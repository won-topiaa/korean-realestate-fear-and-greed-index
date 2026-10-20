"""수도권·광역시 실거래 처음 채우기 (GitHub Actions용 — 맥 없이 매일 이어받기).

받은 거래는 저장소 열(molit_store.COLS)만 남겨 data/molit_kr/partial/{코드}.csv.gz에 쌓고, 받은 (코드, 월)은 partial/done.json에 적는다
(거래가 0건인 달도 적어야 다시 받지 않는다). 단지 이름·동·지번은 단지 표(data/molit_kr/complexes.csv)에 바로 고쳐 넣는다.
지역 하나가 2006년 1월부터 끝까지 다 차면 지역 저장소(data/molit_kr/trades_*.csv.gz)로 옮기고 그 지역의 partial 파일을 지운다.
하루 호출 한도(약 1만 건)나 시간 한도에 걸리면 받은 만큼 저장하고 끝낸다.

모든 지역이 저장소에 들어간 뒤 남은 한도로는 단지 이름 채우기를 한다: 이름을 남기기 전에 받은 거래(부산 옛 거래, 경기 일부)의
단지는 단지 표에 없으므로, 그 단지들이 거래된 (지역 코드, 달)을 적게 골라 다시 받는다 (names_tried.json에 받은 것을 적어 되풀이 안 함).

사용: python region_backfill.py [끝YYYYMM] [--minutes 분] [--max-calls 호출 수]
      (--max-calls: 월간 갱신을 앞둔 날 그 몫의 하루 한도를 남겨 둘 때)
      python region_backfill.py --seed   # 맥에서 region_fetch.py로 받은 구·월 JSON을 partial로 옮긴다 (한 번만)
      python region_backfill.py --names-left   # 이름이 아직 없는 단지 수 (워크플로가 할 일이 남았는지 볼 때)
종료 코드: 0 = 모든 지역 저장소에 있고 단지 이름도 다 채움, 3 = 아직 남음 (한도·시간), 1 = 오류
"""
import datetime as dt
import gzip
import io
import json
import sys
import time

import pandas as pd

import molit_fetch as M
import molit_store as S
import region_store
from regions import REGIONS

PART = region_store.DIR / "partial"
DONE = PART / "done.json"
TRIED = region_store.DIR / "names_tried.json"
START = "200601"


def load_done():
    return json.loads(DONE.read_text()) if DONE.exists() else {}


def save(done, rows):
    """새로 받은 행을 코드별 partial 파일에 덧붙이고 done.json을 쓴다 (내용이 같으면 파일도 같게: gzip 시간 고정).
    단지 표를 먼저 고친다 (끊겨도 done.json에 안 적힌 달은 다시 받으니 이름이 빠지지 않는다)."""
    PART.mkdir(parents=True, exist_ok=True)
    region_store.update_complexes([r for new in rows.values() for r in new])
    for lawd, new in rows.items():
        if not new:
            continue
        path = PART / f"{lawd}.csv.gz"
        old = pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else pd.DataFrame(columns=S.COLS)
        nf = S._frame(new, lawd).astype(str)
        again = set(zip(nf["dealYear"], nf["dealMonth"]))  # 지난 실행이 이 파일을 쓰고 done.json은 못 쓴 채 끊겼으면 같은 달이 또 옴
        old = old[[ym not in again for ym in zip(old["dealYear"], old["dealMonth"])]]
        df = pd.concat([old, nf], ignore_index=True).fillna("")
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
            gz.write(df.to_csv(index=False).encode())
        tmp = path.with_suffix(".gz.tmp")
        tmp.write_bytes(buf.getvalue())
        tmp.replace(path)
        new.clear()
    tmp = DONE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({k: sorted(v) for k, v in sorted(done.items())}, ensure_ascii=False))
    tmp.replace(DONE)


def merge(rid):
    """다 찬 지역을 지역 저장소로 옮기고 partial을 지운다."""
    parts = [pd.read_csv(PART / f"{l}.csv.gz", dtype=str, keep_default_na=False)
             for l in REGIONS[rid]["lawd"] if (PART / f"{l}.csv.gz").exists()]
    store = region_store.load() if region_store.exists() else pd.DataFrame(columns=S.COLS)
    store = store[~store["lawd"].isin(REGIONS[rid]["lawd"])]
    df = pd.concat([store, *parts], ignore_index=True).fillna("")
    bad = ~(df["dealYear"].str.isdigit() & df["dealMonth"].str.isdigit())
    if bad.any():  # 연·월이 빈 행은 저장소 파일을 나눌 수 없다 (한 줄 때문에 병합이 매번 실패하지 않게 빼고 알림)
        print(f"  알림: 거래 연·월이 비어 뺀 행 {int(bad.sum())}개", flush=True)
        df = df[~bad]
    S.save(df, d=region_store.DIR)  # 연도 파일을 다 쓴 뒤 한꺼번에 바꾼다 (실패하면 지난 저장소·partial 그대로)
    keep = {f"trades_{y}.csv.gz" for y in df["dealYear"].unique()}
    for old in S.files(region_store.DIR):  # 거래가 없어진 연도 파일만 정리
        if old.name not in keep:
            old.unlink()
    done = load_done()
    for l in REGIONS[rid]["lawd"]:
        (PART / f"{l}.csv.gz").unlink(missing_ok=True)
        done.pop(l, None)
    save(done, {})
    return len(df)


def seed():
    """맥에서 받은 JSON (data/raw/molit/apt_kr) 중 지역 저장소에 아직 없는 지역의 것을 partial로 옮긴다."""
    import region_fetch as F
    have = set(region_store.regions_in_store())
    done, rows, n = load_done(), {}, 0
    for rid, d in REGIONS.items():
        if rid in have:
            continue
        for lawd in d["lawd"]:
            for f in sorted(F.OUT.glob(f"{lawd}_*.json")):
                ym = f.stem.split("_")[1]
                if ym in done.get(lawd, []):
                    continue
                rows.setdefault(lawd, []).extend(json.loads(f.read_text()))
                done.setdefault(lawd, []).append(ym)
                n += 1
    save(done, rows)
    return n


def fetch_retry(lawd, ym, t0, minutes):
    """잠깐 끊긴 경우만 다시 (한도는 QuotaExceeded로 바로 멈춤). 끝내 못 받으면 None."""
    for attempt in range(4):
        try:
            return M.fetch(lawd, ym)
        except RuntimeError as e:
            print(f"  재시도 {attempt + 1}: {str(e)[:120]}", flush=True)
            if time.time() - t0 > minutes * 60:  # 재시도가 길어져 작업 시간 한도를 넘기지 않게
                return None
            time.sleep(30 * (attempt + 1))
    return None


def names_todo():
    """이름이 없는 단지 → 그 단지들이 거래된 (지역 코드, YYYYMM)별 단지 묶음 (이미 다시 받아 본 달은 뺌)."""
    if not region_store.exists():
        return {}, set()
    st = region_store.load()
    st = st[(st["aptSeq"] != "") & ~st["aptSeq"].isin(set(region_store.load_complexes()["aptSeq"]))]
    tried = set(json.loads(TRIED.read_text())) if TRIED.exists() else set()
    st = st.assign(ym=st["dealYear"] + st["dealMonth"].str.zfill(2))
    st = st[~(st["lawd"] + "_" + st["ym"]).isin(tried)]
    sets = {k: set(v) for k, v in st.groupby(["lawd", "ym"])["aptSeq"]}
    return sets, set(st["aptSeq"])


def fill_names(t0, minutes, max_calls=None):
    """이름 없는 단지를 가장 적은 호출로 덮도록 (지역 코드, 달)을 하나씩 골라 다시 받는다 (욕심쟁이 덮기: 남은 단지를 가장 많이
    덮는 달부터). 반환: (호출 수, 남은 단지 수)."""
    sets, left = names_todo()
    tried = set(json.loads(TRIED.read_text())) if TRIED.exists() else set()
    calls, rows = 0, []

    def flush():
        region_store.update_complexes(rows)
        TRIED.write_text(json.dumps(sorted(tried)))
        rows.clear()
    try:
        while left and sets:
            (lawd, ym), got_set = max(sets.items(), key=lambda kv: (len(kv[1] & left), kv[0][1]))
            if not got_set & left:
                break
            if time.time() - t0 > minutes * 60 or (max_calls is not None and calls >= max_calls):
                print(f"시간·호출 한도 — 단지 이름 채우기 {calls}회 후 멈춤", flush=True)
                break
            del sets[(lawd, ym)]
            got = fetch_retry(lawd, ym, t0, minutes)
            if got is None:
                continue
            calls += 1
            tried.add(f"{lawd}_{ym}")
            rows.extend(got)
            left -= {r.get("aptSeq") for r in got}
            if calls % 100 == 0:
                flush()
                print(f"  단지 이름 · 호출 {calls} · 남은 단지 {len(left):,}", flush=True)
            time.sleep(0.15)
    finally:  # 한도에 걸려도 받은 만큼은 남긴다
        flush()
    return calls, len(left)


def main(end, minutes, max_calls=None):
    t0, calls = time.time(), 0
    done, rows = load_done(), {}
    have = set(region_store.regions_in_store())
    try:
        for rid, d in REGIONS.items():
            if rid in have:
                continue
            for ym in M.months(START, end):
                for lawd in d["lawd"]:
                    if ym in done.get(lawd, []):
                        continue
                    if time.time() - t0 > minutes * 60 or (max_calls is not None and calls >= max_calls):
                        save(done, rows)
                        print(f"시간·호출 한도 ({minutes}분 · {max_calls or '-'}회) — 호출 {calls}회 후 멈춤", flush=True)
                        return 3
                    got = fetch_retry(lawd, ym, t0, minutes)
                    if got is None:
                        continue  # 이번에는 건너뛰고 다음 실행에 다시 (시간 한도를 넘겼으면 다음 차례에서 멈춤)
                    rows.setdefault(lawd, []).extend(got)
                    done.setdefault(lawd, []).append(ym)
                    calls += 1
                    if calls % 300 == 0:
                        save(done, rows)
                        print(f"  {d['name']} {ym} · 호출 {calls} · {time.time() - t0:.0f}s", flush=True)
                    time.sleep(0.15)
            save(done, rows)
            if all(ym in done.get(l, []) for l in d["lawd"] for ym in M.months(START, end)):
                print(f"{d['name']} 완료 → 지역 저장소 {merge(rid):,}건", flush=True)
                done = load_done()
            else:  # 한두 달이 끊겨도 남은 한도로 다음 지역은 계속 받는다 (끝의 '남은 지역'이 3을 돌려줌)
                print(f"{d['name']}: 이번에 못 받은 달이 있어 다음 실행에 이어받기", flush=True)
    except M.QuotaExceeded:
        save(done, rows)
        print(f"하루 호출 한도 — 호출 {calls}회 후 멈춤", flush=True)
        return 3
    left = [REGIONS[r]["name"] for r in REGIONS if r not in set(region_store.regions_in_store())]
    print("남은 지역:", left or "없음", flush=True)
    if left:
        return 3
    try:
        n, miss = fill_names(t0, minutes, None if max_calls is None else max_calls - calls)
    except M.QuotaExceeded:
        print("하루 호출 한도 — 단지 이름 채우기는 다음 실행에", flush=True)
        return 3
    print(f"단지 이름 채우기: 호출 {n}회 · 이름이 없는 단지 {miss:,}곳", flush=True)
    return 3 if miss and names_todo()[0] else 0  # 다시 받아도 이름이 안 나온 단지만 남았으면 끝


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("end", nargs="?", default=dt.date.today().strftime("%Y%m"))
    ap.add_argument("--minutes", type=int, default=300)
    ap.add_argument("--max-calls", type=int)
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--names-left", action="store_true")
    a = ap.parse_args()
    if a.names_left:
        print(len(names_todo()[1]))
        sys.exit(0)
    if a.seed:
        print("partial로 옮긴 구·월:", seed())
        sys.exit(0)
    sys.exit(main(a.end, a.minutes, a.max_calls))

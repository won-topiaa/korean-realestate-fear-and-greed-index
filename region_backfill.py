"""수도권·광역시 실거래 처음 채우기 (GitHub Actions용 — 맥 없이 매일 이어받기).

받은 거래는 저장소 열(molit_store.COLS)만 남겨 data/molit_kr/partial/{코드}.csv.gz에 쌓고, 받은 (코드, 월)은 partial/done.json에 적는다
(거래가 0건인 달도 적어야 다시 받지 않는다). 지역 하나가 2006년 1월부터 끝까지 다 차면 지역 저장소(data/molit_kr/trades_*.csv.gz)로
옮기고 그 지역의 partial 파일을 지운다. 하루 호출 한도(약 1만 건)나 시간 한도에 걸리면 받은 만큼 저장하고 끝낸다.

사용: python region_backfill.py [끝YYYYMM] [--minutes 분]
      python region_backfill.py --seed   # 맥에서 region_fetch.py로 받은 구·월 JSON을 partial로 옮긴다 (한 번만)
종료 코드: 0 = 모든 지역 저장소에 있음, 3 = 아직 남음 (한도·시간), 1 = 오류
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
START = "200601"


def load_done():
    return json.loads(DONE.read_text()) if DONE.exists() else {}


def save(done, rows):
    """새로 받은 행을 코드별 partial 파일에 덧붙이고 done.json을 쓴다 (내용이 같으면 파일도 같게: gzip 시간 고정)."""
    PART.mkdir(parents=True, exist_ok=True)
    for lawd, new in rows.items():
        if not new:
            continue
        path = PART / f"{lawd}.csv.gz"
        old = pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else pd.DataFrame(columns=S.COLS)
        df = pd.concat([old, S._frame(new, lawd)], ignore_index=True).fillna("")
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
    for old in S.files(region_store.DIR):  # 연도 파일을 통째로 다시 쓰므로 지난 파일부터 정리
        old.unlink()
    S.save(df, d=region_store.DIR)
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


def main(end, minutes):
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
                    if time.time() - t0 > minutes * 60:
                        save(done, rows)
                        print(f"시간 한도 {minutes}분 — 호출 {calls}회 후 멈춤", flush=True)
                        return 3
                    for attempt in range(4):  # 잠깐 끊긴 경우만 다시 (한도는 바로 멈춤)
                        try:
                            got = M.fetch(lawd, ym)
                            break
                        except RuntimeError as e:
                            print(f"  재시도 {attempt + 1}: {str(e)[:120]}", flush=True)
                            time.sleep(30 * (attempt + 1))
                    else:
                        continue  # 이번에는 건너뛰고 다음 실행에 다시
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
            else:
                print(f"{d['name']}: 이번에 못 받은 달이 있어 다음 실행에 이어받기", flush=True)
                return 3
    except M.QuotaExceeded:
        save(done, rows)
        print(f"하루 호출 한도 — 호출 {calls}회 후 멈춤", flush=True)
        return 3
    left = [REGIONS[r]["name"] for r in REGIONS if r not in set(region_store.regions_in_store())]
    print("남은 지역:", left or "없음", flush=True)
    return 3 if left else 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("end", nargs="?", default=dt.date.today().strftime("%Y%m"))
    ap.add_argument("--minutes", type=int, default=300)
    ap.add_argument("--seed", action="store_true")
    a = ap.parse_args()
    if a.seed:
        print("partial로 옮긴 구·월:", seed())
        sys.exit(0)
    sys.exit(main(a.end, a.minutes))

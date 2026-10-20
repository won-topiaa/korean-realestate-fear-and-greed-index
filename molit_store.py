"""국토부 실거래(서울 아파트) 저장소: 필요한 열만 담은 연도별 압축 CSV (data/molit/trades_YYYY.csv.gz).

연도별로 나눠서 매달 갱신 때 최근 연도 파일만 바뀌게 한다 (저장소가 매달 통째로 커지지 않도록).
gzip 헤더 시간을 고정해, 내용이 같으면 파일도 바이트 단위로 같다.
단지 이름·주소처럼 거래마다 같은 값은 단지 표(data/molit/complexes.csv)에 한 번만 둔다 (단지 검색용).
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DIR = ROOT / "data" / "molit"
JSON_DIR = ROOT / "data" / "raw" / "molit" / "apt"
COLS = ["lawd", "aptSeq", "excluUseAr", "floor", "dealYear", "dealMonth", "dealDay", "dealAmount", "cdealType", "dealingGbn"]
COMPLEX = DIR / "complexes.csv"
CCOLS = ["aptSeq", "aptNm", "names", "umdNm", "jibun", "buildYear", "umdCd", "bonbun", "bubun", "last"]


def _frame(rows, lawd):
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df["lawd"] = lawd
    return df.reindex(columns=COLS)


def files(d=DIR):
    return sorted(d.glob("trades_*.csv.gz"))


def exists(d=DIR):
    return bool(files(d))


def load(d=DIR):
    return pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in files(d)], ignore_index=True)


def save(df, years=None, d=DIR):
    """years를 주면 그 연도 파일만 다시 쓴다. d: 저장 폴더 (지역 저장소는 data/molit_kr)."""
    d.mkdir(parents=True, exist_ok=True)
    tmps = []
    for y, part in df.groupby("dealYear"):
        if years is not None and str(y) not in years:
            continue
        part = part.assign(_m=part["dealMonth"].astype(int), _d=pd.to_numeric(part["dealDay"], errors="coerce").fillna(0))
        part = part.sort_values(["_m", "lawd", "_d", "aptSeq", "dealAmount"]).drop(columns=["_m", "_d"])
        tmp = d / f"trades_{y}.csv.gz.tmp"
        part.to_csv(tmp, index=False, compression={"method": "gzip", "compresslevel": 9, "mtime": 0})
        tmps.append(tmp)
    for tmp in tmps:  # 모든 연도를 다 쓴 뒤에 바꾼다: 중간에 끊기거나 이상한 행에 걸려도 지난 파일 그대로
        tmp.replace(tmp.with_suffix(""))


def load_complexes(path=COMPLEX):
    if not path.exists():
        return pd.DataFrame(columns=CCOLS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def update_complexes(rows, path=COMPLEX):
    """새로 받은 거래 행으로 단지 표를 고친다: 가장 최근 거래의 이름·주소를 쓰고, 예전 이름은 names에 남긴다 (검색용).
    path: 단지 표 파일 (지역 저장소는 data/molit_kr/complexes.csv)."""
    new = pd.DataFrame([r for r in rows if r.get("aptSeq")])
    if new.empty:
        return len(load_complexes(path))
    new = new.reindex(columns=[c for c in CCOLS if c not in ("names", "last")] + ["dealYear", "dealMonth"]).fillna("")
    new["last"] = new["dealYear"] + new["dealMonth"].str.zfill(2)
    old = load_complexes(path)
    both = pd.concat([old.assign(_o=0), new.drop(columns=["dealYear", "dealMonth"]).assign(_o=1)], ignore_index=True).fillna("")
    both = both.sort_values(["aptSeq", "last", "_o"], kind="mergesort")
    both["_n"] = both["names"].where(both["names"] != "", both["aptNm"])
    names = both.groupby("aptSeq")["_n"].agg(  # 최근 이름이 앞
        lambda s: "|".join(dict.fromkeys(n for x in reversed(list(s)) for n in x.split("|") if n)))
    out = both.groupby("aptSeq").last()  # 최근 거래 기준 (코드는 빈 칸이 아닌 마지막 값을 따로 채움)
    for c in ["umdCd", "bonbun", "bubun"]:
        known = both[both[c] != ""].groupby("aptSeq")[c].last()
        out[c] = known.reindex(out.index).fillna("")
    out["names"] = names.reindex(out.index)
    out = out.reset_index().reindex(columns=CCOLS).sort_values("aptSeq")
    tmp = path.with_suffix(".csv.tmp")
    out.to_csv(tmp, index=False)
    tmp.replace(path)
    return len(out)


def consolidate_from_json():
    frames, rows = [], []
    for f in sorted(JSON_DIR.glob("*.json")):
        r = json.loads(f.read_text())
        frames.append(_frame(r, f.stem.split("_")[0]))
        rows += r
    df = pd.concat([f for f in frames if len(f)], ignore_index=True).fillna("")
    save(df)
    COMPLEX.unlink(missing_ok=True)
    update_complexes(rows)
    return len(df)


def replace_months(new_by_month):
    """new_by_month: {"YYYYMM": [(lawd, rows), ...]} — 해당 계약월 행을 새 자료로 통째로 교체 (바뀐 연도 파일만 다시 씀)."""
    df = load()
    ym = df["dealYear"] + df["dealMonth"].str.zfill(2)
    df = df[~ym.isin(set(new_by_month))]
    add = [_frame(rows, lawd) for m in new_by_month.values() for lawd, rows in m]
    df = pd.concat([df] + add, ignore_index=True).fillna("")
    save(df, years={m[:4] for m in new_by_month})
    update_complexes([r for m in new_by_month.values() for _, rows in m for r in rows])
    return len(df)


if __name__ == "__main__":
    old = DIR / "trades.csv.gz"
    if old.exists():  # 예전 단일 파일 → 연도별로 옮김
        save(pd.read_csv(old, dtype=str, keep_default_na=False))
        old.unlink()
    else:
        consolidate_from_json()
    fs = files()
    print(len(fs), "files |", round(sum(f.stat().st_size for f in fs) / 1e6, 1), "MB | rows", len(load()))

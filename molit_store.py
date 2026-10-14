"""국토부 실거래(서울 아파트) 저장소: 필요한 열만 담은 연도별 압축 CSV (data/molit/trades_YYYY.csv.gz).

연도별로 나눠서 매달 갱신 때 최근 연도 파일만 바뀌게 한다 (저장소가 매달 통째로 커지지 않도록).
gzip 헤더 시간을 고정해, 내용이 같으면 파일도 바이트 단위로 같다.
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DIR = ROOT / "data" / "molit"
JSON_DIR = ROOT / "data" / "raw" / "molit" / "apt"
COLS = ["lawd", "aptSeq", "excluUseAr", "dealYear", "dealMonth", "dealDay", "dealAmount", "cdealType", "dealingGbn"]


def _frame(rows, lawd):
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df["lawd"] = lawd
    return df.reindex(columns=COLS)


def files():
    return sorted(DIR.glob("trades_*.csv.gz"))


def exists():
    return bool(files())


def load():
    return pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in files()], ignore_index=True)


def save(df, years=None):
    """years를 주면 그 연도 파일만 다시 쓴다."""
    DIR.mkdir(parents=True, exist_ok=True)
    for y, part in df.groupby("dealYear"):
        if years is not None and str(y) not in years:
            continue
        part = part.assign(_m=part["dealMonth"].astype(int), _d=pd.to_numeric(part["dealDay"], errors="coerce").fillna(0))
        part = part.sort_values(["_m", "lawd", "_d", "aptSeq", "dealAmount"]).drop(columns=["_m", "_d"])
        tmp = DIR / f"trades_{y}.csv.gz.tmp"
        part.to_csv(tmp, index=False, compression={"method": "gzip", "compresslevel": 9, "mtime": 0})
        tmp.replace(DIR / f"trades_{y}.csv.gz")  # 쓰다 끊겨도 지난 파일 유지


def consolidate_from_json():
    frames = [_frame(json.loads(f.read_text()), f.stem.split("_")[0]) for f in sorted(JSON_DIR.glob("*.json"))]
    df = pd.concat([f for f in frames if len(f)], ignore_index=True).fillna("")
    save(df)
    return len(df)


def replace_months(new_by_month):
    """new_by_month: {"YYYYMM": [(lawd, rows), ...]} — 해당 계약월 행을 새 자료로 통째로 교체 (바뀐 연도 파일만 다시 씀)."""
    df = load()
    ym = df["dealYear"] + df["dealMonth"].str.zfill(2)
    df = df[~ym.isin(set(new_by_month))]
    add = [_frame(rows, lawd) for m in new_by_month.values() for lawd, rows in m]
    df = pd.concat([df] + add, ignore_index=True).fillna("")
    save(df, years={m[:4] for m in new_by_month})
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

"""수도권·광역시 실거래 저장소 (data/molit_kr/trades_YYYY.csv.gz). 서울 저장소(molit_store)와 같은 열·형식이고, lawd는 지금 지역 코드.

region_fetch.py가 받은 구·월 JSON(data/raw/molit/apt_kr)을 지역 단위로 옮긴다. 2006년 1월부터 빠진 달이 없는 지역만 넣는다
(반쯤 받은 지역이 지수에 섞이지 않게). 단지 검색용 단지 표는 만들지 않는다.

사용: python region_store.py [끝YYYYMM]
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

import molit_store as S
import region_fetch as F
from regions import REGIONS

DIR = Path(__file__).parent / "data" / "molit_kr"


def exists():
    return S.exists(DIR)


def load(rid=None):
    df = S.load(DIR)
    return df[df["lawd"].isin(REGIONS[rid]["lawd"])] if rid else df


def regions_in_store():
    if not exists():
        return []
    have = set(load()["lawd"].unique())
    return [r for r, d in REGIONS.items() if have & set(d["lawd"])]


def consolidate(end):
    """빠진 달이 없는 지역의 JSON을 모두 모아 저장소를 다시 쓴다. 반환: 넣은 지역, 건수."""
    done = [r for r in REGIONS if F.missing(r, "200601", end) == 0]
    frames = []
    for r in done:
        for lawd in REGIONS[r]["lawd"]:
            for f in sorted(F.OUT.glob(f"{lawd}_*.json")):
                frames.append(S._frame(json.loads(f.read_text()), lawd))
    if not frames:
        return done, 0
    df = pd.concat([f for f in frames if len(f)], ignore_index=True).fillna("")
    for old in S.files(DIR):  # 연도 파일을 통째로 다시 쓰므로 지난 파일부터 정리
        old.unlink()
    S.save(df, d=DIR)
    return done, len(df)


def replace_months(new_by_month):
    """{"YYYYMM": [(lawd, rows), ...]} — 그 계약월 행을 새 자료로 교체 (월간 갱신용, 바뀐 연도 파일만 다시 씀)."""
    df = load()
    ym = df["dealYear"] + df["dealMonth"].str.zfill(2)
    codes = {lawd for m in new_by_month.values() for lawd, _ in m}
    df = df[~(ym.isin(set(new_by_month)) & df["lawd"].isin(codes))]
    add = [S._frame(rows, lawd) for m in new_by_month.values() for lawd, rows in m]
    df = pd.concat([df] + add, ignore_index=True).fillna("")
    S.save(df, years={m[:4] for m in new_by_month}, d=DIR)
    return len(df)


if __name__ == "__main__":
    end = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().strftime("%Y%m")
    done, n = consolidate(end)
    fs = S.files(DIR)
    print("지역:", [REGIONS[r]["name"] for r in done], f"| 거래 {n:,}건 | {len(fs)}개 파일 {sum(f.stat().st_size for f in fs) / 1e6:.1f} MB")

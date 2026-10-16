"""신고가 단지 → results_highs/highs.json (사이트 빌드 때 site/highs/data/로 복사, 저장소에는 안 올림).

신고가 = 같은 단지·같은 전용면적(0.01㎡까지 같은 집)에서 2006년 이후 신고된 모든 거래가보다 비싸게 계약된 거래.
- 해제·직거래 제외. 그 집 크기의 첫 거래(비교할 이전 거래 없음)는 세지 않는다.
- 직전 최고가보다 2배 넘게 비싼 거래는 입력 오류일 수 있어 목록에서 빼고 개수만 남긴다.
- 최근 4개 달 목록 + 최근 36개 달 서울 신고가 비중(비교 가능한 거래 중 신고가 비율).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import molit_store
from apt_score import LAWD2GU

ROOT = Path(__file__).parent
OUT = ROOT / "results_highs"
MONTHS, TREND = 4, 36
JUMP = 2.0  # 직전 최고가의 2배 초과는 목록에서 뺌


def trades():
    df = molit_store.load()
    df = df[(df["cdealType"] == "") & (df["dealingGbn"] != "직거래")].copy()
    df["price"] = pd.to_numeric(df["dealAmount"].str.replace(",", ""), errors="coerce")
    df["area"] = pd.to_numeric(df["excluUseAr"], errors="coerce").round(2)
    df["floor"] = pd.to_numeric(df["floor"], errors="coerce")
    df = df[(df["price"] > 0) & (df["area"] > 0)].copy()
    df["date"] = pd.to_datetime(dict(year=df["dealYear"].astype(int), month=df["dealMonth"].astype(int),
                                     day=pd.to_numeric(df["dealDay"], errors="coerce").fillna(15).astype(int)))
    df["ym"] = df["date"].dt.strftime("%Y-%m")
    df = df.sort_values(["aptSeq", "area", "date", "price"], kind="mergesort").reset_index(drop=True)
    g = df.groupby(["aptSeq", "area"], sort=False)
    df["n_prev"] = g.cumcount()
    cmax = g["price"].cummax()
    df["prevmax"] = cmax.groupby([df["aptSeq"], df["area"]]).shift()
    at = df["date"].where(df["price"] == cmax)  # 최고가가 처음 나온 날 (같은 값이 다시 나오면 그날)
    df["prevdate"] = at.groupby([df["aptSeq"], df["area"]]).ffill().groupby([df["aptSeq"], df["area"]]).shift()
    df["high"] = (df["n_prev"] > 0) & (df["price"] > df["prevmax"])
    return df


def main():
    OUT.mkdir(exist_ok=True)
    df = trades()
    cx = molit_store.load_complexes().set_index("aptSeq")
    yms = sorted(df["ym"].unique())
    cmp_ = df[df["n_prev"] > 0]
    by = cmp_.groupby("ym")["high"].agg(["sum", "count"])
    trend = [[ym, int(by.loc[ym, "sum"]), int(by.loc[ym, "count"])] for ym in yms[-TREND:] if ym in by.index]
    months = []
    for ym in yms[-MONTHS:][::-1]:
        m = df[df["ym"] == ym]
        c = m[m["n_prev"] > 0]
        h = c[c["high"]]
        jump = h["price"] > JUMP * h["prevmax"]
        rows = []
        for r in h[~jump].sort_values("price", ascending=False).itertuples():
            info = cx.loc[r.aptSeq] if r.aptSeq in cx.index else None
            rows.append([r.aptSeq, "" if info is None else info["aptNm"], r.lawd, "" if info is None else info["umdNm"],
                         float(r.area), None if np.isnan(r.floor) else int(r.floor), r.date.strftime("%Y-%m-%d"),
                         int(r.price), int(r.prevmax), r.prevdate.strftime("%Y-%m"), int(r.n_prev)])
        gu = {}
        for code, sub in c.groupby("lawd"):
            gu[code] = [int(sub["high"].sum()), int(len(sub))]
        months.append({"ym": ym, "n": int(len(m)), "cmp": int(len(c)), "high": int((~jump).sum()), "jump": int(jump.sum()),
                       "complexes": int(h[~jump]["aptSeq"].nunique()), "gu": gu, "rows": rows})
    out = {"asof": df["date"].max().strftime("%Y-%m-%d"), "gu_names": LAWD2GU, "months": months, "trend": trend}
    (OUT / "highs.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    m = months[1] if len(months) > 1 else months[0]  # 다 들어온 지난달 (없으면 이번 달)
    print(f"신고가: {m['ym']} 신고가 {m['high']:,}건 (비교 가능 {m['cmp']:,}건의 {m['high'] / max(1, m['cmp']):.0%}, 단지 {m['complexes']:,}곳, "
          f"2배 초과 제외 {m['jump']}) · {(OUT / 'highs.json').stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()

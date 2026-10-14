"""실거래 반복매매지수의 '그때 알 수 있던 값' (보고서 비교 기준용) → data/repeat_sales_rt.csv

반복매매지수는 나중 거래가 들어오면 과거 값도 다시 추정된다. 그래서 지금 지수로 만든 과거의 6개월 가격 변화는
그 시점에 실제로 알 수 있던 값과 다르다. 달마다 그 달 20일 기준(실거래 신고 시차 2개월)으로 알 수 있던 거래만으로
지수를 다시 추정해 직전 6개월 변화를 기록한다. 이미 계산한 달은 다시 계산하지 않는다(매달 한 달씩 덧붙임).
"""
import numpy as np
import pandas as pd

import molit_indicators as MI
from backtest import ROOT

OUT = ROOT / "data" / "repeat_sales_rt.csv"
START = pd.Timestamp("2007-01-01")


def main():
    have = pd.read_csv(OUT, index_col=0, parse_dates=True) if OUT.exists() else pd.DataFrame(columns=["d6", "d3"])
    tr = MI.load()
    last = tr["date"].max()
    months = [t for t in pd.date_range(START, last, freq="MS") if t not in have.index]
    rows = {}
    for t in months:
        v, _ = MI.repeat_sales(tr[tr["date"] <= t - pd.DateOffset(months=2)])
        lv = np.log(v)
        g = lambda k: lv.get(t - pd.DateOffset(months=k), np.nan)
        rows[t] = {"d6": g(2) - g(8), "d3": g(2) - g(5)}
    out = pd.concat([have, pd.DataFrame(rows).T]).sort_index() if rows else have
    out.index.name = "date"
    tmp = OUT.with_suffix(".csv.tmp")
    out.to_csv(tmp)
    tmp.replace(OUT)
    print(f"그때 알 수 있던 실거래 변화: {len(rows)}개월 새로 계산, 총 {len(out)}개월 ({out.index.min().date()}~{out.index.max().date()})")


if __name__ == "__main__":
    main()

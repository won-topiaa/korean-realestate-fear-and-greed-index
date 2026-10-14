"""v2: 새 지표 포함 + 정답 3종(KB / 부동산원 / 실거래 반복매매지수)으로 같은 백테스트를 반복.

결과: results_v2/<정답>/*.csv, results_v2/summary.csv
"""
import json
import sys

import numpy as np
import pandas as pd

import backtest as bt

TARGETS = sys.argv[1:] or ["KB", "부동산원", "실거래"]
V1 = ['설문_매수우위변화', '설문_가격전망', '전세_수급', '전세_가격전망', '전세_3개월모멘텀', '자금_기준금리변화',
      '자금_주담대금리변화', '자금_국고채10년변화', '관심_아파트', '관심_부동산', '관심_집값', '관심_청약', '관심_갭투자',
      '관심_공포어역수', '시장_건설주모멘텀', '시장_건설주상대강도', '시장_KOSPI모멘텀', '가격_3개월모멘텀',
      '가격_선도50모멘텀', '가격_상승구비율', '설문_매수우위', '설문_거래활발', '전세_매매선호', '가격_12개월이평괴리',
      '자금_기준금리수준', '자금_가계신용증가']
SPEED = ["선행", "동행", "후행"]


def two_level(scores, groups):
    return pd.concat([bt.composite(scores, g) for g in groups if g], axis=1).mean(axis=1, skipna=True)


def candidates(scores, meta):
    core = meta[~meta["주제"].isin(["가격부담", "공급"])]
    v1 = meta.loc[V1]
    out = {
        "v1 (26개, 기존)": two_level(scores, [list(v1.index[v1["속도"] == v]) for v in SPEED]),
        "v2 (속도 3그룹, 새 지표 포함)": two_level(scores, [list(core.index[core["속도"] == v]) for v in SPEED]),
        "v2 주제 그룹 균등": two_level(scores, [list(core.index[core["주제"] == t]) for t in core["주제"].unique()]),
        "전체 지표 균등": bt.composite(scores, scores.columns),
    }
    for t in meta["주제"].unique():
        out[f"주제: {t}"] = bt.composite(scores, meta.index[meta["주제"] == t])
    for c in meta.index:
        out[f"지표: {c}"] = scores[c]
    return out


def main():
    rows = []
    for tgt in TARGETS:
        bt.TARGET = tgt
        bt.OUT = bt.ROOT / "results_v2" / tgt
        bt.OUT.mkdir(parents=True, exist_ok=True)
        scores, meta, targets, mom, price = bt.load()
        for name, s in candidates(scores, meta).items():
            r = bt.evaluate(s, targets, mom)
            m = bt.window_mask(s.index, bt.FULL)
            lo, hi = (bt.block_bootstrap_ic(s[m].to_numpy(), targets["선행12"][m].to_numpy(), n=300)
                      if not name.startswith("지표") else (np.nan, np.nan))
            rows.append({"정답": tgt, "후보": name, "학습": r["학습_선행12"], "검증": r["검증_선행12"],
                         "안정성": np.nanmin([r["학습_선행12"], r["검증_선행12"]]) if not np.isnan(r["학습_선행12"]) else np.nan,
                         "전체": r["전체_선행12"], "동행_전체": r["전체_동행"], "가격외정보": r["전체_선행12_추가정보"],
                         "CI5": lo, "CI95": hi, "시작": r["커버리지시작"], "현재": s.dropna().iloc[-1] if s.notna().any() else np.nan})
        scores.to_csv(bt.OUT / "indicator_scores.csv")
        print("done", tgt, "| 정답 기간", price.first_valid_index().date(), "~", price.last_valid_index().date(), flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(bt.ROOT / "results_v2" / "summary.csv", index=False)
    return df


if __name__ == "__main__":
    df = main()
    pd.set_option("display.width", 250)
    pv = df.pivot_table(index="후보", columns="정답", values=["학습", "검증", "안정성"]).round(2)
    print(pv.to_string())

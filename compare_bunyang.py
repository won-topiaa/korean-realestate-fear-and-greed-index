"""추천 v1에 분양물량을 다시 넣었을 때 비교 (후행 배치 / 측정된 시차대로 선행 배치)."""
import numpy as np
import pandas as pd

import backtest as bt

scores, meta, targets, mom, price = bt.load()
core = meta[~meta["주제"].isin(["가격부담", "공급"])]
SPEED = ["선행", "동행", "후행"]


def index(extra=None, where=None):
    groups = {v: list(core.index[core["속도"] == v]) for v in SPEED}
    if extra:
        groups[where].append(extra)
    return pd.concat([bt.composite(scores, groups[v]) for v in SPEED], axis=1).mean(axis=1, skipna=True)


variants = {
    "v1 (26개)": index(),
    "v1 + 분양물량 (후행에)": index("공급_분양물량", "후행"),
    "v1 + 분양물량 (선행에)": index("공급_분양물량", "선행"),
    "31개 전체": pd.concat([bt.composite(scores, meta.index[meta["속도"] == v]) for v in SPEED], axis=1).mean(axis=1),
}
SUB = ("2013-01-01", "2026-12-01")  # 분양물량 점수가 존재하는 구간
rows = []
for name, s in variants.items():
    r = bt.evaluate(s, targets, mom)
    m = bt.window_mask(s.index, bt.FULL)
    lo, hi = bt.block_bootstrap_ic(s[m].to_numpy(), targets["선행12"][m].to_numpy())
    ms = bt.window_mask(s.index, SUB)
    lag, lagic = bt.best_lag(s, price)
    b = {}
    for a, z, lab in [(0, 25, "극공포"), (75, 101, "극탐욕")]:
        sel = m & (s >= a) & (s < z) & targets["선행12"].notna()
        b[lab] = f"{np.expm1(targets['선행12'][sel].mean())*100:+.1f}% ({sel.sum()}개월)"
    rows.append({
        "버전": name,
        "학습_선행12": r["학습_선행12"], "검증_선행12": r["검증_선행12"],
        "안정성": min(r["학습_선행12"], r["검증_선행12"]),
        "2013~_선행12": bt.spearman(s[ms].to_numpy(), targets["선행12"][ms].to_numpy()),
        "학습_동행": r["학습_동행"], "검증_동행": r["검증_동행"],
        "가격외정보": r["전체_선행12_추가정보"], "CI": f"{lo:.2f}~{hi:.2f}", "선행시차": lag,
        **b, "현재": s.iloc[-1],
    })
df = pd.DataFrame(rows).set_index("버전")
pd.set_option("display.width", 250)
print(df.round(2).to_string())

s = scores["공급_분양물량"]
print("\n분양물량 단독: 점수 시작", s.first_valid_index().date(), "| 현재 점수", round(s.iloc[-1], 1))
print("분양물량 단독 선행시차:", bt.best_lag(s, price))
# 분양물량과 다른 v1 지표의 상관 (중복 정보인지)
corr = scores[list(core.index) + ["공급_분양물량"]].corr()["공급_분양물량"].drop("공급_분양물량").sort_values()
print("v1 지표와의 상관 상위/하위:\n", corr.round(2).tail(4).to_string(), "\n", corr.round(2).head(3).to_string())
raw = pd.read_csv("data/raw/kb/분양물량.csv")
raw = raw[(raw["일정"] >= 202501) & (raw["일정"] <= 202612)][["일정", "합계.세대수"]]
print("\n최근 서울 분양 세대수 (월):", raw.to_string(index=False))

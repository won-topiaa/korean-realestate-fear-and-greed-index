"""시점 의존성 진단: 지표별 장기 추세·구조 단절·점수 고착(0/100에 붙어 있는 기간) + 구성 지표 수 변화."""
import numpy as np
import pandas as pd
from scipy.stats import ks_2samp, spearmanr

import backtest as bt

bt.TARGET = "실거래"
NOT_REALTIME = ("공급_분양물량", "공급_향후입주역수")
raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
raw = raw[raw.index <= raw["__price"].last_valid_index()]
meta = pd.read_csv(bt.ROOT / "data" / "indicator_meta.csv", index_col=0).fillna("")
meta = meta.loc[[c for c in meta.index if c not in NOT_REALTIME]]
raw = raw[meta.index]
sc = raw.apply(bt.pct_score)
E = raw.index >= "2006-01-01"


def longest_run(mask):
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


rows = []
for c in meta.index:
    s = raw.loc[E, c].dropna()
    if len(s) < 48:
        continue
    t = np.arange(len(s))
    a, b = s[s.index < "2016-01-01"], s[s.index >= "2016-01-01"]
    shift = (b.mean() - a.mean()) / s.std() if len(a) > 24 and len(b) > 24 else np.nan
    ks = ks_2samp(a, b).statistic if len(a) > 24 and len(b) > 24 else np.nan
    z = sc.loc[E, c].dropna()
    rows.append({"지표": c, "주제": meta.loc[c, "주제"], "시작": str(s.index[0].date())[:7],
                 "추세ρ": spearmanr(t, s).statistic, "전후반_평균이동σ": shift, "KS": ks,
                 "점수고착%": ((z >= 95) | (z <= 5)).mean() * 100,
                 "최장고착개월": longest_run(((z >= 90) | (z <= 10)).to_numpy())})
d = pd.DataFrame(rows).set_index("지표")
d["경고"] = (d["추세ρ"].abs() > 0.6).astype(int) + (d["전후반_평균이동σ"].abs() > 1.0).astype(int) + (d["최장고착개월"] >= 24).astype(int)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 100)
print(d.sort_values(["경고", "최장고착개월"], ascending=False).round(2).to_string())
d.to_csv(bt.ROOT / "results_v2" / "diag_time.csv")

n_av = sc.loc[E].notna().sum(axis=1)
print("\n월별 사용 가능한 지표 수:", {str(k.year): int(v) for k, v in n_av.resample("YE").last().items()})
by = {v: sc.loc[E, meta.index[meta["속도"] == v]].notna().sum(axis=1).resample("YE").last() for v in ["선행", "동행", "후행"]}
print("그룹별 지표 수 (2006/2012/2020/2026):", {v: [int(s.iloc[i]) for i in (0, 6, 14, -1)] for v, s in by.items()})

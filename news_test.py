"""빅카인즈 뉴스 언급 지표 백테스트 (v3 틀 안에서)."""
import numpy as np
import pandas as pd

import backtest as bt
import remedies as RM
import v3
from news_indicators import META_NEWS

raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
raw = raw[raw.index <= raw["__price"].last_valid_index()]
news = pd.read_csv(bt.ROOT / "data" / "news_indicators.csv", index_col=0, parse_dates=True).reindex(raw.index)
meta, _ = v3.load_meta()
cols = list(meta.columns)
nmeta = pd.DataFrame.from_dict(META_NEWS, orient="index", columns=cols)
allmeta = pd.concat([meta, nmeta])
X = pd.concat([raw[meta.index], news], axis=1)
sc = v3.scores(X)
P3 = RM.P3


def ics(s, t="실거래"):
    y = RM.Y[t]; s = s.reindex(y.index)
    return [bt.spearman(s[bt.window_mask(s.index, w)].to_numpy(), y[bt.window_mask(s.index, w)].to_numpy()) for w in P3]


def index(m):
    return v3.spread(pd.concat([bt.composite(sc, m.index[m["속도"] == v]) for v in v3.SPEED], axis=1).mean(axis=1))


rows = []
for c in nmeta.index:
    a = ics(sc[c]); rows.append({"지표": c.replace("뉴스_", ""), "06–12": a[0], "13–19": a[1], "20–26": a[2], "최저": np.nanmin(a), "KB최저": np.nanmin(ics(sc[c], "KB")), "현재": sc[c].dropna().iloc[-1]})
g = bt.composite(sc, nmeta.index)
a = ics(g); rows.append({"지표": "[뉴스 전체]", "06–12": a[0], "13–19": a[1], "20–26": a[2], "최저": min(a), "KB최저": min(ics(g, "KB")), "현재": g.dropna().iloc[-1]})
gg = bt.composite(sc, meta.index[meta["주제"] == "관심"])
a = ics(gg); rows.append({"지표": "[구글 검색 전체]", "06–12": a[0], "13–19": a[1], "20–26": a[2], "최저": min(a), "KB최저": min(ics(gg, "KB")), "현재": gg.dropna().iloc[-1]})
pd.set_option("display.width", 220)
print(pd.DataFrame(rows).set_index("지표").round(2).to_string())
print("뉴스 전체 선행시차:", bt.best_lag(g, np.exp(np.log(pd.read_csv(bt.ROOT / 'data' / 'targets_extra.csv', index_col=0, parse_dates=True)['실거래지수']).reindex(g.index))))
print("뉴스 전체 vs 구글 검색 상관:", round(g.corr(gg), 2), "| 뉴스 vs v3 지수 상관:", round(g.corr(index(meta)), 2))

SMALL = ["뉴스_탐욕비중", "뉴스_부동산관심", "뉴스_집값상승", "뉴스_집값하락역수"]
search = list(meta.index[meta["주제"] == "관심"])
var = {
    "v3 그대로": meta,
    "v3 + 뉴스 4개 (선행)": allmeta.loc[list(meta.index) + SMALL],
    "v3 + 뉴스 15개 (선행)": allmeta,
    "v3 − 구글 + 뉴스 4개": allmeta.loc[[c for c in meta.index if c not in search] + SMALL],
    "v3 − 구글 + 뉴스 15개": allmeta.loc[[c for c in allmeta.index if c not in search]],
}
m4 = allmeta.loc[list(meta.index) + SMALL].copy(); m4.loc[SMALL, "속도"] = "동행"
var["v3 + 뉴스 4개 (동행)"] = m4
rows = []
for n, m in var.items():
    s = index(m); a = ics(s); k = ics(s, "KB")
    rows.append({"구성": n, "지표수": len(m), "06–12": a[0], "13–19": a[1], "20–26": a[2], "최저": min(a), "KB최저": min(k), "현재": s.dropna().iloc[-1]})
print(pd.DataFrame(rows).set_index("구성").round(2).to_string())

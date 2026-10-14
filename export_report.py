"""보고서용 데이터 묶음 (results/report_data.json)."""
import json

import numpy as np
import pandas as pd

import backtest as bt


def r2(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 3)


scores, meta, targets, mom, price = bt.load()
cands, _, _ = bt.build_candidates(scores, meta)
res = pd.read_csv(bt.OUT / "group_results.csv")
ci = pd.read_csv(bt.OUT / "bootstrap_ci.csv")


def two_level(groups):
    return pd.concat([bt.composite(scores, m) for m in groups], axis=1).mean(axis=1, skipna=True)


core = meta[~meta["주제"].isin(["가격부담", "공급"])]
speed = ["선행", "동행", "후행"]
B = two_level([core.index[core["속도"] == v] for v in speed])
C = two_level([meta.index[meta["속도"] == v] for v in speed])
V = bt.composite(scores, meta.index[meta["주제"] == "가격부담"])

m = bt.window_mask(B.index, ("2004-01-01", "2026-12-01"))
series = {
    "dates": [d.strftime("%Y-%m") for d in B.index[m]],
    "B": [r2(v) for v in B[m]],
    "V": [r2(v) for v in V[m]],
    "price": [r2(v) for v in price[m]],
    "fwd12": [r2(v) for v in targets["선행12"][m]],
}


def ev(name, s):
    r = bt.evaluate(s, targets, mom)
    lo, hi = bt.block_bootstrap_ic(s[bt.window_mask(s.index, bt.FULL)].to_numpy(),
                                   targets["선행12"][bt.window_mask(s.index, bt.FULL)].to_numpy())
    return {"name": name, "train": r2(r["학습_선행12"]), "test": r2(r["검증_선행12"]),
            "train_now": r2(r["학습_동행"]), "test_now": r2(r["검증_동행"]),
            "extra": r2(r["전체_선행12_추가정보"]), "ci": [r2(lo), r2(hi)],
            "lag": int(bt.best_lag(s, price)[0])}


schemes = [
    ("속도: 선행·동행·후행", series_c := C),
    ("주제: 9개 주제", bt.scheme_indices(scores, meta, cands)["[2단계] 주제 그룹 균등"]),
    ("구분 없이 31개 균등", bt.composite(scores, scores.columns)),
    ("출처: 설문·실측·검색…", bt.scheme_indices(scores, meta, cands)["[2단계] 출처성격 그룹 균등"]),
    ("CNN 7개 지표 복제", bt.composite(scores, meta.index[meta["CNN대응"] != ""])),
    ("행위자: 매수자·중개사…", bt.scheme_indices(scores, meta, cands)["[2단계] 행위자 그룹 균등"]),
    ("시장: 매매·전세·분양·금융", bt.scheme_indices(scores, meta, cands)["[2단계] 시장 그룹 균등"]),
    ("상관 군집 6개 (데이터 기반)", bt.scheme_indices(scores, meta, cands)["[2단계] 상관군집6 그룹 균등"]),
    ("처음 원안: 금리+공급+언급수", bt.composite(scores, meta.index[meta["사용자원안"] != ""])),
]
scheme_rows = [ev(n, s) for n, s in schemes]
rec = ev("추천 v1: 속도 3그룹 − 가격부담·공급", B)

themes = ["수급심리", "가격", "금융시장", "전세", "관심", "자금", "공급", "가격부담"]
theme_rows = [ev(t, bt.composite(scores, meta.index[meta["주제"] == t])) for t in themes]
for row in theme_rows:
    row["n"] = int((meta["주제"] == row["name"]).sum())
    row["members"] = [i.split("_", 1)[1] for i in meta.index[meta["주제"] == row["name"]]]

# 점수 구간별 이후 12개월 서울 아파트 변화 (추천 지수)
mf = bt.window_mask(B.index, bt.FULL)
buckets = []
for lo, hi, lab in [(0, 25, "극단적 공포"), (25, 45, "공포"), (45, 55, "중립"), (55, 75, "탐욕"), (75, 101, "극단적 탐욕")]:
    sel = mf & (B >= lo) & (B < hi) & targets["선행12"].notna()
    y = targets["선행12"][sel]
    buckets.append({"label": lab, "range": f"{lo}–{min(hi, 100)}", "mean": r2(np.expm1(y.mean())),
                    "up": r2((y > 0).mean()), "n": int(sel.sum())})

combos = pd.read_csv(bt.OUT / "indicator_combos.csv")
top = combos.sort_values("학습IC", ascending=False)
overfit = {"n": len(combos), "top10_test": r2(top.head(10)["검증IC"].mean()),
           "top1000_test": r2(top.head(1000)["검증IC"].mean()), "all_test": r2(combos["검증IC"].mean()),
           "rank_corr": r2(combos[["학습IC", "검증IC"]].corr(method="spearman").iloc[0, 1]),
           "best": top.iloc[0]["조합"], "best_train": r2(top.iloc[0]["학습IC"]), "best_test": r2(top.iloc[0]["검증IC"])}

last = B.index[-1]
now = {"date": last.strftime("%Y-%m"), "B": r2(B.iloc[-1]), "C": r2(C.iloc[-1]), "V": r2(V.iloc[-1]),
       "speed": {v: r2(bt.composite(scores, core.index[core["속도"] == v]).iloc[-1]) for v in speed},
       "themes": {t: r2(bt.composite(scores, meta.index[meta["주제"] == t]).iloc[-1]) for t in themes},
       "prev12": r2(B.iloc[-13]), "prev3": r2(B.iloc[-4])}
members = {v: [i.split("_", 1)[1] + f" ({meta.loc[i, '주제']})" for i in core.index[core["속도"] == v]] for v in speed}

snap_dates = ["2006-11", "2008-12", "2012-12", "2015-06", "2018-09", "2020-07", "2021-09", "2022-11", "2024-05", "2025-06"]
snaps = []
for d in snap_dates:
    t = pd.Timestamp(d + "-01")
    snaps.append({"date": d, "B": r2(B.get(t)), "V": r2(V.get(t)), "fwd12": r2(np.expm1(targets["선행12"].get(t)))})

out = {"series": series, "tps": json.load(open(bt.OUT / "turning_points.json")), "schemes": scheme_rows, "rec": rec,
       "themes": theme_rows, "buckets": buckets, "overfit": overfit, "now": now, "members": members, "snaps": snaps,
       "n_ind": int(len(meta)), "n_core": int(len(core)), "n_groups": int(len(res)),
       "n_subsets": int(len(pd.read_csv(bt.OUT / "theme_subsets.csv")))}
json.dump(out, open(bt.OUT / "report_data.json", "w"), ensure_ascii=False)
print(json.dumps({k: v for k, v in out.items() if k != "series"}, ensure_ascii=False, indent=1))

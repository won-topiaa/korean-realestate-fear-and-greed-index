"""v2 보고서 데이터 (results_v2/report_data.json): 정답 = 실거래 반복매매지수, 비교용 KB."""
import json

import numpy as np
import pandas as pd

import backtest as bt

P3 = [("2006-01-01", "2012-12-01", "2006–12"), ("2013-01-01", "2019-12-01", "2013–19"), ("2020-01-01", "2026-12-01", "2020–26")]
NOT_REALTIME = ("공급_분양물량", "공급_향후입주역수")


def r3(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 3)


def ic(s, y, w):
    m = bt.window_mask(s.index, w)
    return bt.spearman(s[m].to_numpy(), y[m].to_numpy())


def grouped(scores, meta, scheme):
    return pd.concat([bt.composite(scores, meta.index[meta[scheme] == g]) for g in meta[scheme].unique()], axis=1).mean(axis=1)


def load(tgt):
    bt.TARGET = tgt
    scores, meta, targets, mom, price = bt.load()
    return scores, meta, targets, mom, price


# ----- 실거래 정답 -----
scores, meta, targets, mom, price = load("실거래")
D = meta.loc[[c for c in meta.index if c not in NOT_REALTIME]]
v2 = grouped(scores, D, "속도")
y = targets["선행12"]


def periods(s, yy=None):
    yy = y if yy is None else yy
    vals = [ic(s, yy, (a, b)) for a, b, _ in P3]
    return [r3(v) for v in vals], r3(np.nanmin(vals))


def row(name, s, kb=None):
    p, mn = periods(s)
    m = bt.window_mask(s.index, bt.FULL)
    lo, hi = bt.block_bootstrap_ic(s[m].to_numpy(), y[m].to_numpy(), n=500)
    out = {"name": name, "p": p, "min": mn, "ci": [r3(lo), r3(hi)]}
    if kb is not None:
        out["kb_min"] = kb
    return out


# KB 정답 쪽 최저값 (같은 후보)
sk, mk, tk, _, pk = load("KB")
Dk = mk.loc[D.index]


def kb_min(fn):
    s = fn(sk, Dk)
    return r3(np.nanmin([ic(s, tk["선행12"], (a, b)) for a, b, _ in P3]))


cands = [
    ("주제별 10그룹", lambda sc, me: grouped(sc, me, "주제")),
    ("속도별 3그룹 (선행·동행·후행)", lambda sc, me: grouped(sc, me, "속도")),
    ("출처별 (설문·실측·검색…)", lambda sc, me: grouped(sc, me, "출처성격")),
    ("시장별 (매매·전세·분양·금융)", lambda sc, me: grouped(sc, me, "시장")),
    ("행위자별 (매수자·중개사…)", lambda sc, me: grouped(sc, me, "행위자")),
    ("구분 없이 균등", lambda sc, me: bt.composite(sc, me.index)),
    ("CNN 대응 지표만", lambda sc, me: bt.composite(sc, me.index[me["CNN대응"] != ""])),
    ("처음 원안 (금리+공급+언급수)", lambda sc, me: bt.composite(sc, me.index[me["사용자원안"] != ""])),
]
schemes = []
for n, fn in cands:
    schemes.append(row(n, fn(scores, D), kb_min(fn)))
schemes.sort(key=lambda r: -(r["min"] if r["min"] is not None else -9))

th = meta["주제"]
core = list(meta.index[~th.isin(["가격부담", "공급"])])
variants = []
for n, mem in [("v1 방식: 가격부담·공급 제외 (40개)", core),
               ("+ 가격부담", core + list(meta.index[th == "가격부담"])),
               ("v2: 실시간 계산 가능한 전부 (45개)", list(D.index)),
               ("전체 47개 (KB 분양·입주 일정 포함)", list(meta.index))]:
    s = grouped(scores, meta.loc[mem], "주제")
    p, mn = periods(s)
    p2, mn2 = periods(grouped(scores, meta.loc[mem], "속도"))
    variants.append({"name": n, "n": len(mem), "p": p2, "min": mn2})

themes = []
for t in D["주제"].unique():
    mem = list(D.index[D["주제"] == t])
    p, mn = periods(bt.composite(scores, mem))
    themes.append({"name": t, "n": len(mem), "p": p, "min": mn, "members": [m.split("_", 1)[1] for m in mem]})
themes.sort(key=lambda r: -(r["min"] if r["min"] is not None else -9))

NEW = ["거래_거래량", "거래_신고가비중", "거래_급락거래역수", "거래_외지인비중", "거래_원정매수비중", "거래_2030비중",
       "거래_법인매수비중", "공급_미분양역수", "설문_부동산원매매수급", "설문_국토연소비심리", "청약_1순위경쟁률",
       "청약_미달역수", "청약_무순위경쟁률", "청약_실제공급", "설문_매수우위"]
singles = []
for c in NEW:
    p, mn = periods(scores[c])
    singles.append({"name": c.split("_", 1)[1], "theme": meta.loc[c, "주제"], "desc": meta.loc[c, "설명"], "p": p, "min": mn,
                    "start": str(scores[c].first_valid_index().date())[:7]})

mf = bt.window_mask(v2.index, bt.FULL)
buckets = []
for lo, hi, lab in [(0, 25, "극단적 공포"), (25, 45, "공포"), (45, 55, "중립"), (55, 75, "탐욕"), (75, 101, "극단적 탐욕")]:
    sel = mf & (v2 >= lo) & (v2 < hi) & y.notna()
    buckets.append({"label": lab, "range": f"{lo}–{min(hi, 100)}", "mean": r3(np.expm1(y[sel].mean())) if sel.any() else None,
                    "up": r3((y[sel] > 0).mean()) if sel.any() else None, "n": int(sel.sum())})

combos = pd.read_csv(bt.ROOT / "results_v2" / "실거래" / "indicator_combos.csv")
top = combos.sort_values("학습IC", ascending=False)
overfit = {"n": len(combos), "best_train": r3(top.iloc[0]["학습IC"]), "best_test": r3(top.iloc[0]["검증IC"]),
           "top1000_test": r3(top.head(1000)["검증IC"].mean()), "all_test": r3(combos["검증IC"].mean())}

# 현재값은 KB 쪽 로드(2026-09까지)로
v2_now = grouped(sk, Dk, "속도")
now = {"date": v2_now.index[-1].strftime("%Y-%m"), "v2": r3(v2_now.iloc[-1]), "prev3": r3(v2_now.iloc[-4]), "prev12": r3(v2_now.iloc[-13]),
       "themes": {t: r3(bt.composite(sk, Dk.index[Dk["주제"] == t]).iloc[-1]) for t in Dk["주제"].unique()},
       "speed": {v: r3(bt.composite(sk, Dk.index[Dk["속도"] == v]).iloc[-1]) for v in ["선행", "동행", "후행"]},
       "speed_n": {v: int((Dk["속도"] == v).sum()) for v in ["선행", "동행", "후행"]}}

tg = pd.read_csv(bt.ROOT / "data" / "targets_extra.csv", index_col=0, parse_dates=True)
kbp = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)["__price"]
rs = tg["실거래지수"]
idx = v2_now.index[(v2_now.index >= "2006-01-01")]
series = {"dates": [d.strftime("%Y-%m") for d in idx], "v2": [r3(v) for v in v2_now.reindex(idx)],
          "rs": [r3(v) for v in rs.reindex(idx)], "kb": [r3(v) for v in kbp.reindex(idx)],
          "fwd12": [r3(v) for v in y.reindex(idx)]}
tps = [(str(d.date())[:7], t) for d, t in bt.turning_points(rs.dropna())]

yr = lambda s: (np.log(s).resample("YE").last().diff() * 100)
quality = {
    "presale": [{"y": 2022, "kb": 26332, "ah": 9100}, {"y": 2023, "kb": 28533, "ah": 9468}, {"y": 2024, "kb": 27920, "ah": 10123},
                {"y": 2025, "kb": 36943, "ah": 4014}, {"y": 2026, "kb": 67239, "ah": 5222}],
    "reb": [{"y": int(d.year), "kb": r3(a), "reb": r3(b), "rs": r3(c)} for d, a, b, c in
            zip(yr(kbp).loc["2017":"2021"].index, yr(kbp).loc["2017":"2021"], yr(tg["부동산원지수"]).loc["2017":"2021"], yr(rs).loc["2017":"2021"])],
}
snap_dates = ["2006-11", "2008-12", "2012-12", "2015-06", "2018-09", "2020-07", "2021-09", "2022-11", "2024-05", "2025-06"]
snaps = [{"date": d, "v2": r3(v2_now.get(pd.Timestamp(d + "-01"))), "fwd12": r3(np.expm1(y.get(pd.Timestamp(d + "-01"))))} for d in snap_dates]

out = {"series": series, "tps": tps, "schemes": schemes, "variants": variants, "themes": themes, "singles": singles,
       "buckets": buckets, "overfit": overfit, "now": now, "quality": quality, "snaps": snaps,
       "n_all": int(len(meta)), "n_v2": int(len(D)), "n_trades": 1411886,
       "lag": int(bt.best_lag(v2, price)[0])}
json.dump(out, open(bt.ROOT / "results_v2" / "report_data.json", "w"), ensure_ascii=False)
print(json.dumps({k: v for k, v in out.items() if k not in ("series",)}, ensure_ascii=False)[:6000])

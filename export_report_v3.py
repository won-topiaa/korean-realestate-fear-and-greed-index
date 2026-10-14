"""v3 보고서 데이터: v2 보고서 데이터 위에 v3 지수·시점 의존성 점검·눈금 펴기 결과를 덧붙임 → results_v2/report_data_v3.json"""
import json

import numpy as np
import pandas as pd

import backtest as bt
import remedies as RM
import v3

D = json.loads((bt.ROOT / "results_v2" / "report_data.json").read_text())
r = pd.read_pickle(bt.ROOT / "results_v2" / "v3_seoul.pkl")
meta, aux_meta = v3.load_meta()
r1 = lambda v: None if v is None or pd.isna(v) else round(float(v), 1)
r3 = lambda v: None if v is None or pd.isna(v) else round(float(v), 3)
P3 = RM.P3
f = r["final"]
tg_ = pd.read_csv(bt.ROOT / "data" / "targets_extra.csv", index_col=0, parse_dates=True)
kbp_ = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)["__price"]
idx = f.dropna().index[f.dropna().index >= "2006-01-01"]
rs_ = tg_["실거래지수"].reindex(idx)
D["series"] = {"dates": [d.strftime("%Y-%m") for d in idx], "idx": [r1(f.get(d)) for d in idx],
               "rs": [r3(v) for v in rs_],
               "fwd12": [r3(v) for v in RM.Y["실거래"].reindex(idx)]}
D["tps"] = [(str(d.date())[:7], tp) for d, tp in bt.turning_points(tg_["실거래지수"].dropna())]
_meta = json.loads((bt.ROOT / "data" / "repeat_sales_meta.json").read_text()) if (bt.ROOT / "data" / "repeat_sales_meta.json").exists() else {}
D["n_trades"] = _meta.get("n_trades", D.get("n_trades"))
D["rs_base"] = _meta.get("base_month", str(rs_.last_valid_index().date())[:7])
y = RM.Y["실거래"]
fi = f.reindex(y.index)
ic = [bt.spearman(fi[bt.window_mask(fi.index, w)].to_numpy(), y[bt.window_mask(fi.index, w)].to_numpy()) for w in P3]
D["v3_ic"] = [r3(v) for v in ic]
yk = RM.Y["KB"]
D["v3_ic_kb"] = r3(np.nanmin([bt.spearman(fi[bt.window_mask(fi.index, w)].to_numpy(), yk[bt.window_mask(fi.index, w)].to_numpy()) for w in P3]))
D["lag"] = int(bt.best_lag(fi, np.exp(np.log(pd.read_csv(bt.ROOT / "data" / "targets_extra.csv", index_col=0, parse_dates=True)["실거래지수"]).reindex(fi.index)))[0])
last = f.dropna().index[-1]
D["now"] = {"date": last.strftime("%Y-%m"), "v2": r1(f.iloc[-1]), "prev3": r1(f.iloc[-4]), "prev12": r1(f.iloc[-13]),
            "themes": {k: r1(v.dropna().iloc[-1]) for k, v in r["themes"].items()},
            "speed": {k: r1(v.dropna().iloc[-1]) for k, v in r["groups"].items()},
            "speed_n": {v: int((meta["속도"] == v).sum()) for v in v3.SPEED}}
mf = bt.window_mask(fi.index, bt.FULL)
D["buckets"] = []
for lo, hi, lab in [(0, 25, "극단적 공포"), (25, 45, "공포"), (45, 55, "중립"), (55, 75, "탐욕"), (75, 101, "극단적 탐욕")]:
    sel = mf & (fi >= lo) & (fi < hi) & y.notna()
    D["buckets"].append({"label": lab, "range": f"{lo}–{min(hi, 100)}", "mean": r3(np.expm1(y[sel].mean())), "up": r3((y[sel] > 0).mean()), "n": int(sel.sum())})
for s in D["snaps"]:  # 국면 스냅샷 (고정 시점)
    t = pd.Timestamp(s["date"] + "-01")
    s["v2"] = s["idx"] = r1(f.get(t))
# 시점 의존성 진단 요약
diag = pd.read_csv(bt.ROOT / "results_v2" / "diag_time.csv", index_col=0)
D["diag"] = [{"name": i.split("_", 1)[1], "theme": row["주제"], "trend": r3(row["추세ρ"]), "shift": r3(row["전후반_평균이동σ"]),
              "pin": int(row["최장고착개월"])} for i, row in diag.sort_values(["경고", "최장고착개월"], ascending=False).head(8).iterrows()]
rem = pd.read_csv(bt.ROOT / "results_v2" / "remedies.csv", index_col=0)
keep = {"R0 v2 그대로": "v2 그대로", "B1 추세 제거 (경고 2+)": "추세 제거 (5년 평균 대비)", "W60 점수화 60개월": "점수화 기간 60개월",
        "D 주제 균등 (지표→주제→속도)": "주제별 균등 가중", "E 성과 가중 (주제별)": "성과 기반 가중치 (직전 7년 성적)",
        "A 검색량 부족 구간 제외": "검색량 부족 구간 제외", "C 고정 구성 (2009년까지 시작)": "고정 구성 (2009년까지 시작한 35개)"}
D["remedies"] = [{"name": v, "p": [r3(rem.loc[k, c]) for c in ["06–12", "13–19", "20–26"]], "min": r3(rem.loc[k, "실거래_최저"]), "kb": r3(rem.loc[k, "KB_최저"])} for k, v in keep.items()]
core = r["core"].reindex(y.index)
exp_sp = (50 + 20 * (core - core.expanding(36).mean()) / core.expanding(36).std()).clip(0, 100)
ic_core = [bt.spearman(core[bt.window_mask(core.index, w)].to_numpy(), y[bt.window_mask(core.index, w)].to_numpy()) for w in P3]
ic_exp = [bt.spearman(exp_sp[bt.window_mask(core.index, w)].to_numpy(), y[bt.window_mask(core.index, w)].to_numpy()) for w in P3]
D["remedies"].append({"name": "v3: 고정 구성 + 검색량 부족 구간 제외", "p": [r3(v) for v in ic_core], "min": r3(min(ic_core)), "kb": D["v3_ic_kb"], "v3": True})
D["spread"] = {"k": v3.K, "ic_core": [r3(v) for v in ic_core], "ic_exp": [r3(v) for v in ic_exp], "ic_fixed": D["v3_ic"],
               "rows": [{"date": d, "core": r1(r["core"].get(pd.Timestamp(d + "-01"))), "exp": r1(exp_sp.get(pd.Timestamp(d + "-01"))),
                         "fixed": r1(f.get(pd.Timestamp(d + "-01")))} for d in ["2008-12", "2012-12", "2020-07", "2022-11", "2024-05", "2026-09"]],
               "dist_core": None}
ff = f[f.index >= "2006-01-01"]
cc = r["core"][r["core"].index >= "2006-01-01"]
band = lambda x: [round(float(((x >= a) & (x < b)).mean()) * 100) for a, b in [(0, 25), (25, 45), (45, 55), (55, 75), (75, 101)]]
D["spread"]["dist_core"], D["spread"]["dist_fixed"] = band(cc), band(ff)
D["n_v3"] = int(len(meta))
D["aux"] = [{"name": c.split("_", 1)[1], "start": str(pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)[c].first_valid_index().date())[:7]} for c in aux_meta.index]
json.dump(D, open(bt.ROOT / "results_v2" / "report_data_v3.json", "w"), ensure_ascii=False)
print("v3 IC", D["v3_ic"], "KB", D["v3_ic_kb"], "lag", D["lag"], "| now", D["now"]["v2"], D["now"]["speed"])
print("spread", D["spread"]["ic_core"], D["spread"]["ic_exp"], D["spread"]["ic_fixed"], D["spread"]["dist_core"], D["spread"]["dist_fixed"])
print("buckets", D["buckets"])

# ---------- v3.1 추가: 공식 시작, 5년 이동 구간, 실효 가중치, 실시간 검증 ----------
import live_track

OFF = pd.Timestamp(v3.OFFICIAL_START)
D["version"], D["official_start"] = v3.VERSION, v3.OFFICIAL_START[:7]
VM = r["vote_meta"]
D["n_votes"] = int(len(VM))
D["n_v3"] = int(sum(len(c.split(", ")) for c in VM["구성"]))
mo = fi.index >= OFF
D["ic_official"] = r3(bt.spearman(fi[mo].to_numpy(), y[mo].to_numpy()))
# 점수 구간별 이후 12개월: 공식 기록 구간만
D["buckets"] = []
for lo, hi, lab in [(0, 25, "극단적 공포"), (25, 45, "공포"), (45, 55, "중립"), (55, 75, "탐욕"), (75, 101, "극단적 탐욕")]:
    sel = mo & (fi >= lo) & (fi < hi) & y.notna()
    D["buckets"].append({"label": lab, "range": f"{lo}–{min(hi, 100)}", "mean": r3(np.expm1(y[sel].mean())) if sel.any() else None,
                         "up": r3((y[sel] > 0).mean()) if sel.any() else None, "n": int(sel.sum())})
# 5년 이동 구간: 현재 버전 vs 단순 기준
raw_ = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
raw_ = raw_[raw_.index <= raw_["__price"].last_valid_index()]
rs_full = tg_["실거래지수"].reindex(raw_.index)
bench = {
    f"{v3.VERSION} 지수": f,
    "KB 매수우위지수 하나": bt.pct_score(raw_["설문_매수우위"]),
    "KB 3개월 가격 변화": bt.pct_score(np.log(raw_["__price"]).diff(3)),
    "실거래 6개월 가격 변화": bt.pct_score((np.log(rs_full) - np.log(rs_full).shift(6)).shift(2)),
}
starts = pd.date_range("2008-01-01", "2020-01-01", freq="12MS")
D["rolling"] = {"starts": [s.year for s in starts], "rows": []}
for name, s in bench.items():
    s = s.reindex(y.index)
    w = [bt.spearman(s[(s.index >= a) & (s.index < a + pd.DateOffset(years=5))].to_numpy(), y[(y.index >= a) & (y.index < a + pd.DateOffset(years=5))].to_numpy()) for a in starts]
    D["rolling"]["rows"].append({"name": name, "w": [r3(v) for v in w], "median": r3(np.nanmedian(w)), "min": r3(np.nanmin(w)),
                                 "full": r3(bt.spearman(s[s.index >= OFF].to_numpy(), y[y.index >= OFF].to_numpy()))})
# 실효 가중치 (최신 달)
Vl = r["votes"].iloc[-1].dropna().index
mm = VM.loc[Vl]
wt = pd.Series({c: 1 / 3 / (mm["속도"] == mm.loc[c, "속도"]).sum() for c in Vl})
D["weights"] = {"themes": {k: r3(v) for k, v in (wt.groupby(mm["주제"]).sum()).sort_values(ascending=False).items()},
                "votes": [{"name": c, "speed": mm.loc[c, "속도"], "theme": mm.loc[c, "주제"], "members": mm.loc[c, "구성"], "w": r3(wt[c])}
                          for c in wt.sort_values(ascending=False).index]}
D["live"] = live_track.evaluate()
D["now"]["speed_n"] = {s: int((VM["속도"] == s).sum()) for s in v3.SPEED}
D["spread"]["ic_core"] = [r3(v) for v in [bt.spearman(core[bt.window_mask(core.index, w)].to_numpy(), y[bt.window_mask(core.index, w)].to_numpy()) for w in P3]]
json.dump(D, open(bt.ROOT / "results_v2" / "report_data_v3.json", "w"), ensure_ascii=False)
print(v3.VERSION + ":", D["ic_official"], "| rolling", [(x["name"], x["median"], x["min"], x["full"]) for x in D["rolling"]["rows"]])
print("weights", D["weights"]["themes"], "| live", D["live"])

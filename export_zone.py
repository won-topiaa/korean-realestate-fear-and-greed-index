"""지도 페이지용 데이터 (results_zone/map_data.json) — v3. 서울·5대 권역·25개 구."""
import json

import numpy as np
import pandas as pd

import backtest as bt
import timing
import v3
from zone_fetch import ZONES

Z = pd.read_pickle(bt.ROOT / "results_zone" / "zone_v3.pkl")
zones, weight = Z["zones"], Z["weight"]
seoul = pd.read_pickle(bt.ROOT / "results_v2" / "v3_seoul.pkl")
meta, aux_meta = v3.load_meta()
P3 = [("2006-01-01", "2012-12-01"), ("2013-01-01", "2019-12-01"), ("2020-01-01", "2026-12-01")]
raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
raw = raw[raw.index <= raw["__price"].last_valid_index()]
idx = raw.index[raw.index >= "2006-01-01"]
r1 = lambda v: None if v is None or pd.isna(v) else round(float(v), 1)
r3 = lambda v: None if v is None or pd.isna(v) else round(float(v), 3)
ser = lambda s: [r1(v) for v in s.reindex(idx)]
W = weight[list(ZONES)].reindex(idx)
Wn = W.div(W.sum(axis=1), axis=0)
AUX_LABEL = {"설문_가격전망": "KB 매매가격 전망 (2013~)", "설문_부동산원매매수급": "부동산원 매매수급 (2012~)",
             "설문_국토연소비심리": "국토연 소비심리 (2011~, 서울)", "전세_가격전망": "KB 전세가격 전망 (2016~)",
             "전세_부동산원전세수급": "부동산원 전세수급 (2012~)", "거래_2030비중": "20·30대 매수 비중 (2019~)",
             "청약_1순위경쟁률": "청약 1순위 경쟁률 (2020~, 서울)", "청약_미달역수": "청약 미달이 적을수록 (2020~, 서울)",
             "청약_무순위경쟁률": "무순위 줍줍 경쟁률 (2021~, 서울)", "청약_실제공급": "실제 분양 공급 (2021~, 서울)",
             "설문_주택가격전망CSI": "한국은행 주택가격전망 CSI (2013~, 전국)"}

tg = pd.read_csv(bt.ROOT / "data" / "targets_extra.csv", index_col=0, parse_dates=True)
rs_seoul = tg["실거래지수"].reindex(idx)
y_seoul = timing.fwd(rs_seoul)  # 발표한 달부터 12개월
sf = seoul["final"].reindex(idx)
ic_seoul = [bt.spearman(sf[bt.window_mask(idx, w)].to_numpy(), y_seoul[bt.window_mask(idx, w)].to_numpy()) for w in P3]


def pack(r, rs, y, ic, ic_s, w, gus):
    return {"gus": gus, "score": ser(r["final"]), "speed": {k: ser(v) for k, v in r["groups"].items()},
            "themes": {k: ser(v) for k, v in r["themes"].items()},
            "aux": {c: ser(r["aux"][c]) for c in AUX_LABEL if r["aux"] is not None and c in r["aux"].columns},
            "rs": [r3(v) for v in rs.reindex(idx)], "fwd12": [r3(v) for v in y.reindex(idx)],
            "ic": [r3(v) for v in ic], "ic_seoul": None if ic_s is None else [r3(v) for v in ic_s], "weight": w}


regions = {z: pack(zones[z], zones[z]["rs"], zones[z]["fwd12"], zones[z]["ic"], zones[z]["ic_seoul"], r3(Wn[z].dropna().iloc[-1]), ZONES[z]) for z in ZONES}
regions["서울"] = pack(seoul, rs_seoul, y_seoul, ic_seoul, None, 1.0, [])
# 2011년 2월 이후(공식 기록) 전체 기간 정확도: 권역 지수 vs 서울 지수를 그 권역에 그대로 쓴 경우
OFF = pd.Timestamp(v3.OFFICIAL_START)
zc = pd.read_pickle(bt.ROOT / "results_zone" / "zone_calc.pkl")["zones"]
VM = seoul["vote_meta"]
for z in ZONES:
    f, yz = zones[z]["final"].reindex(idx), zones[z]["fwd12"].reindex(idx)
    m = idx >= OFF
    regions[z]["acc"] = r3(bt.spearman(f[m].to_numpy(), yz[m].to_numpy()))
    regions[z]["acc_seoul"] = r3(bt.spearman(sf[m].to_numpy(), yz[m].to_numpy()))
    zs = set(zc[z]["zone_specific"])
    regions[z]["zone_votes"] = int(sum(any(c in zs for c in comp.split(", ")) for comp in VM["구성"]))
m = idx >= OFF
regions["서울"]["acc"] = r3(bt.spearman(sf[m].to_numpy(), y_seoul[m].to_numpy()))
for z in ZONES:
    regions[z]["level"] = "zone"
regions["서울"]["level"] = "seoul"
# 25개 구: 보조 지표는 서울·권역과 같은 값이라 빼고 (파일 크기), 정확도는 구·권역·서울 지수 셋을 같은 구 실거래로 비교
gus, gw = Z["gus"], Z["gu_weight"]
GW = gw.reindex(idx)
GWn = GW.div(GW.sum(axis=1), axis=0)
gc = pd.read_pickle(bt.ROOT / "results_zone" / "zone_calc.pkl")["gus"]
gu_order = [g for z in ZONES for g in ZONES[z]]
for g in gu_order:
    r = gus[g]
    pk = pack(r, r["rs"], r["fwd12"], [], None, r3(GWn[g].dropna().iloc[-1]), [g])
    pk.pop("aux"); pk.pop("ic"); pk.pop("ic_seoul")
    pk.update({"level": "gu", "zone": r["zone"], "acc": r3(r["acc3"]["gu"]), "acc_zone": r3(r["acc3"]["zone"]),
               "acc_seoul": r3(r["acc3"]["seoul"])})
    own = set(gc[g]["zone_specific"])
    pk["own_votes"] = int(sum(any(c in own for c in comp.split(", ")) for comp in VM["구성"]))
    regions[g] = pk
# 서울 안 상대 강도 (구): 신고가 비중의 25개 구 안 순위. 공포탐욕 점수와 섞지 않는 별도 지표 (근거: gu_engine_study.py)
HI = pd.DataFrame({g: gc[g]["ind"]["거래_신고가비중"] for g in gu_order}).reindex(idx)
okm = HI.notna().sum(axis=1) >= 20
RANK = HI.rank(axis=1, ascending=False, method="min").where(okm)
PCT = (HI.rank(axis=1, pct=True) * 100).where(okm)
for g in gu_order:
    regions[g]["rel"] = {"rank": [None if pd.isna(v) else int(v) for v in RANK[g]], "pct": ser(PCT[g]),
                         "hi": [r3(v) for v in HI[g]]}
regions["서울"]["hi"] = [r3(v) for v in raw["거래_신고가비중"].reindex(idx)]


def cs_mean(Sdf):
    """달마다 25개 구 순위상관 (2011.2~, 이후 12개월 가격이 나온 달) → 평균, 양수인 해."""
    Yg = pd.DataFrame({g: gus[g]["fwd12"] for g in gu_order}).reindex(idx)
    out = {}
    for t in idx[idx >= OFF]:
        a, b = Sdf.loc[t], Yg.loc[t]
        mm = a.notna() & b.notna()
        if mm.sum() >= 20 and a[mm].nunique() > 1:
            out[t] = bt.spearman(a[mm].to_numpy(), b[mm].to_numpy())
    s = pd.Series(out)
    yr = s.groupby(s.index.year).mean()
    return {"ic": r3(s.mean()), "pos_years": int((yr > 0).sum()), "years": int(len(yr))}


gu_cs = {"score": cs_mean(pd.DataFrame({g: gus[g]["final"] for g in gu_order}).reindex(idx)), "rel": cs_mean(HI)}
geo = json.loads((bt.ROOT / "data" / "seoul_map.json").read_text())
data = {"dates": [d.strftime("%Y-%m") for d in idx], "regions": regions, "geo": geo,
        "theme_order": list(VM["주제"].unique()), "aux_label": AUX_LABEL,
        "n_ind": int(sum(len(c.split(", ")) for c in VM["구성"])), "n_votes": int(len(VM)),
        "n_zone_specific": int(zones[next(iter(ZONES))]["n_zone"]), "k": v3.K, "gu_order": gu_order,
        "gu_acc_mean": {k: r3(np.mean([gus[g]["acc3"][k] for g in gu_order])) for k in ("gu", "zone", "seoul")}, "gu_cs": gu_cs,
        "version": v3.VERSION, "official_start": v3.OFFICIAL_START[:7]}
json.dump(data, open(bt.ROOT / "results_zone" / "map_data.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("bytes", len(json.dumps(data, ensure_ascii=False, separators=(",", ":"))), "| 서울 v3 IC", np.round(ic_seoul, 2))
print({z: regions[z]["score"][-1] for z in ["서울", *ZONES]}, "| themes", data["theme_order"], "| zone-specific", data["n_zone_specific"])

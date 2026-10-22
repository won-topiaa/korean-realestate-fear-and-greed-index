"""공공판 P6: 깨끗한 공공판(P5)에 KOSIS·HOUSTAT 자료를 더함 → results_v2/public_keys.json

2026-10-21, 결과를 보기 전에 정한 규칙 (P5 = public_clean.py, 주가·구글 없음):
- 설문_거래활발   국토연 주택시장(매매+전세 합산) 소비심리 → 국토연 **주택매매시장** 소비심리지수
                  (KOSIS 390 DT_39002_04, 그 지역 값), 2개월 늦춤 (8월 값이 9월 30일에 나옴)
- 부담_구매력역수 부동산원 매매지수 × 원리금 계수 ÷ GDP → 주택금융공사 **주택구입부담지수 K-HAI**
                  (HOUSTAT T186503126543136, 분기, 그 지역 값). 분기 끝 4개월 뒤 달부터 씀
                  (2025년 4분기 값이 2026년 4월 5일 전후 공개 → 4월 20일 계산부터)
- 부담_PIR        부동산원 매매지수 ÷ GDP → 주택금융공사 **지역별 PIR** (HOUSTAT T188183126881844, 월간,
                  보금자리론·디딤돌 대출 이용자 기준). 0은 빈 값으로 본다. 6개월 늦춤
                  (10월 21일에 서울 최신 값이 4월)
- 나머지는 P5와 같다. 국토연 주택전세시장 소비심리(DT_39002_05)는 받아 두지만 넣을 자리(KB 전세가격전망은 보조)가 없어 쓰지 않는다.
판정 (P5와 같음): 서울과 지역마다 정확도(2011년 2월 이후) ≥ 0.40, 5년 구간 중앙값 ≥ 0.25면 통과.
  서울은 12개월 덩어리 부트스트랩 90% 구간과 KB판과의 차이 구간을, 지역은 2017년까지 배운 비중으로 2019년 이후 정확도를 함께 적는다.
진단 (판정에 쓰지 않음): 세 가지를 P5에 하나씩만 넣었을 때의 결과.
"""
import json

import numpy as np
import pandas as pd

import backtest as bt
import houstat_fetch as H
import kosis_fetch as K
import public_clean as PC
import public_own as PO
import public_own_region as PR
import public_validate as PVal
import public_variant as PV
import region_engine_study as S
import remedies as RM
import v3
from regions import REGIONS

FULL = {"서울": "서울특별시", "인천": "인천광역시", "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "대구": "대구광역시"}
SWAPS = ["설문_거래활발", "부담_구매력역수", "부담_PIR"]


def kosis(name, region):
    d = pd.DataFrame(K.data("390", "DT_39002_04", name))
    d = d[d["C1_NM"] == FULL[region]]
    return pd.Series(d["DT"].astype(float).to_numpy(), pd.to_datetime(d["PRD_DE"], format="%Y%m")).sort_index()


def khai(region):
    d = pd.DataFrame(H.data("T186503126543136", cycle="QY", name="khai"))
    d = d[d["ITM_NM"] == region].dropna(subset=["DTA_VAL"])
    q = d["WRTTIME_IDTFR_ID"].astype(str)
    when = pd.to_datetime(q.str[:4] + "-" + (q.str[4:].astype(int) * 3).astype(str) + "-01") + pd.DateOffset(months=4)
    return pd.Series(d["DTA_VAL"].astype(float).to_numpy(), when).sort_index()


def hf_pir(region):
    d = pd.DataFrame(H.data("T188183126881844", cycle="MM", name="pir_lir_m"))
    d = d[(d["ITM_NM"] == "PIR") & (d["CLS_NM"] == region)]
    s = pd.Series(d["DTA_VAL"].astype(float).to_numpy(), pd.to_datetime(d["WRTTIME_IDTFR_ID"], format="%Y%m")).sort_index()
    return s.replace(0, np.nan).dropna()


def new_cols(region, idx):
    return {"설문_거래활발": PR.put(kosis("국토연_매매심리", region), idx, 2),
            "부담_구매력역수": PR.put(khai(region), idx, 0),
            "부담_PIR": PR.put(hf_pir(region), idx, 6)}


def seoul_frames():
    raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
    raw = raw[raw.index <= raw["__price"].last_valid_index()]
    s = pd.read_pickle(PO.CACHE)["s"].reindex(raw.index)
    pub = PV.public_cols(raw)
    pub["설문_거래활발"] = pub["설문_거래활발"].shift(1)
    pub["가격_선도50모멘텀"] = s["lead_d3"]
    pub["가격_상승구비율"] = s["up3"]
    pub["부담_전세가율역수"] = -PC.ratio("seoul", PV.reb("reb_매매지수_서울"), PV.reb("reb_전세지수_서울"), raw.index)
    pub["전세_매매선호"] = np.nan
    p5 = raw.copy()
    p5[pub.columns] = pub
    return raw, p5, new_cols("서울", raw.index)


def seoul_eval(frame, m, aux, y):
    r = v3.compute(frame, m, aux)
    e, _ = PV.ev(r["final"], y)
    return e, r["final"]


def seoul():
    raw, p5, new = seoul_frames()
    meta, aux = v3.load_meta()
    y = RM.Y["실거래"]
    m = meta.loc[[c for c in meta.index if c != "전세_매매선호" and not c.startswith(("시장_", "관심_"))]]
    p6 = p5.copy()
    for c in SWAPS:
        p6[c] = new[c]
    out, series = {}, {}
    for n, f, mm in [("KB판", raw, meta), ("P5", p5, m), ("P6", p6, m)]:
        e, s = seoul_eval(f, mm, aux, y)
        series[n] = s
        out[n] = {"2011~": e["2011~"], "5년 중앙값": e["5년 중앙값"], "5년 최저": e["5년 최저"], "현재": e["현재"],
                  "기준 통과": bool(e["2011~"] >= 0.40 and e["5년 중앙값"] >= 0.25)}
    k = y.index >= PVal.OFF
    ci = PVal.paired_boot(series["KB판"].reindex(y.index)[k].to_numpy(), series["P6"].reindex(y.index)[k].to_numpy(), y[k].to_numpy())
    out["P6"]["90% 구간"], out["P6 차이(KB−P6) 90% 구간"] = list(ci[:, 1]), list(ci[:, 2])
    si = series["P6"].reindex(y.index)
    part = lambda a, b: bt.spearman(si[(si.index >= a) & (si.index < b)].to_numpy(), y[(y.index >= a) & (y.index < b)].to_numpy())
    out["P6"]["2011~2018"], out["P6"]["2019~"] = part(PVal.OFF, PVal.SPLIT), part(PVal.SPLIT, pd.Timestamp("2100-01-01"))
    diag = {}
    for c in SWAPS:  # 진단: 하나씩만
        f = p5.copy()
        f[c] = new[c]
        e, _ = seoul_eval(f, m, aux, y)
        diag[c] = {"2011~": e["2011~"], "5년 중앙값": e["5년 중앙값"]}
    sc = v3.scores(pd.DataFrame({c: new[c] for c in SWAPS}))
    old = v3.scores(p5[SWAPS])
    kbs = v3.scores(raw[SWAPS])
    yy = y[y.index >= PVal.OFF]
    one = {c: {"KB": bt.spearman(kbs[c].reindex(yy.index).to_numpy(), yy.to_numpy()),
               "P5": bt.spearman(old[c].reindex(yy.index).to_numpy(), yy.to_numpy()),
               "P6": bt.spearman(sc[c].reindex(yy.index).to_numpy(), yy.to_numpy())} for c in SWAPS}
    return out, diag, one


def regions():
    base = next(c for c in S.CONFIGS if c["name"] == "자료로 비중 · 120개월")
    cfg = dict(base, drop=["금융시장", "관심"])
    rids = list(S.DATA)
    kb_data = S.DATA
    lead = pd.read_pickle(PO.CACHE)["s"]["lead_d3"]
    rts = pd.read_pickle(PC.TMP)
    p5, p6, one = {}, {}, {c: {} for c in SWAPS}
    for rid in rids:
        ind = kb_data[rid]["ind"]
        o = PR.public_region(rid, ind, rts[rid], lead)
        o["설문_거래활발"] = o["설문_거래활발"].shift(1)
        o["부담_전세가율역수"] = -PC.ratio(rid, PR.reb(f"r_{rid}_매매지수"), PR.reb(f"r_{rid}_전세지수"), ind.index)
        new = new_cols(REGIONS[rid]["name"], ind.index)
        o6 = o.copy()
        for c in SWAPS:
            o6[c] = new[c]
            oc = o.copy()
            oc[c] = new[c]
            one[c][rid] = {"ind": oc, "fwd12": kb_data[rid]["fwd12"]}
        p5[rid] = {"ind": o, "fwd12": kb_data[rid]["fwd12"]}
        p6[rid] = {"ind": o6, "fwd12": kb_data[rid]["fwd12"]}
    out, diag = {}, {}
    train_end = PVal.SPLIT - pd.DateOffset(months=12)
    for tag, data in [("P5", p5), ("P6", p6)]:
        S.DATA, S.CACHE = data, {}
        for h in rids:
            f = S.run(cfg, h, rids)
            late = S.run(cfg, h, rids, a=PVal.SPLIT, b=None, wb=train_end)
            out.setdefault(REGIONS[h]["name"], {})[tag] = {"정확도": f["acc"], "5년 중앙값": f["win_median"], "5년 최저": f["win_min"],
                                                          "기간 검증 2019~": late["acc"],
                                                          "기준 통과": bool(f["acc"] >= 0.40 and f["win_median"] >= 0.25)}
    for c in SWAPS:
        S.DATA, S.CACHE = one[c], {}
        diag[c] = {REGIONS[h]["name"]: S.run(cfg, h, rids)["acc"] for h in rids}
    S.DATA, S.CACHE = kb_data, {}
    return out, diag


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    sr, sdiag, one = seoul()
    print(json.dumps(sr, ensure_ascii=False, indent=1, default=lambda x: round(float(x), 3)))
    print("\n서울 지표 하나씩 (2011~ 순위상관):\n", pd.DataFrame(one).T.round(3).to_string())
    print("\n서울 진단 (P5에 하나씩만):\n", pd.DataFrame(sdiag).T.round(3).to_string(), flush=True)
    rr, rdiag = regions()
    rows = {f"{r} {t}": v for r, d in rr.items() for t, v in d.items()}
    print("\n", pd.DataFrame(rows).T.round(3).to_string())
    print("\n지역 진단 (P5에 하나씩만, 정확도):\n", pd.DataFrame(rdiag).T.round(3).to_string())
    res = {"rule": "public_keys.py docstring", "서울": sr, "서울 진단": sdiag, "서울 지표": one, "지역": rr, "지역 진단": rdiag}
    (bt.ROOT / "results_v2" / "public_keys.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))

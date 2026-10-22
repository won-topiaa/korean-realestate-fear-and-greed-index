"""수도권·광역시: KB 없이 공개 자료로 직접 만든 지표 시험 → results_region/public_own.json

2026-10-21, 결과를 보기 전에 정한 규칙 (서울 public_own.py와 같은 정의를 지역 자료로):
  가격_3개월모멘텀     그 지역 실거래 반복매매지수(그 달 20일에 알 수 있던 거래만으로 다시 추정) 3개월 로그 변화
  가격_12개월이평괴리  같은 지수의 마지막 값 / 마지막 12개 평균 − 1
  가격_상승구비율      시군구마다 같은 방식으로 추정한 지수에서 마지막 달에 오른 시군구 비율, 3개월 평균 (절반 이상 추정될 때만)
  가격_선도50모멘텀    서울 자체 선도50 (전국 공통 값 자리, public_own.py)
  설문_매수우위        부동산원 그 지역 매매수급지수 (이미 지역 지표에 있음)
  설문_매수우위변화    같은 지수 3개월 변화
  설문_거래활발        국토연 그 지역 주택시장 소비심리지수 (부동산원 R-ONE, 1개월 늦춤)
  전세_수급            부동산원 그 지역 전세수급지수
  전세_3개월모멘텀     부동산원 그 지역 아파트 전세가격지수 3개월 로그 변화 (1개월 늦춤)
  부담_PIR             부동산원 그 지역 매매지수 / 최근 4분기 명목 GDP
  부담_구매력역수      부동산원 그 지역 매매지수 × 30년 원리금 상환계수(주담대 금리) / 명목 GDP
  부담_전세가율역수    −(부동산원 그 지역 전세지수 / 매매지수) (1개월 늦춤)
  설문_가격전망·전세_가격전망(보조)·전세_매매선호   비움
엔진: 지금 임시 엔진과 같은 '자료로 비중 · 120개월' (평가하는 지역을 빼고 배운 비중). KB판과 공공판을 같은 방식으로 잰다.
판정: 지역마다 정확도(2011년 2월 이후) ≥ 0.40, 5년 구간 중앙값 ≥ 0.25 → 그 지역 공공판을 인덱서고에 낼 수 있음.
"""
import json
import time

import numpy as np
import pandas as pd

import backtest as bt
import molit_indicators as MI
import public_own as PO
import region_engine_study as S
import region_store
from build_indicators import ecos
from regions import REGIONS

M = pd.DateOffset(months=1)
RAW = bt.ROOT / "data" / "raw" / "reb"


def reb(name):
    d = pd.DataFrame(json.loads((RAW / f"{name}.json").read_text()))
    d["date"] = pd.to_datetime(d["WRTTIME_IDTFR_ID"], format="%Y%m")
    return d.groupby("date")["DTA_VAL"].sum().astype(float)


def put(s, idx, lag):
    s = s.reindex(s.index.union(idx)).sort_index().ffill(limit=3).shift(lag)
    return s.reindex(idx)


def rt_series(rid, months):
    tr = MI.load(df=region_store.load(rid))
    lawds = list(REGIONS[rid]["lawd"])
    by = {l: tr[tr["lawd"] == l] for l in lawds}
    rows = {}
    for t in months:
        c = t - 2 * M
        r = {}
        lv = PO.lv_at(tr, c)
        if lv is not None and c in lv.index and c - 12 * M in lv.index:
            r["d3"] = lv[c] - lv[c - 3 * M]
            r["gap12"] = np.exp(lv[c]) / np.exp(lv[lv.index > c - 12 * M]).mean() - 1
        ups = []
        for l in lawds:
            if len(by[l]) < 200:
                continue
            lg = PO.lv_at(by[l], c)
            if lg is not None and c in lg.index and c - M in lg.index:  # 그 달 거래가 없는 시군구는 빼고 센다
                ups.append(float(lg[c] > lg[c - M]))
        r["up1"] = np.mean(ups) if len(ups) >= max(2, len(lawds) / 2) else np.nan
        rows[t] = r
    s = pd.DataFrame(rows).T
    s["up3"] = s["up1"].rolling(3).mean()
    return s


def public_region(rid, ind, rt, lead):
    idx = ind.index
    out = ind.copy()
    p, j = reb(f"r_{rid}_매매지수"), reb(f"r_{rid}_전세지수")
    gdp = ecos("명목GDP").rolling(4).sum().resample("MS").ffill()
    gdp.index = gdp.index + pd.DateOffset(months=5)
    gdp = gdp.reindex(gdp.index.union(idx)).ffill(limit=5).reindex(idx)
    r = ecos("주담대금리") / 100 / 12
    af = put(r / (1 - (1 + r) ** -360), idx, 2)
    p1 = put(p, idx, 1)
    rt = rt.reindex(idx)
    out["가격_3개월모멘텀"] = rt["d3"]
    out["가격_12개월이평괴리"] = rt["gap12"]
    out["가격_상승구비율"] = rt["up3"]
    out["가격_선도50모멘텀"] = lead.reindex(idx)
    out["설문_매수우위"] = ind["설문_부동산원매매수급"]
    out["설문_매수우위변화"] = ind["설문_부동산원매매수급"].diff(3)
    out["설문_거래활발"] = put(reb(f"r_{rid}_주택심리"), idx, 1)
    out["전세_수급"] = ind["전세_부동산원전세수급"]
    out["전세_3개월모멘텀"] = put(np.log(j).diff(3), idx, 1)
    out["부담_PIR"] = np.log(p1) - np.log(gdp)
    out["부담_구매력역수"] = np.log(p1) + np.log(af) - np.log(gdp)
    out["부담_전세가율역수"] = -put(j / p, idx, 1)
    for c in ("설문_가격전망", "전세_가격전망", "전세_매매선호"):
        if c in out:
            out[c] = np.nan
    return out


if __name__ == "__main__":
    lead = pd.read_pickle(PO.CACHE)["s"]["lead_d3"]
    regions = list(S.DATA)
    cfg = next(c for c in S.CONFIGS if c["name"] == "자료로 비중 · 120개월")
    kb = {h: S.run(cfg, h, regions) for h in regions}
    pub_data = {}
    for rid in regions:
        t0 = time.time()
        ind = S.DATA[rid]["ind"]
        months = ind.index[ind.index >= "2007-01-01"]
        rt = rt_series(rid, months)
        pub_data[rid] = {"ind": public_region(rid, ind, rt, lead), "fwd12": S.DATA[rid]["fwd12"]}
        print(f"  {rid} 공공 지표 {time.time() - t0:.0f}s", flush=True)
    S.DATA, S.CACHE = pub_data, {}
    pub = {h: S.run(cfg, h, regions) for h in regions}
    rows = []
    for h in regions:
        a, b = kb[h], pub[h]
        ok = b["acc"] >= 0.40 and b["win_median"] >= 0.25
        rows.append({"지역": REGIONS[h]["name"], "KB 정확도": a["acc"], "KB 5년 중앙": a["win_median"], "공공 정확도": b["acc"],
                     "공공 5년 중앙": b["win_median"], "공공 5년 최저": b["win_min"], "공공 2019~": b["recent"], "공공판 기준 통과": ok})
    df = pd.DataFrame(rows).set_index("지역")
    pd.set_option("display.width", 220)
    print(df.round(3).to_string())
    w = S.ic_weights(regions, 120)
    tot = sum(w.values())
    print("\n공공판 표 비중 (모든 지역으로 배움):", ", ".join(f"{k} {v / tot:.3f}" for k, v in sorted(w.items(), key=lambda x: -x[1]) if v > 0))
    (bt.ROOT / "results_region" / "public_own.json").write_text(json.dumps(
        {"rule": "public_own_region.py docstring", "kb": kb, "public": pub}, ensure_ascii=False, indent=1, default=float))

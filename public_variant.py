"""공공데이터만 쓰는 버전 시험: KB 자료를 빼고 같은 개념의 공공 자료로 바꿨을 때 정확도가 얼마나 달라지나.

결과를 보기 전에 정한 대체 규칙 (지표 이름은 그대로 두어 주제·속도·표 묶기가 v3.2와 같게):
  가격_3개월모멘텀      KB 매매지수        → 부동산원 아파트 매매가격지수 3개월 변화 (1개월 늦춤)
  가격_12개월이평괴리   KB 매매지수        → 부동산원 매매가격지수 / 12개월 평균 - 1 (1개월 늦춤)
  가격_선도50모멘텀     KB 선도아파트50    → 국토부 실거래 반복매매지수 3개월 변화 (2개월 늦춤)
  가격_상승구비율       KB 구별 지수       → 없음 (원래 3개월모멘텀과 한 표)
  설문_매수우위         KB 중개사 설문     → 부동산원 매매수급지수 (2012.7~)
  설문_매수우위변화     KB                 → 부동산원 매매수급지수 3개월 변화
  설문_거래활발         KB                 → 국토연 부동산 소비심리지수 (2011.7~)
  전세_수급             KB                 → 부동산원 전세수급지수 (2012.7~)
  전세_3개월모멘텀      KB 전세지수        → 부동산원 아파트 전세가격지수 3개월 변화 (1개월 늦춤)
  부담_PIR              KB PIR             → 부동산원 매매지수 / 최근 4분기 명목 GDP (한국은행)
  부담_구매력역수       KB 주택구매력지수  → 부동산원 매매지수 × 주담대 원리금 계수(30년) / 명목 GDP
  부담_전세가율역수     KB 전세가율        → -(부동산원 전세지수 / 매매지수) (1개월 늦춤)
비교 후보: P0 KB만 빼기, P1 공공 대체(+구글·주가), P2 P1에서 주가(네이버) 빼기, P3 P2에서 구글도 빼기.
"""
import json

import numpy as np
import pandas as pd

import backtest as bt
import remedies as RM
import v3
from build_indicators import ecos

RAW = bt.ROOT / "data" / "raw"
KB_COLS = ["가격_3개월모멘텀", "가격_12개월이평괴리", "가격_선도50모멘텀", "가격_상승구비율", "설문_매수우위", "설문_매수우위변화",
           "설문_거래활발", "전세_수급", "전세_3개월모멘텀", "전세_매매선호", "부담_PIR", "부담_구매력역수", "부담_전세가율역수"]


def reb(name):
    d = pd.DataFrame(json.loads((RAW / "reb" / f"{name}.json").read_text()))
    d["date"] = pd.to_datetime(d["WRTTIME_IDTFR_ID"], format="%Y%m")
    return d.groupby("date")["DTA_VAL"].sum().astype(float)


def public_cols(raw):
    idx = raw.index

    def put(s, lag):  # 파이프라인과 같은 순서: 최대 3개월 이어 쓰기 → 공개 시차만큼 늦춤
        s = s.reindex(s.index.union(idx)).sort_index().ffill(limit=3).shift(lag)
        return s.reindex(idx)

    p, j = reb("reb_매매지수_서울"), reb("reb_전세지수_서울")
    rs = pd.read_csv(bt.ROOT / "data" / "targets_extra.csv", index_col=0, parse_dates=True)["실거래지수"]
    gdp = ecos("명목GDP").rolling(4).sum().resample("MS").ffill()
    gdp.index = gdp.index + pd.DateOffset(months=5)  # 분기 끝 3개월 뒤 공개 (가계신용과 같은 규칙)
    gdp = gdp.reindex(gdp.index.union(idx)).ffill(limit=5).reindex(idx)
    r = ecos("주담대금리") / 100 / 12
    af = put(r / (1 - (1 + r) ** -360), 2)  # 30년 원리금균등 상환 계수, 금리는 2개월 늦춤
    p1 = put(p, 1)
    out = pd.DataFrame(index=idx)
    out["가격_3개월모멘텀"] = put(np.log(p).diff(3), 1)
    out["가격_12개월이평괴리"] = put(p / p.rolling(12).mean() - 1, 1)
    out["가격_선도50모멘텀"] = put(np.log(rs).diff(3), 2)
    out["설문_매수우위"] = raw["설문_부동산원매매수급"]  # 이미 1개월 늦춘 값
    out["설문_매수우위변화"] = raw["설문_부동산원매매수급"].diff(3)
    out["설문_거래활발"] = raw["설문_국토연소비심리"]
    out["전세_수급"] = raw["전세_부동산원전세수급"]
    out["전세_3개월모멘텀"] = put(np.log(j).diff(3), 1)
    out["부담_PIR"] = np.log(p1) - np.log(gdp)
    out["부담_구매력역수"] = np.log(p1) + np.log(af) - np.log(gdp)
    out["부담_전세가율역수"] = -put(j / p, 1)
    return out


starts = pd.date_range("2008-01-01", "2020-01-01", freq="12MS")


def ev(s, y):
    si = s.reindex(y.index)
    w = np.array([bt.spearman(si[(si.index >= a) & (si.index < a + pd.DateOffset(years=5))].to_numpy(),
                              y[(y.index >= a) & (y.index < a + pd.DateOffset(years=5))].to_numpy()) for a in starts])
    full = lambda a: bt.spearman(si[si.index >= a].to_numpy(), y[y.index >= a].to_numpy())
    kb = min(bt.spearman(si[bt.window_mask(si.index, a)].to_numpy(), RM.Y["KB"][bt.window_mask(si.index, a)].to_numpy()) for a in RM.P3)
    return {"5년 중앙값": np.nanmedian(w), "5년 최저": np.nanmin(w), "0.3 미만": int((w < 0.3).sum()),
            "2011~": full("2011-02-01"), "2014.7~": full("2014-07-01"), "KB기준 최저": kb, "현재": s.dropna().iloc[-1]}, w


if __name__ == "__main__":
    raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
    raw = raw[raw.index <= raw["__price"].last_valid_index()]
    meta, aux_meta = v3.load_meta()
    y = RM.Y["실거래"]
    pub = public_cols(raw)
    market = [c for c in meta.index if c.startswith("시장_")]
    google = [c for c in meta.index if c.startswith("관심_")]
    nokb = meta.loc[[c for c in meta.index if c not in KB_COLS]]
    pub_meta = meta.loc[[c for c in meta.index if c not in ("가격_상승구비율", "전세_매매선호")]]
    raw_pub = raw.copy()
    raw_pub[pub.columns] = pub
    cands = {
        "v3.2 (지금, KB 포함)": (raw, meta),
        "P0 KB만 빼기": (raw, nokb),
        "P1 공공 대체 + 구글·주가": (raw_pub, pub_meta),
        "P2 공공 대체 + 구글": (raw_pub, pub_meta.drop(market)),
        "P3 공공 대체만 (정부·한은)": (raw_pub, pub_meta.drop(market + google)),
    }
    rows, wins, res = {}, {}, {}
    for n, (rw, m) in cands.items():
        r = v3.compute(rw, m, aux_meta)
        rows[n], wins[n] = ev(r["final"], y)
        nv = r["n_votes_available"]
        rows[n]["표 수 (2008·2011·2014·최신)"] = "/".join(str(int(nv.get(pd.Timestamp(d), 0))) for d in ["2008-01-01", "2011-02-01", "2014-07-01"]) + f"/{int(nv.iloc[-1])}"
        res[n] = r
    df = pd.DataFrame(rows).T
    pd.set_option("display.width", 220)
    print(df.round(3).to_string())
    print("\n5년 구간별 (시작 연도)")
    print(pd.DataFrame(wins, index=[s.year for s in starts]).T.round(2).to_string())
    print("\n대체 지표 하나씩: 2011~ 순위상관 (지표 점수 기준, KB 원래 → 공공 대체)")
    sc_kb, sc_pub = v3.scores(raw[list(pub.columns)]), v3.scores(pub)
    for c in pub.columns:
        a = sc_kb[c].reindex(y.index) if c in sc_kb else None
        b = sc_pub[c].reindex(y.index)
        m = y.index >= "2011-02-01"
        print(f"  {c:12s} {bt.spearman(a[m].to_numpy(), y[m].to_numpy()):+.2f} → {bt.spearman(b[m].to_numpy(), y[m].to_numpy()):+.2f}"
              f"  · 두 지표 상관 {a[m].corr(b[m]):.2f}")
    tf = {n: {k: round(float(v.dropna().iloc[-1]), 1) for k, v in r["themes"].items()} for n, r in res.items()}
    print("\n최신 달 주제별 점수\n", pd.DataFrame(tf).round(1).to_string())
    pd.to_pickle({"table": df, "windows": wins, "series": {n: r["final"] for n, r in res.items()}}, bt.ROOT / "results_v2" / "public_variant.pkl")

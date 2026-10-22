"""KB 없이 공개 자료로 직접 만든 지표 시험 (P4) → results_v2/public_own.pkl

2026-10-21, 결과를 보기 전에 정한 규칙:
KB 지표 12개(+ 표에서 빠지는 전세_매매선호)를 아래 공개 자료 지표로 바꾸고, 엔진 v3.3 구조(점수화·표 묶기·속도 3그룹)는 그대로 둔다.
지표 이름은 그대로 둬서 주제·속도·표 묶기가 같다. KB 값에 맞추는 조정은 하지 않는다 (정의는 아래에서 미리 고정).
실거래로 만드는 지표는 달마다 '그 달 20일에 알 수 있던 거래'(계약 2개월 전 달까지)만으로 지수를 다시 추정해 잰다 (rs_vintage.py와 같은 방식).
  가격_3개월모멘텀     서울 실거래 반복매매지수 3개월 로그 변화
  가격_12개월이평괴리  같은 지수의 마지막 값 / 마지막 12개 평균 − 1
  가격_상승구비율      25개 구 각각의 실거래 지수에서 마지막 달에 오른 구 비율, 3개월 평균 (3개월모멘텀과 한 표)
  가격_선도50모멘텀    해마다 시가총액(세대수 × 직전 12개월 거래가 중위값, 전년 10월까지 계약) 상위 50단지의 실거래 지수 3개월 로그 변화
                      (세대수·사용승인일은 건축물대장, 그 해 1월 전에 사용승인된 단지만)
  설문_매수우위        부동산원 매매수급지수 (P1과 같음)
  설문_매수우위변화    부동산원 매매수급지수 3개월 변화 (P1과 같음)
  설문_거래활발        국토연 부동산 소비심리지수 (P1과 같음)
  전세_수급            부동산원 전세수급지수 (P1과 같음)
  전세_3개월모멘텀     부동산원 아파트 전세가격지수 3개월 로그 변화, 1개월 늦춤 (P1과 같음)
  부담_PIR             부동산원 매매지수 / 최근 4분기 명목 GDP (P1과 같음. 실거래 지수는 추정할 때마다 기준이 달라 수준 비교가 안 됨)
  부담_구매력역수      부동산원 매매지수 × 30년 원리금 상환계수(주담대 금리) / 명목 GDP (P1과 같음)
  부담_전세가율역수    −(부동산원 전세지수 / 매매지수) (P1과 같음)
비교: 지금(KB 포함) · P1(10-14 공공 대체) · P4 · P4에서 주가 빼기 · P4에서 주가·구글 빼기.
판정: 2011년 2월 이후 순위상관 ≥ 0.40이고 5년 구간 중앙값 ≥ 0.25인 공공판(P1·P4 계열) 중 두 값 평균이 가장 높은 것을
인덱서고용 공공판으로 한다. 사이트 엔진을 바꿀지는 KB판과의 차이를 보고 사용자가 정한다.
"""
import time

import numpy as np
import pandas as pd

import backtest as bt
import molit_indicators as MI
import public_variant as PV
import remedies as RM
import v3

CACHE = bt.ROOT / "results_v2" / "public_own_series.pkl"
M = pd.DateOffset(months=1)


def lv_at(tr, c):
    """계약 c달까지의 거래로 추정한 로그 지수 (c가 마지막 달)."""
    sub = tr[tr["date"] <= c]
    if sub["date"].nunique() < 15:
        return None
    v, _ = MI.repeat_sales(sub)
    return np.log(v)


def leaders(tr, bld, year):
    """year년에 쓸 시가총액 상위 50단지 (전년 10월까지 12개월 계약, 그 해 1월 전 사용승인)."""
    a, b = pd.Timestamp(year - 1, 11, 1) - pd.DateOffset(months=12), pd.Timestamp(year - 1, 10, 1)
    med = tr[(tr["date"] >= a) & (tr["date"] <= b)].groupby("aptSeq")["price"].median()
    ok = bld[(bld["useApr"] < f"{year}0101")]
    cap = (ok["hhld"] * med.reindex(ok.index)).dropna()
    return set(cap.nlargest(50).index)


def build_series(months):
    tr = MI.load()
    bld = pd.read_csv(bt.ROOT / "data" / "molit" / "buildings.csv", dtype=str)
    bld = bld[bld["status"] == "ok"].set_index("aptSeq")
    bld["hhld"] = pd.to_numeric(bld["hhld"], errors="coerce")
    bld = bld[(bld["hhld"] > 0) & bld["useApr"].notna()]
    gus = sorted(tr["gu"].unique())
    by_gu = {g: tr[tr["gu"] == g] for g in gus}
    sets = {}
    rows = {}
    t0 = time.time()
    for k, t in enumerate(months):
        c = t - 2 * M
        r = {}
        lv = lv_at(tr, c)
        if lv is not None and c - 12 * M in lv.index:
            r["d3"] = lv[c] - lv[c - 3 * M]
            r["gap12"] = np.exp(lv[c]) / np.exp(lv[lv.index > c - 12 * M]).mean() - 1
        ups = []
        for g in gus:
            lg = lv_at(by_gu[g], c)
            if lg is not None and c - M in lg.index:
                ups.append(float(lg[c] > lg[c - M]))
        r["up1"] = np.mean(ups) if len(ups) >= 20 else np.nan
        if t.year not in sets:
            sets[t.year] = leaders(tr, bld, t.year)
        ll = lv_at(tr[tr["aptSeq"].isin(sets[t.year])], c)
        if ll is not None and c - 3 * M in ll.index:
            r["lead_d3"] = ll[c] - ll[c - 3 * M]
        rows[t] = r
        if k % 24 == 0:
            print(f"  {t.date()} ({k + 1}/{len(months)}, {time.time() - t0:.0f}s)", flush=True)
    s = pd.DataFrame(rows).T
    s["up3"] = s["up1"].rolling(3).mean()
    return s, sets


def own_cols(raw, s):
    out = PV.public_cols(raw)  # P1 정의 (부동산원·국토연·GDP)
    s = s.reindex(raw.index)
    out["가격_3개월모멘텀"] = s["d3"]
    out["가격_12개월이평괴리"] = s["gap12"]
    out["가격_상승구비율"] = s["up3"]
    out["가격_선도50모멘텀"] = s["lead_d3"]
    out["전세_매매선호"] = np.nan
    return out


if __name__ == "__main__":
    raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
    raw = raw[raw.index <= raw["__price"].last_valid_index()]
    months = raw.index[raw.index >= "2007-01-01"]
    if CACHE.exists() and pd.read_pickle(CACHE)["s"].index.max() >= months.max():
        s, sets = pd.read_pickle(CACHE)["s"], pd.read_pickle(CACHE)["sets"]
    else:
        print("그때 알 수 있던 실거래 지수로 가격 지표 만들기", flush=True)
        s, sets = build_series(months)
        pd.to_pickle({"s": s, "sets": sets}, CACHE)
    meta, aux_meta = v3.load_meta()
    y = RM.Y["실거래"]
    market = [c for c in meta.index if c.startswith("시장_")]
    google = [c for c in meta.index if c.startswith("관심_")]
    p1, p4 = raw.copy(), raw.copy()
    pub = PV.public_cols(raw)
    p1[pub.columns] = pub
    own = own_cols(raw, s)
    p4[own.columns] = own
    p1_meta = meta.loc[[c for c in meta.index if c not in ("가격_상승구비율", "전세_매매선호")]]
    cands = {
        "지금 (KB 포함)": (raw, meta),
        "P1 공공 대체 (10-14)": (p1, p1_meta),
        "P4 자체 지표": (p4, meta),
        "P4 - 주가": (p4, meta.drop(market)),
        "P4 - 주가·구글": (p4, meta.drop(market + google)),
    }
    rows, wins, res = {}, {}, {}
    for n, (rw, m) in cands.items():
        r = v3.compute(rw, m, aux_meta)
        rows[n], wins[n] = PV.ev(r["final"], y)
        nv = r["n_votes_available"]
        rows[n]["표 수 (2008·2011·2014·최신)"] = "/".join(str(int(nv.get(pd.Timestamp(d), 0))) for d in ["2008-01-01", "2011-02-01", "2014-07-01"]) + f"/{int(nv.iloc[-1])}"
        res[n] = r
    df = pd.DataFrame(rows).T
    pub_ok = df[(df.index != "지금 (KB 포함)") & (df["2011~"] >= 0.40) & (df["5년 중앙값"] >= 0.25)]
    pick = (pub_ok["2011~"] + pub_ok["5년 중앙값"]).idxmax() if len(pub_ok) else None
    pd.set_option("display.width", 220)
    print(df.drop(columns=["KB기준 최저"]).round(3).to_string())
    print("\n판정: 공공판 →", pick or "기준을 넘는 공공판 없음")
    print("\n5년 구간별 (시작 연도)")
    print(pd.DataFrame(wins, index=[d.year for d in PV.starts]).T.round(2).to_string())
    print("\n바꾼 지표 하나씩: 2011~ 순위상관 (KB → P4)")
    m11 = y.index >= "2011-02-01"
    sc_kb, sc_own = v3.scores(raw[list(own.columns)]), v3.scores(own)
    for c in own.columns:
        if c == "전세_매매선호":
            continue
        a, b = sc_kb[c].reindex(y.index), sc_own[c].reindex(y.index)
        print(f"  {c:12s} {bt.spearman(a[m11].to_numpy(), y[m11].to_numpy()):+.2f} → {bt.spearman(b[m11].to_numpy(), y[m11].to_numpy()):+.2f}"
              f"  · 두 지표 상관 {a[m11].corr(b[m11]):.2f}")
    print("\n선도50 자체 선정 예 (2026):", ", ".join(sorted(sets.get(2026, []))[:8]), "…")
    pd.to_pickle({"table": df, "windows": wins, "pick": pick, "series": {n: r["final"] for n, r in res.items()}},
                 bt.ROOT / "results_v2" / "public_own.pkl")

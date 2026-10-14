"""시점 의존성 해결책 비교 (정답: 실거래 반복매매지수, 비교: KB).

R0  v2 그대로
A   검색량 부족 구간 제외: 직전 24개월 평균 검색량이 5 미만이면 그 달 검색 지표는 '없음'
B1  추세 제거(강): 경고 2개 이상 지표는 '5년 평균 대비 편차'로 바꾼 뒤 점수화
B2  추세 제거(넓게): 경고 1개 이상 지표 전부
C   고정 구성: 2009년까지 시작한 지표만 사용 (시대마다 구성이 같도록)
D   주제 균등: 지표 → 주제 → 속도 그룹 순으로 평균 (지표가 많은 주제가 그룹을 장악하지 않도록)
E   성과 가중: 주제별 가중치를 직전 7년 성적(12개월 뒤에야 알 수 있는 정보만)으로 정하고 동일가중과 반반 섞음
W60 점수화 기간 60개월
"""
import numpy as np
import pandas as pd

import backtest as bt

NOT_REALTIME = ("공급_분양물량", "공급_향후입주역수")
P3 = [("2006-01-01", "2012-12-01"), ("2013-01-01", "2019-12-01"), ("2020-01-01", "2026-12-01")]
SPEED = ["선행", "동행", "후행"]

raw0 = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
raw0 = raw0[raw0.index <= raw0["__price"].last_valid_index()]
kbp = raw0["__price"]
meta = pd.read_csv(bt.ROOT / "data" / "indicator_meta.csv", index_col=0).fillna("")
meta = meta.loc[[c for c in meta.index if c not in NOT_REALTIME]]
raw0 = raw0[meta.index]
diag = pd.read_csv(bt.ROOT / "results_v2" / "diag_time.csv", index_col=0)
tg = pd.read_csv(bt.ROOT / "data" / "targets_extra.csv", index_col=0, parse_dates=True)
rs = tg["실거래지수"].reindex(raw0.index)
Y = {"실거래": np.log(rs).shift(-12) - np.log(rs), "KB": np.log(kbp).shift(-12) - np.log(kbp)}

TREND_KW = {"관심_아파트": ["아파트"], "관심_부동산": ["부동산"], "관심_집값": ["집값"], "관심_청약": ["청약"],
            "관심_갭투자": ["갭투자"], "관심_공포어역수": ["급매", "미분양"]}


def search_mask():
    m = pd.DataFrame(True, index=raw0.index, columns=list(TREND_KW))
    for c, kws in TREND_KW.items():
        vol = sum(pd.read_csv(bt.ROOT / "data" / "raw" / "trends" / f"{k}.csv", index_col=0, parse_dates=True).iloc[:, 0] for k in kws)
        ok = vol.rolling(24).mean() >= 5
        m[c] = ok.reindex(raw0.index).fillna(False)
    return m


def prepare(search=False, detrend=None, fixed=False, window=120):
    raw = raw0.copy()
    if search:
        raw[list(TREND_KW)] = raw[list(TREND_KW)].where(search_mask())
    if detrend is not None:
        for c in detrend:
            raw[c] = raw[c] - raw[c].rolling(60, min_periods=36).mean()
    cols = list(meta.index)
    if fixed:
        cols = [c for c in cols if pd.Timestamp(diag.loc[c, "시작"] + "-01") <= pd.Timestamp("2009-12-01")] if True else cols
    bt.WINDOW = window
    sc = raw[cols].apply(bt.pct_score)
    bt.WINDOW = 120
    return sc, meta.loc[cols]


def flat_speed(sc, me):
    return pd.concat([bt.composite(sc, me.index[me["속도"] == v]) for v in SPEED], axis=1).mean(axis=1)


def theme_within_speed(sc, me):
    groups = []
    for v in SPEED:
        sub = me[me["속도"] == v]
        groups.append(pd.concat([bt.composite(sc, sub.index[sub["주제"] == t]) for t in sub["주제"].unique()], axis=1).mean(axis=1))
    return pd.concat(groups, axis=1).mean(axis=1)


def adaptive(sc, me, y, lookback=84, gap=12, shrink=0.5):
    themes = {t: bt.composite(sc, me.index[me["주제"] == t]) for t in me["주제"].unique()}
    T = pd.DataFrame(themes)
    out = pd.Series(np.nan, index=T.index)
    for i, d in enumerate(T.index):
        avail = T.loc[d].dropna()
        if avail.empty:
            continue
        w_eq = pd.Series(1 / len(avail), index=avail.index)
        lo, hi = max(0, i - gap - lookback), i - gap  # 12개월 뒤에야 결과를 아는 구간만
        w = w_eq
        if hi - lo >= 36:
            ics = {}
            for t in avail.index:
                x, yy = T[t].iloc[lo:hi].to_numpy(), y.iloc[lo:hi].to_numpy()
                ics[t] = bt.spearman(x, yy)
            ic = pd.Series(ics).fillna(0).clip(lower=0)
            if ic.sum() > 0:
                w = shrink * w_eq + (1 - shrink) * ic / ic.sum()
        out[d] = (avail * w).sum() / w.sum()
    return out


def evaluate(name, s):
    r = {"방식": name}
    for tn, y in Y.items():
        ics = [bt.spearman(s[bt.window_mask(s.index, w)].to_numpy(), y[bt.window_mask(s.index, w)].to_numpy()) for w in P3]
        if tn == "실거래":
            r.update({"06–12": ics[0], "13–19": ics[1], "20–26": ics[2]})
        r[f"{tn}_최저"] = np.nanmin(ics)
    for (a, b), k in zip(P3, ["평균06–12", "평균13–19", "평균20–26"]):
        r[k] = s[a:b].mean()
    r["시대편차"] = np.nanmax([r["평균06–12"], r["평균13–19"], r["평균20–26"]]) - np.nanmin([r["평균06–12"], r["평균13–19"], r["평균20–26"]])
    r["현재"] = s.dropna().iloc[-1]
    return r


if __name__ == "__main__":
    warn2 = list(diag.index[diag["경고"] >= 2])
    warn1 = list(diag.index[diag["경고"] >= 1])
    print("경고2+:", warn2); print("경고1+:", warn1)
    res, series = [], {}
    cfg = {
        "R0 v2 그대로": dict(),
        "A 검색량 부족 구간 제외": dict(search=True),
        "B1 추세 제거 (경고 2+)": dict(detrend=warn2),
        "B2 추세 제거 (경고 1+)": dict(detrend=warn1),
        "C 고정 구성 (2009년까지 시작)": dict(fixed=True),
        "W60 점수화 60개월": dict(window=60),
    }
    cache = {}
    for n, kw in cfg.items():
        sc, me = prepare(**kw)
        cache[n] = (sc, me)
        s = flat_speed(sc, me); series[n] = s; res.append(evaluate(n, s))
    sc, me = cache["R0 v2 그대로"]
    s = theme_within_speed(sc, me); series["D 주제 균등 (지표→주제→속도)"] = s; res.append(evaluate("D 주제 균등 (지표→주제→속도)", s))
    s = adaptive(sc, me, Y["실거래"]); series["E 성과 가중 (주제별)"] = s; res.append(evaluate("E 성과 가중 (주제별)", s))
    # 조합
    sc, me = prepare(search=True, detrend=warn2)
    for n, f in [("A+B1", flat_speed), ("A+B1+D", theme_within_speed)]:
        s = f(sc, me); series[n] = s; res.append(evaluate(n, s))
    s = adaptive(sc, me, Y["실거래"]); series["A+B1+E"] = s; res.append(evaluate("A+B1+E", s))
    df = pd.DataFrame(res).set_index("방식")
    pd.set_option("display.width", 260)
    print(df.round(2).to_string())
    df.to_csv(bt.ROOT / "results_v2" / "remedies.csv")
    pd.DataFrame(series).to_csv(bt.ROOT / "results_v2" / "remedies_series.csv")

"""엔진 구조 점검: 공개 시차, 실제 구성 지표 수, 지표 중복, 실효 가중치, 신고가 정의 편향."""
import numpy as np
import pandas as pd

import backtest as bt
import remedies as RM
import v3

raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
raw = raw[raw.index <= raw["__price"].last_valid_index()]
meta, aux = v3.load_meta()
P3 = RM.P3


def ics(s, t="실거래"):
    y = RM.Y[t]; s = s.reindex(y.index)
    return [bt.spearman(s[bt.window_mask(s.index, w)].to_numpy(), y[bt.window_mask(s.index, w)].to_numpy()) for w in P3]


def v3_index(R):
    return v3.compute(R[meta.index], meta)["final"]


pd.set_option("display.width", 220)
base = v3_index(raw)
print("[0] v3 현재 설정:", np.round(ics(base), 3), "KB최저", round(min(ics(base, "KB")), 3), "현재", round(base.dropna().iloc[-1], 1))

# 1) 20일 실행 기준 공개 시차 반영
LAG1 = [c for c in meta.index if c.startswith("거래_") and c not in ("거래_신고가비중", "거래_급락거래역수")] + ["공급_미분양역수",
        "자금_기준금리수준", "자금_기준금리변화", "자금_국고채10년변화", "시장_건설주모멘텀", "시장_건설주상대강도", "시장_KOSPI모멘텀"] + \
       [c for c in meta.index if c.startswith("관심_")]
LAG1 = [c for c in LAG1 if c in meta.index]
R = raw.copy(); R[LAG1] = R[LAG1].shift(1)
lagged = v3_index(R)
print("[1] 공개 시차 반영 (", len(LAG1), "개 지표 1개월 늦춤):", np.round(ics(lagged), 3), "KB최저", round(min(ics(lagged, "KB")), 3), "현재", round(lagged.dropna().iloc[-1], 1))
print("    1개월 늦춘 지표:", LAG1)

# 2) 고정 구성이 실제로 몇 개로 계산되나
sc = v3.scores(raw[meta.index])
n = sc.notna().sum(axis=1)
print("[2] v3 실제 사용 지표 수:", {str(k.year): int(v) for k, v in n.resample("YE").last().items() if k.year in (2006, 2007, 2008, 2009, 2010, 2011, 2012, 2016, 2026)})
full_from = n[n >= len(meta) - 1].index.min()
print("    35개 중 34개 이상이 처음 갖춰진 달:", full_from.date())

# 3) 거의 같은 지표 (점수 상관 0.85 이상)
C = sc.corr(min_periods=60)
pairs = [(a, b, round(C.loc[a, b], 2)) for i, a in enumerate(C.index) for b in C.index[i + 1:] if C.loc[a, b] > 0.85]
print("[3] 점수 상관 0.85 이상인 지표 쌍:", pairs)

# 4) 실효 가중치 (최신 달 기준: 그룹 1/3 × 그룹 내 1/n)
last = sc.iloc[-1].dropna().index
w = pd.Series({c: 1 / 3 / (meta.loc[last, "속도"] == meta.loc[c, "속도"]).sum() for c in last})
print("[4] 속도 그룹별 지표 수:", meta.loc[last, "속도"].value_counts().to_dict())
print("    주제별 실효 가중치(%):", (w.groupby(meta.loc[last, "주제"]).sum() * 100).round(1).sort_values(ascending=False).to_dict())
print("    지표 하나의 최대 가중치:", w.idxmax(), round(w.max() * 100, 1), "% / 최소:", w.idxmin(), round(w.min() * 100, 1), "%")

# 5) 눈금 끝 붙음
f = base[base.index >= "2006-01-01"].dropna()
print("[5] 0 또는 100에 붙은 달:", int(((f <= 0) | (f >= 100)).sum()), "/", len(f))

# 6) 신고가·급락 정의: 전체 기간 최고가 → 최근 36개월 최고가, 급락은 직전 거래가 24개월 이내일 때만
import molit_indicators as MI
df = MI.load()
g = df.groupby("key")
months = (df["date"].dt.year * 12 + df["date"].dt.month)
prev_m = g["date"].shift(1)
prev_months = (prev_m.dt.year * 12 + prev_m.dt.month)
prior_last = g["price"].shift(1)
# 최근 36개월 최고가: 같은 key의 과거 거래 중 36개월 이내만
df["_m"] = months
res = []
for k, sub in df.groupby("key", sort=False):
    if len(sub) < 2:
        continue
    m_, p_ = sub["_m"].to_numpy(), sub["price"].to_numpy()
    for i in range(1, len(sub)):
        win = (m_[:i] >= m_[i] - 36)
        if win.any():
            res.append((sub.index[i], p_[i] > p_[:i][win].max()))
hi36 = pd.Series(dict(res))
ok_all = g.cumcount() >= 1
hi_all = (df["price"] > g["price"].transform(lambda s: s.shift(1).cummax())) & ok_all
d = pd.DataFrame({"date": df["date"], "all": hi_all.where(ok_all), "w36": hi36.reindex(df.index)})
by_year = d.groupby(d["date"].dt.year)[["all", "w36"]].mean().round(3)
print("[6] 연도별 신고가 비중 (전체기간 기준 vs 최근 36개월 기준):"); print(by_year.loc[[2007, 2008, 2009, 2012, 2015, 2018, 2021, 2023, 2025]].to_string())
gap = months - prev_months
drop_all = ((df["price"] < 0.9 * prior_last) & ok_all)
drop_24 = ((df["price"] < 0.9 * prior_last) & (gap <= 24))
dd = pd.DataFrame({"date": df["date"], "all": drop_all.where(ok_all), "g24": drop_24.where(gap <= 24)})
print("    직전 거래와의 간격 중앙값(개월):", float(gap.median()), "| 24개월 넘는 비교 비율:", round(float((gap > 24).mean()), 3))
m_all = d.groupby("date")["w36"].mean()
m_drop = dd.groupby("date")["g24"].mean()
R2 = raw.copy()
R2["거래_신고가비중"] = m_all.rolling(3).mean().shift(2).reindex(R2.index)
R2["거래_급락거래역수"] = (-m_drop.rolling(3).mean().shift(2)).reindex(R2.index)
alt = v3_index(R2)
print("    정의 수정 후 v3:", np.round(ics(alt), 3), "KB최저", round(min(ics(alt, "KB")), 3))
R3 = R2.copy(); R3[LAG1] = R3[LAG1].shift(1)
both = v3_index(R3)
print("[7] 공개 시차 + 신고가 정의 수정 함께:", np.round(ics(both), 3), "KB최저", round(min(ics(both, "KB")), 3), "현재", round(both.dropna().iloc[-1], 1))
for nm, s in [("현재 v3", base), ("시차 반영", lagged), ("시차+정의", both)]:
    print(f"    {nm}: 2011~ 3구간", np.round([bt.spearman(s.reindex(RM.Y['실거래'].index)[bt.window_mask(RM.Y['실거래'].index, w)].to_numpy(), RM.Y['실거래'][bt.window_mask(RM.Y['실거래'].index, w)].to_numpy()) for w in [("2011-01-01", "2016-12-01"), ("2017-01-01", "2021-12-01"), ("2022-01-01", "2026-12-01")]], 3))

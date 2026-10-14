"""25개 구 엔진 후보 비교.

평가 (결과를 보기 전에 정함, 2011년 2월 이후):
  M1 시간 정확도: 구마다 '그 구 점수 ↔ 그 구 이후 12개월 실거래 가격' 순위상관, 25개 구 평균
  M2 구 간 순위 정확도: 달마다 '25개 구 점수 순위 ↔ 이후 12개월 구별 가격 순위' 순위상관의 평균
선정: M1이 서울 지수보다 0.02 넘게 나쁘지 않은 후보 중 M2가 가장 높은 것.
      M2가 0.05 미만이거나 해마다 평균이 양수인 해가 2/3 미만이면 '구 전용 엔진은 효과 없음'으로 본다.
후보:
  A 지금 구 엔진 (v3.2 + 구 값)       B 권역 지수를 그 구에 그대로     C 서울 지수 (구 간 차이 없음)
  D 구 고유 표만 (11개 지표)          E 상대 엔진: 구 고유 지표를 달마다 25개 구 안에서 순위로 바꾸고,
                                        그때까지(14개월 전까지) 확인된 성적으로 가중 (미래 정보 없음)
  K 참고: 직전 12개월 구 가격 상승률 순위 (가중치 추정 없음)
"""
import numpy as np
import pandas as pd

import backtest as bt
import v3

ROOT = bt.ROOT
Z0 = pd.read_pickle(ROOT / "results_zone" / "zone_calc.pkl")
ZV = pd.read_pickle(ROOT / "results_zone" / "zone_v3.pkl")
seoul = pd.read_pickle(ROOT / "results_v2" / "v3_seoul.pkl")
GUS = list(Z0["gus"])
idx = Z0["gus"][GUS[0]]["ind"].index
OFF = pd.Timestamp(v3.OFFICIAL_START)
OWN = ["가격_3개월모멘텀", "가격_12개월이평괴리", "전세_3개월모멘텀", "부담_전세가율역수", "거래_거래량", "거래_거래량증가",
       "거래_외지인비중", "거래_원정매수비중", "거래_법인매수비중", "거래_신고가비중", "거래_급락거래역수"]
Y = pd.DataFrame({g: Z0["gus"][g]["fwd12"] for g in GUS}).reindex(idx)
meta, aux_meta = v3.load_meta()


def frame(f):
    return pd.DataFrame({g: f(g) for g in GUS}).reindex(idx)


def cs_ic(S, Yv, min_n=20):
    out = {}
    for t in S.index:
        a, b = S.loc[t], Yv.loc[t]
        m = a.notna() & b.notna()
        if m.sum() >= min_n and a[m].nunique() > 1:
            out[t] = bt.spearman(a[m].to_numpy(), b[m].to_numpy())
    return pd.Series(list(out.values()), index=pd.DatetimeIndex(list(out.keys())), dtype=float)


def cs_rank(X):
    r = X.rank(axis=1, pct=True)
    return (r - 0.5).where(X.notna().sum(axis=1) >= 15, np.nan)


# ---------- 후보 점수 (행=달, 열=구)
S = {}
S["A 지금 구 엔진"] = frame(lambda g: ZV["gus"][g]["final"])
S["B 권역 지수"] = frame(lambda g: ZV["zones"][ZV["gus"][g]["zone"]]["final"])
S["C 서울 지수"] = frame(lambda g: seoul["final"])
own_meta = meta.loc[[c for c in OWN if c in meta.index]]
S["D 구 고유 표만"] = frame(lambda g: v3.compute(Z0["gus"][g]["ind"], own_meta)["final"])

# 상대 엔진 (walk-forward)
mom12 = frame(lambda g: np.log(Z0["gus"][g]["rs"]).diff(12).shift(2))
feats = {c: frame(lambda g, c=c: Z0["gus"][g]["ind"][c]) for c in OWN}
feats["실거래_12개월상승률"] = mom12
R = {k: cs_rank(X) for k, X in feats.items()}
IC = pd.DataFrame({k: cs_ic(X, Y, min_n=15) for k, X in feats.items()}).reindex(idx)
E = pd.DataFrame(np.nan, index=idx, columns=GUS)
W = {}
for i, t in enumerate(idx):
    past = IC.loc[: t - pd.DateOffset(months=14)]  # 이후 12개월 가격 + 실거래 신고 시차 2개월이 확인된 달만
    n = past.notna().sum()
    w = past.mean().where(n >= 36, 0.0).fillna(0.0)
    if w.abs().sum() == 0:
        continue
    W[t] = w
    sc = sum(w[k] * R[k].loc[t].fillna(0) for k in R) / w.abs().sum()
    E.loc[t] = sc.where(R["가격_3개월모멘텀"].loc[t].notna())
S["E 상대 엔진 (서울 ± 상대)"] = S["C 서울 지수"] + 30 * E  # 구 간 순위는 E, 수준은 서울 지수 ± 최대 약 15점
S["K 참고: 직전 12개월 상승률"] = mom12


def m1(Sc):
    m = idx >= OFF
    return float(np.nanmean([bt.spearman(Sc[g][m].to_numpy(), Y[g][m].to_numpy()) for g in GUS]))


rows, yearly = {}, {}
for n, Sc in S.items():
    ic = cs_ic(Sc, Y)
    ic = ic[ic.index >= OFF]
    yr = ic.groupby(ic.index.year).mean()
    yearly[n] = yr
    rows[n] = {"M1 시간 정확도": m1(Sc), "M2 구 간 순위": ic.mean() if len(ic) else np.nan,
               "M2 양수인 달": (ic > 0).mean() if len(ic) else np.nan,
               "M2 양수인 해": f"{int((yr > 0).sum())}/{len(yr)}" if len(yr) else "-",
               "M2 t(겹침 보정)": ic.mean() / (ic.std() / np.sqrt(len(ic) / 12)) if len(ic) > 12 else np.nan}
df = pd.DataFrame(rows).T
pd.set_option("display.width", 220)
print(df.round(3).to_string())
print("\n해마다 M2 평균 (구 간 순위상관)")
print(pd.DataFrame(yearly).T.round(2).to_string())
print("\n구 간 순위상관: 지표 하나씩 (2011~ 달 평균, 양수 = 이 지표가 높은 구가 이후 더 오름)")
ic11 = IC[IC.index >= OFF]
print(pd.DataFrame({"평균": ic11.mean(), "양수인 달": (ic11 > 0).mean()}).sort_values("평균").round(3).to_string())
if W:
    print("\n상대 엔진 최신 가중치\n", pd.Series(list(W.values())[-1]).round(3).sort_values().to_string())
base = df.loc["C 서울 지수", "M1 시간 정확도"]
ok = df[(df["M1 시간 정확도"] >= base - 0.02) & df.index.str[0].isin(list("ABDE"))]
best = ok["M2 구 간 순위"].idxmax()
yr = yearly[best]
print(f"\n선정 규칙 결과: {best} (M2 {df.loc[best, 'M2 구 간 순위']:.3f}, 양수인 해 {int((yr > 0).sum())}/{len(yr)})",
      "→ 효과 있음" if df.loc[best, "M2 구 간 순위"] >= 0.05 and (yr > 0).mean() >= 2 / 3 else "→ 구 전용 엔진 효과 없음")
pd.to_pickle({"table": df, "yearly": yearly, "E": E, "weights": W, "feature_ic": IC}, ROOT / "results_zone" / "gu_engine_study.pkl")

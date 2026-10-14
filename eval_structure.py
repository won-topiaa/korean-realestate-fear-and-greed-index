"""4·5번 구조 수정 후보 비교 (공개 시차·지표 정의 수정 반영 후).

선정 기준(결과를 보기 전에 정함): 5년 이동 구간(2008~2020 시작, 13개) 순위상관 중앙값이 가장 높은 후보.
단, 5년 구간 최저값이 기준선(C0)보다 0.05 넘게 나쁘면 제외.
"""
import numpy as np
import pandas as pd

import backtest as bt
import remedies as RM
import v3

raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
raw = raw[raw.index <= raw["__price"].last_valid_index()]
meta, _ = v3.load_meta()
sc = v3.scores(raw[meta.index])
y = RM.Y["실거래"]

# 같은 원자료 = 한 표 (같은 속도 그룹 안에서)
MERGE = {"가격_상승구비율": "가격_3개월모멘텀", "거래_원정매수비중": "거래_외지인비중",
         "거래_급락거래역수": "거래_신고가비중", "시장_건설주상대강도": "시장_건설주모멘텀"}
DROP = ["전세_매매선호"]


def votes(sc, meta):
    keep = [c for c in meta.index if c not in DROP]
    vs, vm = {}, {}
    for c in keep:
        head = MERGE.get(c, c)
        vs.setdefault(head, []).append(c)
    V = pd.DataFrame({h: sc[cs].mean(axis=1, skipna=True) for h, cs in vs.items()})
    return V, meta.loc[list(vs)]


def speed_equal(V, M):
    return pd.concat([V[M.index[M["속도"] == s]].mean(axis=1) for s in v3.SPEED], axis=1).mean(axis=1)


def theme_in_speed(V, M):
    gs = []
    for s in v3.SPEED:
        sub = M[M["속도"] == s]
        gs.append(pd.concat([V[sub.index[sub["주제"] == t]].mean(axis=1) for t in sub["주제"].unique()], axis=1).mean(axis=1))
    return pd.concat(gs, axis=1).mean(axis=1)


def all_equal(V, M):
    return V.mean(axis=1)


def google_one(V, M):
    g = [c for c in V.columns if c.startswith("관심_")]
    V2 = V.drop(columns=g).assign(관심_구글=V[g].mean(axis=1))
    M2 = pd.concat([M.drop(index=g), M.loc[[g[0]]].rename(index={g[0]: "관심_구글"})])
    return speed_equal(V2, M2), (V2, M2)


V, M = votes(sc, meta)
cands = {
    "C0 기준선 (v3, 시차 반영)": v3.spread(pd.concat([sc[meta.index[meta["속도"] == s]].mean(axis=1) for s in v3.SPEED], axis=1).mean(axis=1)),
    "C1 중복 제거 + 속도 3그룹": v3.spread(speed_equal(V, M)),
    "C2 중복 제거 + 그룹 안 주제 균등": v3.spread(theme_in_speed(V, M)),
    "C3 중복 제거 + 표 전체 균등": v3.spread(all_equal(V, M)),
    "C4 중복 제거 + 구글 검색 한 표": v3.spread(google_one(V, M)[0]),
}
starts = pd.date_range("2008-01-01", "2020-01-01", freq="12MS")


def rolling(s):
    s = s.reindex(y.index)
    return np.array([bt.spearman(s[(s.index >= a) & (s.index < a + pd.DateOffset(years=5))].to_numpy(),
                                 y[(y.index >= a) & (y.index < a + pd.DateOffset(years=5))].to_numpy()) for a in starts])


rows = []
for n, s in cands.items():
    w = rolling(s); si = s.reindex(y.index)
    p3 = [bt.spearman(si[bt.window_mask(si.index, a)].to_numpy(), y[bt.window_mask(si.index, a)].to_numpy()) for a in RM.P3]
    kb = min(bt.spearman(si[bt.window_mask(si.index, a)].to_numpy(), RM.Y["KB"][bt.window_mask(si.index, a)].to_numpy()) for a in RM.P3)
    full = bt.spearman(si[si.index >= "2011-01-01"].to_numpy(), y[y.index >= "2011-01-01"].to_numpy())
    rows.append({"후보": n, "5년 중앙값": np.nanmedian(w), "5년 최저": np.nanmin(w), "0.3미만": int((w < 0.3).sum()),
                 "2011~ 전체": full, "세구간": "/".join(f"{v:.2f}" for v in p3), "KB최저": kb, "현재": s.dropna().iloc[-1]})
df = pd.DataFrame(rows).set_index("후보")
base_min = df.iloc[0]["5년 최저"]
df["탈락"] = df["5년 최저"] < base_min - 0.05
pd.set_option("display.width", 220)
print(df.round(3).to_string())
ok = df[~df["탈락"]]
print("\n선정:", ok["5년 중앙값"].idxmax())
# 실효 가중치 (최신 달)
for name, fn in [("C0", None), ("C1", speed_equal), ("C2", theme_in_speed)]:
    if fn is None:
        last = sc.iloc[-1].dropna().index; mm = meta.loc[last]
        w = pd.Series({c: 1 / 3 / (mm["속도"] == mm.loc[c, "속도"]).sum() for c in last}); th = mm["주제"]
    elif fn is speed_equal:
        last = V.iloc[-1].dropna().index; mm = M.loc[last]
        w = pd.Series({c: 1 / 3 / (mm["속도"] == mm.loc[c, "속도"]).sum() for c in last}); th = mm["주제"]
    else:
        last = V.iloc[-1].dropna().index; mm = M.loc[last]
        w = pd.Series({c: 1 / 3 / mm[mm["속도"] == mm.loc[c, "속도"]]["주제"].nunique() / ((mm["속도"] == mm.loc[c, "속도"]) & (mm["주제"] == mm.loc[c, "주제"])).sum() for c in last}); th = mm["주제"]
    print(name, "주제별 실효 가중치(%):", (w.groupby(th).sum() * 100).round(1).sort_values(ascending=False).to_dict())
pd.to_pickle({"V": V, "M": M}, bt.ROOT / "results_v2" / "votes.pkl")

# C5: 같은 출처 규칙을 끝까지 — KB 소득연계 통계(PIR·구매력지수)도 한 표
MERGE["부담_구매력역수"] = "부담_PIR"
V5, M5 = votes(sc, meta)
s5, (V5g, M5g) = google_one(V5, M5)
s5 = v3.spread(s5)
w = rolling(s5); si = s5.reindex(y.index)
p3 = [bt.spearman(si[bt.window_mask(si.index, a)].to_numpy(), y[bt.window_mask(si.index, a)].to_numpy()) for a in RM.P3]
kb = min(bt.spearman(si[bt.window_mask(si.index, a)].to_numpy(), RM.Y["KB"][bt.window_mask(si.index, a)].to_numpy()) for a in RM.P3)
full = bt.spearman(si[si.index >= "2011-01-01"].to_numpy(), y[y.index >= "2011-01-01"].to_numpy())
print(f"\nC5 (C4 + PIR·구매력 한 표): 5년 중앙값 {np.nanmedian(w):.3f} · 최저 {np.nanmin(w):.3f} · 0.3미만 {int((w < 0.3).sum())} · 2011~ {full:.3f} · 세구간 {'/'.join(f'{v:.2f}' for v in p3)} · KB최저 {kb:.3f} · 현재 {s5.dropna().iloc[-1]:.1f} · 탈락 {np.nanmin(w) < base_min - 0.05}")
last = V5g.iloc[-1].dropna().index; mm = M5g.loc[last]
wt = pd.Series({c: 1 / 3 / (mm["속도"] == mm.loc[c, "속도"]).sum() for c in last})
print("C5 표 수:", mm["속도"].value_counts().to_dict(), "| 주제별 실효 가중치(%):", (wt.groupby(mm["주제"]).sum() * 100).round(1).sort_values(ascending=False).to_dict())
print("C5 최대 단일 표:", wt.idxmax(), round(wt.max() * 100, 1), "%")

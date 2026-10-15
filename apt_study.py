"""단지 검색 '실거래 위치 점수' 설계 검증 (2026-10). 결과는 apt_score.py의 고정값이 된다.

1) 층 보정: 같은 단지·평형·반기 안에서 층에 따른 가격 차 → 층 효과표. 2018년까지로 만들고 2019년~에서 확인.
2) 평형 환산: 같은 단지 다른 평형 거래로 이 평형 가격을 맞히기. ㎡당 같은 값 / 서울 공통 면적 탄력성 / 단지별 평형 비율(줄임).
   2020년까지로 만들고 2021년~ 거래를 맞혀 본다. → 단지별 비율을 최근 3년 거래로(k=1) 구할 때 가장 정확 (중앙 오차 4.6%).
3) 점수: 스토캐스틱(최고·최저 사이 위치) vs 순위, 층 보정 유무, 같은 평형만 vs 다른 평형으로 채움.
   기준: 점수를 낸 뒤 6개월 안 같은 단지 다음 거래(최대 3건)가 '최근 거래'보다 낮게/높게 나오는지 (시장·층·평형 보정 후).
   → 층 보정은 크게 도움(0.41 → 0.50), 스토캐스틱과 순위는 비슷, 같은 평형 5건 미만일 때만 다른 평형으로 채우는 게
     범위(73% → 88%)를 넓히면서 정확도를 지킴. 평형을 무조건 섞으면 같은 평형 다음 거래 기준으로 나빠짐.
"""
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import molit_indicators as MI
import molit_store

T0 = time.time()
DAY = np.timedelta64(1, "D")


def load():
    df = molit_store.load()
    df = df[(df.cdealType == "") & (df.dealingGbn != "직거래")].copy()  # 해제·직거래 제외
    df["price"] = pd.to_numeric(df.dealAmount.str.replace(",", ""), errors="coerce")
    df["area"] = pd.to_numeric(df.excluUseAr, errors="coerce")
    df["floor"] = pd.to_numeric(df["floor"], errors="coerce")
    df = df[(df.price > 0) & (df.area > 0) & df.floor.notna()].copy()
    df["month"] = pd.to_datetime(dict(year=df.dealYear.astype(int), month=df.dealMonth.astype(int), day=1))
    df["date"] = df.month + pd.to_timedelta(pd.to_numeric(df.dealDay, errors="coerce").fillna(15) - 1, unit="D")
    df["type"] = df.area.round(0)
    return df.sort_values(["aptSeq", "date", "price"], kind="mergesort").reset_index(drop=True)


def gu_index():
    """구별 반복매매지수 (시장 변화 보정용). 최근 달은 그대로 쓰고 비면 앞 값."""
    t = MI.load()
    months = pd.date_range(t.date.min(), t.date.max(), freq="MS")
    out = {}
    for g, sub in t.groupby("gu"):
        rs, _ = MI.repeat_sales(sub)
        out[g] = np.log(rs.reindex(months).ffill())
    return pd.DataFrame(out)


FLOOR_BINS = [1, 2, 3, 4, 5, 7, 10, 14, 19, 29, 999]  # 1층 이하, 2, 3, 4, 5, 6~7, 8~10, 11~14, 15~19, 20~29, 30+
FLOOR_LAB = ["1층 이하", "2층", "3층", "4층", "5층", "6~7층", "8~10층", "11~14층", "15~19층", "20~29층", "30층+"]
REF = 6  # 기준: 8~10층


def floor_bucket(f):
    return np.searchsorted(FLOOR_BINS, np.maximum(f, 1), side="left")


def demean(a, g):
    """g(그룹 번호) 안 평균을 뺀다 (bincount: 문자열 groupby보다 훨씬 가벼움)."""
    a = np.asarray(a, dtype=float)
    a2 = a.reshape(len(a), -1)
    cnt = np.bincount(g)
    out = np.empty_like(a2)
    for j in range(a2.shape[1]):
        out[:, j] = a2[:, j] - (np.bincount(g, weights=a2[:, j]) / np.maximum(cnt, 1))[g]
    return out.reshape(a.shape)


def codes(*cols):
    return pd.MultiIndex.from_arrays(cols).factorize()[0] if len(cols) > 1 else pd.factorize(cols[0])[0]


def floor_design(d, top):
    b = floor_bucket(d.floor.to_numpy())
    X = np.zeros((len(d), len(FLOOR_LAB) - 1 + (1 if top else 0)))
    cols = [i for i in range(len(FLOOR_LAB)) if i != REF]
    for j, i in enumerate(cols):
        X[:, j] = b == i
    if top:  # 탑층 (관측된 단지 최고층, 5층 이상 단지만)
        X[:, -1] = (d.floor.to_numpy() >= d.maxfl.to_numpy()) & (d.maxfl.to_numpy() >= 5)
    return X, cols


def fit_floor(d, top):
    g = codes(d.aptSeq.to_numpy(), d.type.to_numpy(), d.half.to_numpy())
    keep = np.bincount(g)[g] >= 3
    X, cols = floor_design(d, top)
    y = d.y.to_numpy()
    gk = pd.factorize(g[keep])[0]
    Xd, yd = demean(X[keep], gk), demean(y[keep], gk)
    beta = np.linalg.lstsq(Xd, yd, rcond=None)[0]
    return beta, (Xd, yd)


def floor_effect(d, beta, top):
    X, _ = floor_design(d, top)
    return X @ beta


def main():
    df = load()
    gi = gu_index()
    df["mk"] = gi.stack().reindex(pd.MultiIndex.from_arrays([df.month, df.lawd])).to_numpy()
    df = df[df.mk.notna()].reset_index(drop=True)
    df["y"] = np.log(df.price) - df.mk  # 시장 변화를 뺀 가격
    df["half"] = df.month.dt.year.astype(str) + np.where(df.month.dt.month <= 6, "a", "b")
    df["maxfl"] = df.groupby("aptSeq").floor.transform("max")
    print(f"거래 {len(df):,}건 · 단지 {df.aptSeq.nunique():,} · 준비 {time.time() - T0:.0f}s", flush=True)

    # ---------- 1) 층 보정 ----------
    print("\n[1] 층 보정 — 같은 단지·평형·반기 안 가격 차이 (기준 8~10층)")
    tr, te = df[df.month < "2019-01-01"], df[df.month >= "2019-01-01"]
    rows = []
    for top in (False, True):
        beta, _ = fit_floor(tr, top)
        _, (Xd, yd) = fit_floor(te, top)
        r2 = 1 - np.var(yd - Xd @ beta) / np.var(yd)
        rows.append(("층 구간" + (" + 탑층" if top else ""), round(r2 * 100, 2)))
    print(pd.DataFrame(rows, columns=["모형", "2019~ 설명력(%)"]).to_string(index=False))
    # 탑층(관측 최고층) 항은 2019~ 설명력을 못 올려서 뺀다 → 층 구간만
    b_old, _ = fit_floor(df[df.month < "2016-01-01"], False)
    b_new, _ = fit_floor(df[df.month >= "2016-01-01"], False)
    b_all, _ = fit_floor(df, False)
    cols = [FLOOR_LAB[i] for i in range(len(FLOOR_LAB)) if i != REF]
    tab = pd.DataFrame({"2006~15": b_old, "2016~26": b_new, "전체": b_all}, index=cols)
    print((np.expm1(tab) * 100).round(1).to_string())
    print("층 효과(log, 전체):", dict(zip(cols, np.round(b_all, 4))))
    df["ff"] = floor_effect(df, b_all, False)
    df["yf"] = df.y - df.ff  # 시장·층 보정 가격

    # ---------- 2) 평형 환산 ----------
    print("\n[2] 평형 환산 — 다른 평형 최근 거래(최대 10건, 2년 안)로 이 거래 가격 맞히기 (2021년~, 중앙 오차 %)")
    df["la"] = np.log(df.area)
    trn = (df.month < "2021-01-01").to_numpy()
    g = codes(df.aptSeq.to_numpy()[trn], df.half.to_numpy()[trn])
    xd, yd = demean(df.la.to_numpy()[trn], g), demean(df.yf.to_numpy()[trn], g)
    B = float(xd @ yd / (xd @ xd))
    print(f"서울 공통 면적 탄력성 b = {B:.3f} (면적 1% ↑ → 가격 {B:.2f}% ↑)")

    def type_dev(sub, k):
        e = pd.Series(demean((sub.yf - B * sub.la).to_numpy(), codes(sub.aptSeq.to_numpy(), sub.half.to_numpy())), index=sub.index)
        s = e.groupby([sub.aptSeq, sub.type]).agg(["sum", "count"])
        return s["sum"] / (s["count"] + k)  # 거래가 적으면 0(공통 탄력성) 쪽으로 줄임

    keyidx = pd.MultiIndex.from_arrays([df.aptSeq, df.type])
    methods = {"㎡당 가격 같다고 봄": (1.0, None), "공통 탄력성": (B, None)}
    for k in (2, 5, 10):
        methods[f"단지별 비율 (k={k})"] = (B, type_dev(df[trn], k).reindex(keyidx).fillna(0).to_numpy())
    for yrs in (2, 3, 5):  # 평형 비율은 시기에 따라 바뀜 → 최근 몇 년만 쓰는 게 나은지
        rec = trn & (df.month >= pd.Timestamp("2021-01-01") - pd.DateOffset(years=yrs)).to_numpy()
        for k in (1, 2):
            methods[f"단지별 비율 (최근 {yrs}년, k={k})"] = (B, type_dev(df[rec], k).reindex(keyidx).fillna(0).to_numpy())
    errs = {m: [] for m in methods}
    errs["(참고) 같은 평형 최근 거래"] = []
    seq = df.aptSeq.to_numpy(); dates = df.date.to_numpy(); typ = df.type.to_numpy()
    yf, la, ff, mk = df.yf.to_numpy(), df.la.to_numpy(), df.ff.to_numpy(), df.mk.to_numpy()
    lp = np.log(df.price.to_numpy())
    bounds = np.flatnonzero(np.r_[True, seq[1:] != seq[:-1], True])
    t21 = np.datetime64("2021-01-01")
    for a, b in zip(bounds[:-1], bounds[1:]):
        if dates[b - 1] < t21 or len(np.unique(typ[a:b])) < 2:
            continue
        t = dates[a:b]
        for i in range(a, b):
            if dates[i] < t21:
                continue
            lo = a + np.searchsorted(t, dates[i] - 730 * DAY, side="left")
            hi = a + np.searchsorted(t, dates[i], side="left")  # 그날 전까지
            if hi <= lo:
                continue
            idx = np.arange(lo, hi)
            oth = idx[typ[idx] != typ[i]][-10:]
            same = idx[typ[idx] == typ[i]][-10:]
            if len(oth) < 3 or len(same) < 3:  # 둘 다 있는 거래에서 비교
                continue
            for m, (bb, dev) in methods.items():
                d_ = dev if dev is not None else np.zeros(len(df))
                conv = yf[oth] - bb * la[oth] - d_[oth] + bb * la[i] + d_[i]
                errs[m].append(np.median(conv) + ff[i] + mk[i] - lp[i])
            errs["(참고) 같은 평형 최근 거래"].append(np.median(yf[same]) + ff[i] + mk[i] - lp[i])
    print(pd.DataFrame({m: [len(v), round(np.median(np.abs(v)) * 100, 2), round(np.median(v) * 100, 2)]
                        for m, v in errs.items()}, index=["거래", "중앙 오차%", "치우침%"]).T.to_string())
    # 층 보정 효과도 같은 방식으로: 같은 평형 최근 거래로 맞힐 때 층 보정 유무
    e_nf, e_f = [], []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if dates[b - 1] < t21:
            continue
        t = dates[a:b]
        for i in range(a, b):
            if dates[i] < t21:
                continue
            lo = a + np.searchsorted(t, dates[i] - 730 * DAY, side="left")
            hi = a + np.searchsorted(t, dates[i], side="left")
            idx = np.arange(lo, hi)
            same = idx[typ[idx] == typ[i]][-10:]
            if len(same) < 3:
                continue
            y_ = yf + ff  # 시장만 보정
            e_nf.append(np.median(y_[same]) + mk[i] - lp[i])
            e_f.append(np.median(yf[same]) + ff[i] + mk[i] - lp[i])
    print(f"층 보정 효과 (같은 평형으로 맞히기, 2021~): 보정 없음 {np.median(np.abs(e_nf)) * 100:.2f}% → 층 보정 {np.median(np.abs(e_f)) * 100:.2f}% (거래 {len(e_f):,})")

    # ---------- 3) 점수 ----------
    K = 2  # [2]에서 가장 잘 맞은 줄임 정도
    dev = type_dev(df, K).reindex(keyidx).fillna(0).to_numpy()
    base = yf - B * la - dev  # 단지 안에서 평형을 맞춘 가격 (같은 평형끼리는 상수 차이라 순위·위치가 같음)
    raw = lp - mk - B * la - dev  # 층 보정 없는 판
    print(f"\n[3] 점수 (평형 비율 k={K}) — 계산 {time.time() - T0:.0f}s", flush=True)

    def pos_rank(v):
        x = v[-1]
        return ((v < x).sum() + 0.5 * ((v == x).sum() - 1)) / (len(v) - 1) * 100

    def pos_stoch(v):
        lo_, hi_ = v.min(), v.max()
        return 50.0 if hi_ - lo_ < 1e-9 else (v[-1] - lo_) / (hi_ - lo_) * 100

    variants = {
        "같은 평형·층 보정 없음·순위": ("same", raw, pos_rank),
        "같은 평형·층 보정·순위": ("same", base, pos_rank),
        "같은 평형·층 보정·스토캐스틱": ("same", base, pos_stoch),
        "같은 평형 5건 미만이면 다른 평형으로 채움·스토캐스틱": ("fill5", base, pos_stoch),
        "같은 평형 10건 미만이면 다른 평형으로 채움·스토캐스틱": ("fill10", base, pos_stoch),
        "평형 구분 없이 최근 10건·스토캐스틱": ("mix", base, pos_stoch),
    }
    res = {v: [] for v in variants}
    t14, t26 = np.datetime64("2014-01-01"), np.datetime64("2026-04-01")
    for a, b in zip(bounds[:-1], bounds[1:]):
        t = dates[a:b]
        if t[-1] < t14:
            continue
        for i in range(a, b):
            if dates[i] < t14 or dates[i] >= t26:
                continue
            j = np.arange(i + 1, a + np.searchsorted(t, dates[i] + 183 * DAY, side="right"))[:3]
            if len(j) == 0:
                continue
            y_out = np.median(base[j]) - base[i]  # 다음 거래(평형 환산·층·시장 보정) − 최근 거래
            js = np.arange(i + 1, a + np.searchsorted(t, dates[i] + 183 * DAY, side="right"))
            js = js[typ[js] == typ[i]][:3]
            y_same = np.median(base[js]) - base[i] if len(js) else np.nan  # 같은 평형 다음 거래만
            lo = a + np.searchsorted(t, dates[i] - 730 * DAY, side="left")
            idx = np.arange(lo, i + 1)
            same_m = typ[idx] == typ[i]
            same, oth = idx[same_m][-10:], idx[~same_m]
            for v, (rule, val, fn) in variants.items():
                if rule == "same":
                    pool = same
                elif rule == "mix":
                    pool = idx[-10:]
                else:
                    need = (5 if rule == "fill5" else 10)
                    pool = same if len(same) >= need else np.sort(np.r_[same, oth[-(10 - len(same)):]] if len(same) < 10 else same)
                if len(pool) < 5:
                    continue
                if pool[-1] != i:  # 최근 거래가 맨 끝
                    pool = np.r_[pool[pool != i], i]
                res[v].append((fn(val[pool]), y_out, len(np.unique(typ[pool])) > 1, y_same, (typ[pool] == typ[i]).sum() < 5))
    n_all = sum(1 for a, b in zip(bounds[:-1], bounds[1:]) for i in range(a, b) if t14 <= dates[i] < t26)
    out = []
    for v, r in res.items():
        r = np.array(r)
        ic = spearmanr(r[:, 0], r[:, 1])[0]
        s_ = r[~np.isnan(r[:, 3])]
        ic_s = spearmanr(s_[:, 0], s_[:, 3])[0]
        th = s_[s_[:, 4] == 1]  # 같은 평형이 5건 미만이던 거래만 (채움의 효과가 드러나는 곳)
        ic_t = spearmanr(th[:, 0], th[:, 3])[0] if len(th) > 100 else np.nan
        out.append((v, len(r), round(ic, 3), len(s_), round(ic_s, 3), round(s_[s_[:, 0] >= 80, 3].mean() * 100, 2),
                    round(s_[s_[:, 0] <= 20, 3].mean() * 100, 2), len(th), round(ic_t, 3), round(r[:, 2].mean() * 100, 1)))
    print(pd.DataFrame(out, columns=["방식", "점수 낸 거래", "상관(아무 평형 다음거래)", "같은평형 다음거래 있음", "상관(같은 평형 다음거래)",
                                     "80점↑ 같은평형 다음%", "20점↓ 같은평형 다음%", "같은평형<5건 거래", "그중 상관", "섞임%"]).to_string(index=False))

    # 지금 기준 범위: 최근 3개월 거래가 있는 단지·평형 중 점수가 나오는 비율
    END = df.date.max()
    rec = df[df.date > END - 90 * DAY]
    last = rec.groupby(["aptSeq", "type"]).tail(1).index.to_numpy()
    cov = {"same": 0, "fill5": 0, "fill10": 0}
    for i in last:
        a = bounds[np.searchsorted(bounds, i, side="right") - 1]
        lo = a + np.searchsorted(dates[a:i + 1], dates[i] - 730 * DAY, side="left")
        idx = np.arange(lo, i + 1)
        ns = (typ[idx] == typ[i]).sum()
        cov["same"] += ns >= 5
        cov["fill5"] += len(idx) >= 5
    print(f"\n지금 범위 (최근 3개월 거래 {len(last):,}개 단지·평형): 같은 평형만 {cov['same'] / len(last) * 100:.1f}% → 다른 평형으로 채우면 {cov['fill5'] / len(last) * 100:.1f}%")
    print(f"평가 대상 거래 {n_all:,} · 전체 {time.time() - T0:.0f}s")
    print(f"고정값: B={B:.4f}, K={K}, 층 효과 {dict(zip(cols, np.round(b_all, 4)))}")


if __name__ == "__main__":
    main()

"""그룹별 공포탐욕 점수가 실제 서울 아파트 시장을 얼마나 잘 측정하는지 백테스트.

점수화: 각 지표를 과거 120개월(최소 24개월) 롤링 백분위로 0~100 변환 — 그 시점까지의 정보만 사용.
그룹 점수: 소속 지표 점수의 단순 평균 (사용 가능한 지표만).
정답(실제 시장 변화): KB 서울 아파트 매매지수
  - 동행: t-3 → t+3 변화 (지금 시장이 달아올랐는지)
  - 선행: 점수를 발표한 달(t+1, timing.PUB_OFFSET)부터 6·12개월 변화 (앞으로 오르는지)
평가: 스피어만 순위상관(IC). 학습 2006~2016 / 검증 2017~ 로 나눠 안정성 확인.
"""
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

import timing

ROOT = Path(__file__).parent
OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)

TRAIN = ("2006-01-01", "2016-12-01")
TEST = ("2017-01-01", "2026-12-01")
FULL = ("2006-01-01", "2026-12-01")
WINDOW, MINP = 120, 24
TARGET = "KB"  # KB | 부동산원 | 실거래


def pct_score(s: pd.Series) -> pd.Series:
    v = s.to_numpy()
    out = np.full(len(v), np.nan)
    for i in range(len(v)):
        if np.isnan(v[i]):
            continue
        w = v[max(0, i - WINDOW + 1): i + 1]
        w = w[~np.isnan(w)]
        if len(w) < MINP:
            continue
        out[i] = ((w < v[i]).sum() + 0.5 * (w == v[i]).sum()) / len(w) * 100
    return pd.Series(out, index=s.index)


def rank(a):
    return pd.Series(a).rank().to_numpy()


def spearman(x, y):
    m = ~(np.isnan(x) | np.isnan(y))
    if m.sum() < 24:
        return np.nan
    return np.corrcoef(rank(x[m]), rank(y[m]))[0, 1]


def partial_spearman(x, y, z):
    """z(과거 가격 모멘텀)를 통제한 뒤 남는 x-y 순위상관 = 가격 추세 외 추가 정보."""
    m = ~(np.isnan(x) | np.isnan(y) | np.isnan(z))
    if m.sum() < 24:
        return np.nan
    rx, ry, rz = rank(x[m]), rank(y[m]), rank(z[m])
    A = np.c_[np.ones(m.sum()), rz]
    ex = rx - A @ np.linalg.lstsq(A, rx, rcond=None)[0]
    ey = ry - A @ np.linalg.lstsq(A, ry, rcond=None)[0]
    return np.corrcoef(ex, ey)[0, 1]


def block_bootstrap_ic(x, y, n=1000, block=12, seed=0):
    m = ~(np.isnan(x) | np.isnan(y))
    x, y = x[m], y[m]
    T = len(x)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(T / block))
    ics = []
    for _ in range(n):
        starts = rng.integers(0, T - block + 1, nb)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:T]
        ics.append(np.corrcoef(rank(x[idx]), rank(y[idx]))[0, 1])
    return np.percentile(ics, [5, 95])


def load():
    df = pd.read_csv(ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
    meta = pd.read_csv(ROOT / "data" / "indicator_meta.csv", index_col=0).fillna("")
    price = df.pop("__price")
    df = df[[c for c in df.columns if c in meta.index]]  # 메타에 등록된 지표만
    if TARGET != "KB":
        tg = pd.read_csv(ROOT / "data" / "targets_extra.csv", index_col=0, parse_dates=True)
        price = tg[{"부동산원": "부동산원지수", "실거래": "실거래지수"}[TARGET]].reindex(df.index)
    df = df[df.index <= price.last_valid_index()]
    price = price[df.index]
    scores = df.apply(pct_score)
    lp = np.log(price)
    targets = pd.DataFrame({
        "동행": lp.shift(-3) - lp.shift(3),
        "선행6": timing.fwd(price, 6),  # 발표한 달부터 (선행12와 같게)
        "선행12": timing.fwd(price),  # 발표한 달부터 (timing.PUB_OFFSET)
    })
    mom = (lp - lp.shift(3))  # 통제용 과거 3개월 가격 변화
    return scores, meta, targets, mom, price


def window_mask(idx, w):
    return (idx >= w[0]) & (idx <= w[1])


def evaluate(score: pd.Series, targets, mom):
    r = {}
    for wn, w in [("학습", TRAIN), ("검증", TEST), ("전체", FULL)]:
        m = window_mask(score.index, w)
        x = score[m].to_numpy()
        for tn in targets:
            r[f"{wn}_{tn}"] = spearman(x, targets[tn][m].to_numpy())
        r[f"{wn}_선행12_추가정보"] = partial_spearman(x, targets["선행12"][m].to_numpy(), mom[m].to_numpy())
    # 극단 구간: 점수 ≥70 vs ≤30 일 때 이후 12개월 수익률 차 (전체 기간)
    m = window_mask(score.index, FULL)
    s, y = score[m], targets["선행12"][m]
    hi, lo = y[s >= 70].mean(), y[s <= 30].mean()
    r["극단_탐욕후12개월"] = hi
    r["극단_공포후12개월"] = lo
    r["극단_스프레드"] = hi - lo
    r["커버리지시작"] = str(score.first_valid_index().date()) if score.first_valid_index() is not None else ""
    return r


def composite(scores, members):
    return scores[list(members)].mean(axis=1, skipna=True)


def build_candidates(scores, meta):
    """(분류방식, 그룹명, 지표목록) 후보 생성."""
    cands = []
    for ind in scores.columns:
        cands.append(("단일지표", ind, [ind]))
    for col in ["주제", "속도", "출처성격", "행위자", "시장"]:
        for g, sub in meta.groupby(col):
            cands.append((col, g, list(sub.index)))
    cands.append(("CNN복제", "CNN 7개 대응지표", list(meta.index[meta["CNN대응"] != ""])))
    cands.append(("사용자원안", "원안 전체(금리+공급+언급수)", list(meta.index[meta["사용자원안"] != ""])))
    for g, sub in meta[meta["사용자원안"] != ""].groupby("사용자원안"):
        cands.append(("사용자원안", g, list(sub.index)))
    cands.append(("전체", "31개 전체 동일가중", list(scores.columns)))
    cands.append(("전체", "가격 제외 전체", [c for c in scores.columns if meta.loc[c, "주제"] != "가격"]))
    # 데이터 기반: 학습기간 점수 상관으로 계층 군집
    tr = scores[window_mask(scores.index, TRAIN)]
    corr = tr.corr(min_periods=36).fillna(0).clip(-1, 1)
    dist = squareform((1 - corr.abs()).to_numpy(), checks=False)
    Z = linkage(dist, "average")
    for k in (4, 6, 8):
        lab = fcluster(Z, k, "maxclust")
        for c in sorted(set(lab)):
            mem = list(corr.index[lab == c])
            cands.append((f"상관군집{k}", f"군집{c}: " + ", ".join(m.split("_")[1] for m in mem[:4]) + ("…" if len(mem) > 4 else ""), mem))
    return cands, corr, Z


def scheme_indices(scores, meta, cands):
    """각 분류방식 전체를 하나의 지수로: 그룹별 평균 → 그룹 간 동일가중."""
    out = {}
    for scheme in ["주제", "속도", "출처성격", "행위자", "시장", "상관군집4", "상관군집6", "상관군집8"]:
        groups = [composite(scores, mem) for s, _, mem in cands if s == scheme]
        out[f"[2단계] {scheme} 그룹 균등"] = pd.concat(groups, axis=1).mean(axis=1, skipna=True)
    out["[1단계] 31개 지표 균등"] = composite(scores, scores.columns)
    return out


def theme_subset_search(scores, meta, targets, mom, key="선행12"):
    """주제 그룹(9개)의 모든 부분집합(511개)을 2단계 균등 지수로 평가."""
    themes = sorted(meta["주제"].unique())
    gs = {t: composite(scores, meta.index[meta["주제"] == t]) for t in themes}
    rows = []
    for k in range(1, len(themes) + 1):
        for combo in itertools.combinations(themes, k):
            s = pd.concat([gs[t] for t in combo], axis=1).mean(axis=1, skipna=True)
            r = evaluate(s, targets, mom)
            r["조합"] = " + ".join(combo)
            r["그룹수"] = k
            rows.append(r)
    return pd.DataFrame(rows)


def indicator_combo_search(scores, targets, max_k=4, key="선행12"):
    """지표 2~4개 조합 전수 탐색: 학습기간 IC로 고르고 검증기간에서 확인 (과최적화 점검)."""
    cols = list(scores.columns)
    S = scores.to_numpy()
    tr = window_mask(scores.index, TRAIN)
    te = window_mask(scores.index, TEST)
    y = targets[key].to_numpy()
    rows = []
    for k in range(2, max_k + 1):
        for combo in itertools.combinations(range(len(cols)), k):
            s = np.nanmean(S[:, combo], axis=1)
            rows.append((k, combo, spearman(s[tr], y[tr]), spearman(s[te], y[te])))
    df = pd.DataFrame(rows, columns=["k", "idx", "학습IC", "검증IC"])
    df["조합"] = df["idx"].apply(lambda t: " + ".join(cols[i] for i in t))
    return df.drop(columns="idx")


def turning_points(price, span=12, min_move=0.05):
    lp = np.log(price).rolling(3, center=True).mean()
    pts = []
    for i in range(span, len(lp) - span):
        w = lp.iloc[i - span: i + span + 1]
        if lp.iloc[i] == w.max():
            pts.append((lp.index[i], "고점"))
        elif lp.iloc[i] == w.min():
            pts.append((lp.index[i], "저점"))
    # 직전 전환점 대비 변동이 작으면 제거
    kept = []
    for d, t in pts:
        if kept and kept[-1][1] == t:
            if (t == "고점" and lp[d] > lp[kept[-1][0]]) or (t == "저점" and lp[d] < lp[kept[-1][0]]):
                kept[-1] = (d, t)
            continue
        if kept and abs(lp[d] - lp[kept[-1][0]]) < min_move:
            continue
        kept.append((d, t))
    return kept


def best_lag(score, price, lags=range(-6, 19)):
    """점수(t)와 '6개월 가격 변화(t+k-6 → t+k)'의 상관이 가장 큰 k = 점수가 시장을 몇 개월 앞서는지 (기준월 기준).
    발표한 달 기준으로 말하려면 timing.PUB_OFFSET을 뺀다 (기준월 t 점수는 t+1월에 발표)."""
    lp = np.log(price)
    d6 = lp - lp.shift(6)
    m = window_mask(score.index, FULL)
    x = score[m].to_numpy()
    ics = {k: spearman(x, d6.shift(-k)[m].to_numpy()) for k in lags}
    ics = {k: v for k, v in ics.items() if not np.isnan(v)}
    if not ics:
        return np.nan, np.nan
    k = max(ics, key=ics.get)
    return k, ics[k]


def main():
    scores, meta, targets, mom, price = load()
    cands, corr, Z = build_candidates(scores, meta)
    tps = turning_points(price)

    rows = []
    series = {}
    for scheme, name, mem in cands:
        s = composite(scores, mem)
        r = evaluate(s, targets, mom)
        r.update({"분류방식": scheme, "그룹": name, "지표수": len(mem), "지표": ", ".join(mem)})
        k, r["선행시차_IC"] = best_lag(s, price)
        r["선행시차_개월"] = k - timing.PUB_OFFSET  # 발표한 달 기준
        rows.append(r)
        series[f"{scheme}|{name}"] = s
    for name, s in scheme_indices(scores, meta, cands).items():
        r = evaluate(s, targets, mom)
        r.update({"분류방식": "분류방식 전체지수", "그룹": name, "지표수": 31, "지표": ""})
        k, r["선행시차_IC"] = best_lag(s, price)
        r["선행시차_개월"] = k - timing.PUB_OFFSET  # 발표한 달 기준
        rows.append(r)
        series[f"분류방식 전체지수|{name}"] = s
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "group_results.csv", index=False)

    subsets = theme_subset_search(scores, meta, targets, mom)
    subsets.to_csv(OUT / "theme_subsets.csv", index=False)
    combos = indicator_combo_search(scores, targets)
    combos.to_csv(OUT / "indicator_combos.csv", index=False)

    pd.DataFrame(series).assign(__price=price).to_csv(OUT / "group_series.csv")
    scores.to_csv(OUT / "indicator_scores.csv")
    targets.to_csv(OUT / "targets.csv")
    corr.to_csv(OUT / "train_score_corr.csv")
    json.dump([(str(d.date()), t) for d, t in tps], open(OUT / "turning_points.json", "w"), ensure_ascii=False)
    print("candidates:", len(res), "theme subsets:", len(subsets), "indicator combos:", len(combos))
    print("turning points:", [(str(d.date()), t) for d, t in tps])


if __name__ == "__main__":
    main()

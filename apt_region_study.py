"""단지 검색 점수의 지역별 고정값 고르기와 검증 (2026-10) → data/apt_params.json (apt_score.py·sim_build.py가 읽음).

서울 고정값(층 효과표·면적 탄력성)은 apt_study.py로 서울 실거래에서 정했다. 지방은 층·평형에 따른 가격 차가 다를 수 있어서
지역마다 같은 방법으로 다시 재고, 결과를 보기 전에 정한 규칙으로 고른다:
- 층 효과표: 2018년까지 거래로 잰 그 지역 표와 서울 표 중 2019년 이후 거래(같은 단지·평형·반기 안 가격 차)를 더 잘 설명하는 쪽.
  그 지역 표가 이기면 전체 기간으로 다시 잰 값을 쓴다.
- 면적 탄력성: 2020년까지로 잰 그 지역 값과 서울 값 중 2021년 이후 거래(같은 단지·반기 안 평형 간 가격 차)를 더 잘 설명하는 쪽.
- 검증 (화면 설명용): 고른 값으로 2014년 1월~2026년 3월 거래마다 점수를 매기고, 6개월 안 같은 평형 다음 거래(최대 3건)가
  시장·층·평형을 맞춘 뒤 얼마나 높았는지 평균 (80점 이상 / 20점 이하). apt_study.py [3]의 '같은 평형 5건 미만이면 채움' 방식.

한 번 고른 값은 고정이다 (서울 고정값처럼). 새 지역이 지역 저장소에 들어오면 월간 갱신·화면 배포가 --missing으로 그 지역만 고른다.

사용: python apt_region_study.py [지역id ...]   (없으면 저장소의 모든 지역을 다시)
      python apt_region_study.py --missing      (아직 고르지 않은 지역만)
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import apt_score as A
import region_store
from apt_study import REF, codes, demean, fit_floor
from regions import REGIONS

ROOT = Path(__file__).parent
DAY = np.timedelta64(1, "D")
SEOUL_BETA = np.delete(A.FLOOR_EFF, REF)


def load(rid):
    df = A.store(rid)
    df = df[(df.cdealType == "") & (df.dealingGbn != "직거래")].copy()
    df["price"] = pd.to_numeric(df.dealAmount.str.replace(",", ""), errors="coerce")
    df["area"] = pd.to_numeric(df.excluUseAr, errors="coerce")
    df["floor"] = pd.to_numeric(df["floor"], errors="coerce")
    df = df[(df.price > 0) & (df.area > 0) & df.floor.notna()].copy()
    df["month"] = pd.to_datetime(dict(year=df.dealYear.astype(int), month=df.dealMonth.astype(int), day=1))
    df["date"] = df.month + pd.to_timedelta(pd.to_numeric(df.dealDay, errors="coerce").fillna(15) - 1, unit="D")
    df["type"] = df.area.round(0)
    mk = A.gu_market(rid)
    df["mk"] = mk.stack().reindex(pd.MultiIndex.from_arrays([df.month, df.lawd])).to_numpy()
    df = df[df.mk.notna()].sort_values(["aptSeq", "date", "price"], kind="mergesort").reset_index(drop=True)
    df["y"] = np.log(df.price) - df.mk
    df["half"] = df.month.dt.year.astype(str) + np.where(df.month.dt.month <= 6, "a", "b")
    df["la"] = np.log(df.area)
    return df


def r2(beta, Xd, yd):
    return 1 - np.var(yd - Xd @ beta) / np.var(yd)


def pick_floor(df):
    tr, te = df[df.month < "2019-01-01"], df[df.month >= "2019-01-01"]
    own, _ = fit_floor(tr, False)
    _, (Xd, yd) = fit_floor(te, False)
    r_own, r_seoul = r2(own, Xd, yd), r2(SEOUL_BETA, Xd, yd)
    use = "own" if r_own > r_seoul else "seoul"
    beta = fit_floor(df, False)[0] if use == "own" else SEOUL_BETA
    return np.insert(beta, REF, 0.0), {"r2_own": round(r_own * 100, 2), "r2_seoul": round(r_seoul * 100, 2), "use": use}


def pick_b(df):
    trn = (df.month < "2021-01-01").to_numpy()
    yf, la = df.yf.to_numpy(), df.la.to_numpy()
    g = codes(df.aptSeq.to_numpy()[trn], df.half.to_numpy()[trn])
    xd, yd = demean(la[trn], g), demean(yf[trn], g)
    own = float(xd @ yd / (xd @ xd))
    g2 = codes(df.aptSeq.to_numpy()[~trn], df.half.to_numpy()[~trn])
    xt, yt = demean(la[~trn], g2), demean(yf[~trn], g2)
    err = {b: float(np.mean((yt - b * xt) ** 2)) for b in (own, A.B)}
    use = "own" if err[own] < err[A.B] else "seoul"
    return (own if use == "own" else A.B), {"own": round(own, 4), "seoul": A.B, "use": use}


def check(df, b):
    """2014-01~2026-03 거래마다 점수(같은 평형 5건 미만이면 다른 평형으로 채움, 스토캐스틱)를 매기고 6개월 안 같은 평형 다음 거래와 비교."""
    dev = A.type_dev(df, b).reindex(pd.MultiIndex.from_arrays([df.aptSeq, df.type])).fillna(0).to_numpy()
    base = df.yf.to_numpy() - b * df.la.to_numpy() - dev
    seq, dates, typ = df.aptSeq.to_numpy(), df.date.to_numpy(), df.type.to_numpy()
    bounds = np.flatnonzero(np.r_[True, seq[1:] != seq[:-1], True])
    t14, t26 = np.datetime64("2014-01-01"), np.datetime64("2026-04-01")
    res = []
    for a, e in zip(bounds[:-1], bounds[1:]):
        t = dates[a:e]
        if t[-1] < t14:
            continue
        for i in range(a, e):
            if dates[i] < t14 or dates[i] >= t26:
                continue
            js = np.arange(i + 1, a + np.searchsorted(t, dates[i] + 183 * DAY, side="right"))
            js = js[typ[js] == typ[i]][:3]
            if not len(js):
                continue
            lo = a + np.searchsorted(t, dates[i] - 730 * DAY, side="left")
            idx = np.arange(lo, i + 1)
            same_m = typ[idx] == typ[i]
            same, oth = idx[same_m][-10:], idx[~same_m]
            pool = same if len(same) >= 5 else np.sort(np.r_[same, oth[-(10 - len(same)):]])
            if len(pool) < 5:
                continue
            v = base[pool]
            lo_, hi_ = v.min(), v.max()
            k = 50.0 if hi_ - lo_ < 1e-9 else (base[i] - lo_) / (hi_ - lo_) * 100
            res.append((k, np.median(base[js]) - base[i]))
    r = np.array(res)
    hi, lo = r[r[:, 0] >= 80, 1], r[r[:, 0] <= 20, 1]
    return {"n": int(len(r)), "ic": round(float(spearmanr(r[:, 0], r[:, 1])[0]), 3),
            "after_high": round(float(hi.mean()) * 100, 1), "after_low": round(float(lo.mean()) * 100, 1),
            "n_high": int(len(hi)), "n_low": int(len(lo))}


def study(rid):
    t0 = time.time()
    df = load(rid)
    ftab, fl = pick_floor(df)
    df["ff"] = A.floor_eff(df.floor.to_numpy(), ftab)
    df["yf"] = df.y - df.ff
    b, bl = pick_b(df)
    ck = check(df, b)
    ck["from"], ck["to"] = "2014-01", "2026-03"
    print(f"{REGIONS[rid]['name']}: 거래 {len(df):,} · 층 2019~ 설명력 자기 {fl['r2_own']}% / 서울 {fl['r2_seoul']}% → {fl['use']} · "
          f"면적 탄력성 자기 {bl['own']} / 서울 {bl['seoul']} → {bl['use']} · 검증 {ck['n']:,}건 상관 {ck['ic']} · "
          f"80점↑ 뒤 {ck['after_high']:+.1f}% · 20점↓ 뒤 {ck['after_low']:+.1f}% · {time.time() - t0:.0f}s", flush=True)
    return {"B": round(float(b), 4), "floor": [round(float(x), 4) for x in ftab], "floor_pick": fl, "B_pick": bl, "check": ck,
            "studied": time.strftime("%Y-%m-%d")}


if __name__ == "__main__":
    p = ROOT / "data" / "apt_params.json"
    out = json.loads(p.read_text()) if p.exists() else {}
    args = sys.argv[1:]
    todo = ([r for r in region_store.regions_in_store() if r not in out] if args == ["--missing"]
            else args or region_store.regions_in_store())
    for rid in todo:
        out[rid] = study(rid)
    if todo:
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("단지 점수 지역 고정값:", ", ".join(REGIONS[r]["name"] for r in todo) or "새 지역 없음", flush=True)

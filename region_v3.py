"""수도권·광역시 지수와 검증 (region_index.py 결과 위에) → results_region/region_v3.pkl

엔진: data/region_engine.json이 있으면 그 고정 엔진(region_engine_study.py가 7개 지역으로 고른 것), 없으면 서울과 같은 v3.
공개 기준 (결과를 보기 전에 2026-10-20에 정함): 정확도(지수와 이후 12개월 그 지역 실거래 가격의 순위상관) 0.40 이상,
5년 구간(1년씩 밀며) 중앙값 0.25 이상. 고정 엔진을 쓸 때는 이 기준을 지역 교차검증 성적(그 지역을 빼고 고른 엔진의 성적)에 적용한다.
- 시작 달: 쓸 수 있는 표가 처음으로 가장 많을 때의 90% 이상이 된 달 (서울 공식 기록 2011년 2월과 같은 규칙). 그 전은 참고용.
비교용(공개 판단에는 안 씀): 서울 지수를 그 지역에 그대로 쓴 경우, KB 매수우위지수 하나, 실거래 6개월 변화(2개월 늦춤).
(2026-10-20 15:40에 적어 둔 '대안 B: 가격부담 3표 빼기' 비교는 사용자 요청으로 엔진 여러 개를 비교하는 region_engine_study.py로 바뀜.
 대안 B는 그 후보 중 '가격부담 빼기'로 들어 있다.)
"""
import json

import numpy as np
import pandas as pd

import backtest as bt
import timing
import v3
from regions import REGIONS

PASS_ACC, PASS_WIN = 0.40, 0.25
R = pd.read_pickle(bt.ROOT / "results_region" / "region_calc.pkl")
meta, aux_meta = v3.load_meta()
seoul = pd.read_pickle(bt.ROOT / "results_v2" / "v3_seoul.pkl")
EP = bt.ROOT / "data" / "region_engine.json"
ENGINE = json.loads(EP.read_text()) if EP.exists() else None
SP = bt.ROOT / "results_region" / "engine_study.json"
FIXED_LORO = json.loads(SP.read_text()).get("fixed_loro", {}) if SP.exists() else {}


def compute(ind):
    """고정 엔진(없으면 서울 v3)으로 지수. 화면용 속도 3그룹·주제 점수도 같은 표로 다시 만든다."""
    if ENGINE is None:
        return v3.compute(ind, meta, aux_meta)
    bt.WINDOW = ENGINE["window"]
    try:
        r = v3.compute(ind, meta, aux_meta)
    finally:
        bt.WINDOW = 120
    V, M = r["votes"], r["vote_meta"]
    keep = M.index[~M["주제"].isin(ENGINE["drop"])]
    V, M = V[keep], M.loc[keep]
    if ENGINE.get("weights"):
        w = pd.Series(ENGINE["weights"]).reindex(keep).fillna(0)
        core = (V * w).sum(axis=1, min_count=1) / V.notna().mul(w).sum(axis=1).replace(0, np.nan)
    elif ENGINE["agg"] == "flat":
        core = V.mean(axis=1)
    else:
        key = "속도" if ENGINE["agg"] == "speed" else "주제"
        core = pd.concat([V[M.index[M[key] == g]].mean(axis=1) for g in M[key].unique()], axis=1).mean(axis=1)
    k = v3.K_REGION  # 고정 엔진의 눈금 (서울 1.5배와 같은 기준으로 정한 배율, v3.py)
    r.update({"core": core, "final": v3.spread(core, k), "votes": V, "vote_meta": M, "n_votes_available": V.notna().sum(axis=1),
              "groups": {g: v3.spread(V[M.index[M["속도"] == g]].mean(axis=1), 1.0) for g in v3.SPEED},  # 그룹·주제는 넓히지 않음 (v3.compute와 같게)
              "themes": {t: v3.spread(V[M.index[M["주제"] == t]].mean(axis=1), 1.0) for t in M["주제"].unique()}})
    return r


def start_month(n_votes):
    full = n_votes >= 0.9 * n_votes.max()
    ok = full[full].index
    return ok[0] if len(ok) else None


def acc(s, y, m):
    return bt.spearman(s[m].to_numpy(), y[m].to_numpy())


def windows(s, y, start):
    """5년 구간 순위상관 (1년씩 밀며, 이후 12개월 가격이 다 나온 구간만)."""
    last = y.last_valid_index()
    out = {}
    for yr in range(start.year, last.year - 3):
        a, b = pd.Timestamp(yr, 1, 1), pd.Timestamp(yr + 4, 12, 1)
        if b > last:
            break
        m = (s.index >= max(a, start)) & (s.index <= b)
        out[yr] = acc(s, y, m)
    return out


print("엔진:", ENGINE["name"] + f" (고정 {ENGINE['chosen']})" if ENGINE else "서울과 같은 v3 (고정 엔진 없음)")

res = {}
for rid, o in R["regions"].items():
    r = compute(o["ind"])
    idx = o["ind"].index
    f, y = r["final"].reindex(idx), o["fwd12"]
    st = start_month(r["n_votes_available"])
    m = idx >= st
    win = windows(f, y, st)
    kb_buy = o["ind"]["설문_매수우위"]
    rs6 = timing.trade_lag(np.log(o["rs"]).diff(6))  # 발표할 때 신고가 다 찬 달까지 (기준월 t 발표 = t+1월 20일)
    r.update({"rs": o["rs"], "fwd12": y, "pairs": o["pairs"], "n_trades": o["n_trades"], "start": st,
              "acc": acc(f, y, m), "acc_seoul": acc(seoul["final"].reindex(idx), y, m), "acc_kb": acc(kb_buy, y, m),
              "acc_rs6": acc(rs6, y, m), "win": win})
    wv = [v for v in win.values() if not np.isnan(v)]
    r["win_median"], r["win_min"] = (float(np.median(wv)), float(np.min(wv))) if wv else (np.nan, np.nan)
    # 고정 엔진: 공개 여부는 고정할 때의 교차검증 성적으로 정한 그대로. 화면의 숫자는 지금 정답(발표한 달부터)으로 다시 잰 값
    # (region_engine_study.py의 fixed_loro: 그 지역만 빼고 비중을 배운 고정 엔진), 없으면 고정할 때의 값
    lo = FIXED_LORO.get(rid) or (ENGINE or {}).get("loro", {}).get(rid)
    if ENGINE:  # 고정 엔진: 교차검증 성적으로 공개 판단 (엔진을 고를 때 없던 지역은 공개하지 않음)
        r["loro"] = lo
        r["publish"] = bool(ENGINE["publish"].get(rid, False))
    else:
        r["publish"] = bool(r["acc"] >= PASS_ACC and r["win_median"] >= PASS_WIN)
    res[rid] = r
    print(f"{REGIONS[rid]['name']}: 현재 {f.dropna().iloc[-1]:.1f} · 시작 {st.date()} · 정확도 {r['acc']:.2f} "
          f"(서울 지수 {r['acc_seoul']:.2f}, KB 매수우위 {r['acc_kb']:.2f}, 실거래 6개월 {r['acc_rs6']:.2f}) · "
          f"5년 구간 중앙 {r['win_median']:.2f} 최저 {r['win_min']:.2f} ({len(wv)}개) → {'공개' if r['publish'] else '검증 중'}")

subs = {}
for lawd, o in R["subs"].items():
    r = compute(o["ind"])
    idx = o["ind"].index
    f = r["final"].reindex(idx)
    reg = res[o["region"]]
    st, rf = reg["start"], reg["final"].reindex(idx)
    a = {"sub": np.nan, "region": np.nan, "seoul": np.nan}
    if o["fwd12"] is not None:
        y, m = o["fwd12"], idx >= st
        a = {"sub": acc(f, y, m), "region": acc(rf, y, m), "seoul": acc(seoul["final"].reindex(idx), y, m)}
    r.update({"region": o["region"], "rs": o["rs"], "fwd12": o["fwd12"], "own": o["own"], "n_trades": o["n_trades"], "acc3": a,
              "n_own": len([c for c in o["own"] if c in meta.index])})
    subs[lawd] = r
for rid in res:
    A = pd.DataFrame({l: subs[l]["acc3"] for l in REGIONS[rid]["lawd"] if l in subs}).T
    print(f"  {REGIONS[rid]['name']} 시군구 {len(A)}곳 평균 정확도: 시군구 지수 {A['sub'].mean():.2f} · 시도 지수 {A['region'].mean():.2f} · "
          f"서울 지수 {A['seoul'].mean():.2f}")
pd.to_pickle({"regions": res, "subs": subs, "engine": ENGINE}, bt.ROOT / "results_region" / "region_v3.pkl")

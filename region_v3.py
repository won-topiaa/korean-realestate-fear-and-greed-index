"""수도권·광역시 v3 지수와 검증 (region_index.py 결과 위에 서울과 같은 v3 엔진) → results_region/region_v3.pkl

공개 기준 (결과를 보기 전에 2026-10-20에 정함):
- 시작 달: 쓸 수 있는 표가 처음으로 가장 많을 때의 90% 이상이 된 달 (서울 공식 기록 2011년 2월과 같은 규칙). 그 전은 참고용.
- 정확도: 시작 달 이후 지수와 이후 12개월 그 지역 실거래 가격 변화의 순위상관이 0.40 이상이고,
  5년 구간(1년씩 밀며)의 중앙값이 0.25 이상이면 공개. 못 미치면 지도에는 '검증 중'으로만 보인다.
비교용(공개 판단에는 안 씀): 서울 지수를 그 지역에 그대로 쓴 경우, KB 매수우위지수 하나, 실거래 6개월 변화(2개월 늦춤).

대안 B (2026-10-20 15:40, 광주·대전 결과만 보고 정함. 대구·울산·인천·부산·경기는 아직 계산 전 = 검증용):
- 광주·대전에서는 서울과 달리 '가격부담' 3표(PIR, 주택구매력, 전세가율)가 이후 가격과 반대로 움직였다
  (광주 -0.44·-0.38·0.01, 대전 -0.03·-0.51·-0.09. 서울은 0.00·0.23·0.38). 그래서 서울 밖 지역은 이 3표를 뺀 22표로 계산해 본다.
- 채택 규칙: 검증용 5개 지역에서 B의 정확도 중앙값이 기본(A)보다 높고, 공개 기준을 넘는 지역 수가 A 이상이면 서울 밖 모든 지역에 B를 쓴다.
  아니면 A를 쓴다. 광주·대전의 B 성적은 설계에 쓴 자료라 낙관적이다. 다른 대안은 시험하지 않는다.
"""
import numpy as np
import pandas as pd

import backtest as bt
import v3
from regions import REGIONS

PASS_ACC, PASS_WIN = 0.40, 0.25
DESIGN = ["gwangju", "daejeon"]  # 대안 B를 정할 때 본 지역 (나머지는 검증용)
R = pd.read_pickle(bt.ROOT / "results_region" / "region_calc.pkl")
meta, aux_meta = v3.load_meta()
meta_b = meta[meta["주제"] != "가격부담"]  # 대안 B: 가격부담 3표(PIR·구매력·전세가율) 제외
seoul = pd.read_pickle(bt.ROOT / "results_v2" / "v3_seoul.pkl")


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


def evaluate(o, mt):
    r = v3.compute(o["ind"], mt, aux_meta)
    idx = o["ind"].index
    f, y = r["final"].reindex(idx), o["fwd12"]
    st = start_month(r["n_votes_available"])
    m = idx >= st
    wv = [v for v in windows(f, y, st).values() if not np.isnan(v)]
    a, med = acc(f, y, m), (float(np.median(wv)) if wv else np.nan)
    return r, {"acc": a, "win_median": med, "pass": bool(a >= PASS_ACC and med >= PASS_WIN)}


# 대안 비교 (검증용 지역이 다 들어왔을 때만 채택을 판단)
cmp = {rid: {"A": evaluate(o, meta)[1], "B": evaluate(o, meta_b)[1]} for rid, o in R["regions"].items()}
hold = [r for r in cmp if r not in DESIGN]
complete = set(hold) == set(REGIONS) - set(DESIGN)
if complete:
    med = {k: float(np.median([cmp[r][k]["acc"] for r in hold])) for k in "AB"}
    npass = {k: sum(cmp[r][k]["pass"] for r in hold) for k in "AB"}
    VARIANT = "B" if med["B"] > med["A"] and npass["B"] >= npass["A"] else "A"
    print(f"대안 비교 (검증용 {len(hold)}곳): 정확도 중앙값 A {med['A']:.2f} · B {med['B']:.2f}, 기준 통과 A {npass['A']} · B {npass['B']} → {VARIANT}")
else:
    VARIANT = "A"  # 검증용 지역이 다 모이기 전에는 기본 엔진
    print(f"대안 비교 보류: 검증용 {len(hold)}/{len(set(REGIONS) - set(DESIGN))}곳만 계산됨 → 기본(A)")
for rid, c in cmp.items():
    print(f"  {REGIONS[rid]['name']}{' (설계용)' if rid in DESIGN else ''}: A {c['A']['acc']:.2f}/{c['A']['win_median']:.2f}{' 통과' if c['A']['pass'] else ''} · "
          f"B {c['B']['acc']:.2f}/{c['B']['win_median']:.2f}{' 통과' if c['B']['pass'] else ''}")
META = meta_b if VARIANT == "B" else meta

res = {}
for rid, o in R["regions"].items():
    r = v3.compute(o["ind"], META, aux_meta)
    idx = o["ind"].index
    f, y = r["final"].reindex(idx), o["fwd12"]
    st = start_month(r["n_votes_available"])
    m = idx >= st
    win = windows(f, y, st)
    kb_buy = o["ind"]["설문_매수우위"]
    rs6 = (np.log(o["rs"]).diff(6)).shift(2)
    r.update({"rs": o["rs"], "fwd12": y, "pairs": o["pairs"], "n_trades": o["n_trades"], "start": st,
              "acc": acc(f, y, m), "acc_seoul": acc(seoul["final"].reindex(idx), y, m), "acc_kb": acc(kb_buy, y, m),
              "acc_rs6": acc(rs6, y, m), "win": win})
    wv = [v for v in win.values() if not np.isnan(v)]
    r["win_median"], r["win_min"] = (float(np.median(wv)), float(np.min(wv))) if wv else (np.nan, np.nan)
    r["publish"] = bool(r["acc"] >= PASS_ACC and r["win_median"] >= PASS_WIN)
    res[rid] = r
    print(f"{REGIONS[rid]['name']}: 현재 {f.dropna().iloc[-1]:.1f} · 시작 {st.date()} · 정확도 {r['acc']:.2f} "
          f"(서울 지수 {r['acc_seoul']:.2f}, KB 매수우위 {r['acc_kb']:.2f}, 실거래 6개월 {r['acc_rs6']:.2f}) · "
          f"5년 구간 중앙 {r['win_median']:.2f} 최저 {r['win_min']:.2f} ({len(wv)}개) → {'공개' if r['publish'] else '검증 중'}")

subs = {}
for lawd, o in R["subs"].items():
    r = v3.compute(o["ind"], META, aux_meta)
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
pd.to_pickle({"regions": res, "subs": subs, "variant": VARIANT, "compare": cmp}, bt.ROOT / "results_region" / "region_v3.pkl")

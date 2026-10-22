"""수도권·광역시 엔진 고르기: 엔진 후보 여러 개를 같은 자료로 돌려 보고, 한 지역씩 빼고 고른 엔진의 성적으로 판단한다.

후보 (정한 날 2026-10-20, 광주·대전·울산 결과를 본 뒤라 그 지역 성적은 낙관적일 수 있음):
- 표 묶음 7가지: 전부(서울과 같음) / 가격부담 빼기 / 가격부담·금융시장 빼기 / 가격부담·관심 빼기 /
  가격부담·금융시장·관심 빼기 / 시장 안 자료만(가격·수급심리·전세·거래·공급) / 설문만(수급심리·전세)
- 합치는 방법 3가지: 속도 3그룹 같은 비중(서울과 같음) / 표마다 같은 비중 / 주제마다 같은 비중
- 점수화 기간 2가지: 120개월(서울과 같음) / 60개월
- 자료로 비중 정하기 2가지: 학습 지역에서 이후 가격과 맞은 정도(순위상관, 음수는 0)로 표 비중 (120·60개월)
→ 44개 엔진. 지표의 부호(높을수록 탐욕)는 바꾸지 않는다 (온도계의 뜻이 바뀌므로).

성적: 2011년 2월 이후 지수와 이후 12개월 그 지역 실거래 가격의 순위상관(정확도), 5년 구간(1년씩 밀며) 순위상관의 중앙값(안정성),
2019년 이후 순위상관(최근). 목표 = 세 값의 평균.
고르는 규칙 (2026-10-20 17:30, 광주·대전·울산·대구만 본 상태에서 정함. 인천·부산·경기는 아직 계산 전):
- 7개 지역의 목표 평균이 가장 높은 엔진 하나를 서울 밖 모든 지역에 쓴다 (지역마다 다른 엔진은 쓰지 않음).
- '자료로 비중' 엔진은 평가하는 지역을 빼고 배운 비중으로 잰다 (자기 지역 성적으로 비중을 정하는 이득을 없앰).
- 그 규칙 자체의 성적은 한 지역씩 빼고 고른 엔진을 뺀 지역에 써서 잰다 (지역 교차검증). 공개는 이 교차검증 성적이
  처음 정한 기준(정확도 0.40 이상, 5년 구간 중앙값 0.25 이상)을 넘는 지역만.
- 서울은 학습에 쓰지 않고 마지막 점검용 (서울 엔진은 그대로 둔다). 2011~2017년(정답이 2019년 전에 끝나는 달)으로 고르고 2019년~에서 재는 기간 검증도 함께 본다.
결과: results_region/engine_study.json, data/region_engine.json (region_v3.py가 쓰는 고정 엔진).
- 임시 엔진 (2026-10-20, 사용자 요청): 부산·경기 실거래가 다 들어오기 전에 있는 지역(5곳)으로 같은 규칙으로 골라 먼저 쓴다 (--provisional).
- 7개 지역이 다 모이면: 임시 엔진을 그대로 새 지역(고를 때 안 본 부산·경기)에 써 본 성적을 남기고, 7개 지역으로 다시 골라 최종으로 고정한다.
- 최종 엔진은 한 번만 만든다 (매달 다시 고르면 기준이 계속 바뀌므로). 다시 고르려면 --refit.
엔진을 새로 정할 때 results_region/engine_new.md에 요약을 남긴다 (월간 갱신이 이슈로 알림).
"""
import sys
import json

import numpy as np
import pandas as pd

import backtest as bt
import region_supply as RS
import timing
import v3

OFF = pd.Timestamp("2011-02-01")
SPLIT = pd.Timestamp("2019-01-01")
R = pd.read_pickle(bt.ROOT / "results_region" / "region_calc.pkl")["regions"]
meta_all, _ = v3.load_meta()
THEMES = {
    "전부": [],
    "가격부담 빼기": ["가격부담"],
    "가격부담·금융시장 빼기": ["가격부담", "금융시장"],
    "가격부담·관심 빼기": ["가격부담", "관심"],
    "가격부담·금융시장·관심 빼기": ["가격부담", "금융시장", "관심"],
    "시장 안 자료만": ["가격부담", "금융시장", "관심", "자금"],
    "설문만": ["가격부담", "금융시장", "관심", "자금", "가격", "거래", "공급"],
}
AGG = {"속도 3그룹": "speed", "표마다 같게": "flat", "주제마다 같게": "theme"}
WINS = [120, 60]


def seoul_frame():
    raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
    raw = raw[raw.index <= raw["__price"].last_valid_index()]
    rs = pd.read_csv(bt.ROOT / "data" / "targets_extra.csv", index_col=0, parse_dates=True)["실거래지수"].reindex(raw.index)
    return {"ind": raw, "fwd12": timing.fwd(rs)}


DATA = {rid: {"ind": o["ind"], "fwd12": o["fwd12"]} for rid, o in R.items()}
SEOUL = seoul_frame()


def votes(o, window):
    """지역 하나의 표 점수 (점수화 기간별로 한 번만 계산)."""
    bt.WINDOW = window
    try:
        sc = v3.scores(o["ind"][[c for c in meta_all.index if c in o["ind"].columns]])
    finally:
        bt.WINDOW = 120
    return v3.votes(sc, meta_all)


CACHE = {}


def V(name, window):
    key = (name, window)
    if key not in CACHE:
        CACHE[key] = votes(SEOUL if name == "seoul" else DATA[name], window)
    return CACHE[key]


def core(vt, vm, drop, agg, w=None):
    keep = vm.index[~vm["주제"].isin(drop)]
    vt, vm = vt[keep], vm.loc[keep]
    if w is not None:
        ww = pd.Series(w).reindex(keep).fillna(0)
        return (vt * ww).sum(axis=1, min_count=1) / vt.notna().mul(ww).sum(axis=1).replace(0, np.nan)
    if agg == "flat":
        return vt.mean(axis=1)
    key = "속도" if agg == "speed" else "주제"
    return pd.concat([vt[vm.index[vm[key] == g]].mean(axis=1) for g in vm[key].unique()], axis=1).mean(axis=1)


def score(s, y, a=OFF, b=None):
    """정확도·5년 구간 중앙값·최저·목표."""
    idx = s.index
    m = (idx >= a) & (idx < b if b is not None else True)
    ic = bt.spearman(s[m].to_numpy(), y.reindex(idx)[m].to_numpy())
    last = y.last_valid_index() if b is None else min(y.last_valid_index(), b - pd.DateOffset(months=1))
    win = []
    for yr in range(a.year, last.year - 3):
        lo, hi = max(pd.Timestamp(yr, 1, 1), a), pd.Timestamp(yr + 4, 12, 1)
        if hi > last:
            break
        mm = (idx >= lo) & (idx <= hi)
        win.append(bt.spearman(s[mm].to_numpy(), y.reindex(idx)[mm].to_numpy()))
    win = [x for x in win if not np.isnan(x)]
    med = float(np.median(win)) if win else np.nan
    late = np.nan
    if b is None:
        ml = idx >= SPLIT
        late = bt.spearman(s[ml].to_numpy(), y.reindex(idx)[ml].to_numpy())
    return {"acc": ic, "win_median": med, "win_min": float(np.min(win)) if win else np.nan, "recent": late,
            "obj": np.nanmean([ic, med, late])}


def ic_weights(train, window, b=None):
    """학습 지역에서 표마다 이후 가격과의 순위상관 평균 (음수는 0) → 비중."""
    out = {}
    for name in train:
        vt, _ = V(name, window)
        y = (SEOUL if name == "seoul" else DATA[name])["fwd12"].reindex(vt.index)
        m = (vt.index >= OFF) & (vt.index < b if b is not None else True)
        for c in vt.columns:
            out.setdefault(c, []).append(bt.spearman(vt[c][m].to_numpy(), y[m].to_numpy()))
    return {c: max(0.0, float(np.nanmean(v))) for c, v in out.items()}


CONFIGS = [{"name": f"{t} · {a} · {w}개월", "drop": d, "agg": ag, "window": w} for t, d in THEMES.items() for a, ag in AGG.items() for w in WINS]
CONFIGS += [{"name": f"자료로 비중 · {w}개월", "drop": [], "agg": "flat", "window": w, "learn": True} for w in WINS]


def run(cfg, name, train, a=OFF, b=None, wb=None):
    """wb: 비중을 배울 때 쓰는 마지막 달 (없으면 b — 평가 기간과 같게). cfg에 extra(공급 보정)가 있으면 그 지역은 공급 표를 더해 잰다."""
    vt, vm = V(name, cfg["window"])
    w = ic_weights([n for n in train if n != name], cfg["window"], wb if wb is not None else b) if cfg.get("learn") else None  # 평가 지역은 비중 학습에서 뺀다
    if w is not None and name in (cfg.get("extra") or {}) and not cfg["drop"]:
        s = RS.combine(vt, w, DATA[name]["ind"], name, cfg["extra"])
    else:
        s = core(vt, vm, cfg["drop"], cfg["agg"], w)
    return score(s, (SEOUL if name == "seoul" else DATA[name])["fwd12"], a, b)


def run_fixed(eng, name):
    """고정 엔진(배운 비중 그대로)을 한 지역에 쓴 성적 — 엔진을 고를 때 안 본 지역의 시험용."""
    vt, vm = V(name, eng["window"])
    if eng.get("weights") and name in (eng.get("extra") or {}) and not eng["drop"]:
        s = RS.combine(vt, eng["weights"], DATA[name]["ind"], name, eng["extra"])
    else:
        s = core(vt, vm, eng["drop"], eng["agg"], eng.get("weights"))
    return score(s, (SEOUL if name == "seoul" else DATA[name])["fwd12"])


def best(train, a=OFF, b=None):
    """학습 지역의 목표 평균이 가장 높은 엔진. 목표를 못 잰 지역이 있는 엔진은 고르지 않고, 같으면 먼저 적힌 후보."""
    res = []
    for i, c in enumerate(CONFIGS):
        objs = [run(c, n, train, a, b)["obj"] for n in train]
        res.append((float(np.mean(objs)) if np.all(np.isfinite(objs)) else -np.inf, -i))
    obj, i = max(res)
    return CONFIGS[-i], obj


def dump(obj, path):
    """중간에 끊겨도 반쯤 쓴 파일이 남지 않게 (임시 파일에 쓰고 바꿔 넣음)."""
    tmp = path.with_name(path.name + ".tmp")
    json.dump(obj, open(tmp, "w"), ensure_ascii=False, indent=1, default=float)
    tmp.replace(path)


if __name__ == "__main__":
    regions = list(DATA)
    base = CONFIGS[0]
    print(f"지역 {len(regions)}곳: {regions} · 엔진 {len(CONFIGS)}개")
    full = {c["name"]: {n: run(c, n, regions) for n in regions} for c in CONFIGS}
    tab = pd.DataFrame({k: {n: v[n]["obj"] for n in regions} for k, v in full.items()}).T
    tab["평균"] = tab.mean(axis=1)
    print("\n[모든 지역으로 잰 성적 상위 10 (낙관적)]")
    print(tab.sort_values("평균", ascending=False).head(10).round(2).to_string())
    print("기본(서울과 같은 엔진):", tab.loc[base["name"]].round(2).to_dict())

    loro = {}
    for h in regions:
        cfg, _ = best([n for n in regions if n != h])
        loro[h] = {"engine": cfg["name"], **run(cfg, h, [n for n in regions if n != h]), "base": run(base, h, regions)}
    print("\n[지역 교차검증: 그 지역을 빼고 고른 엔진의 그 지역 성적]")
    for h, r in loro.items():
        print(f"  {h}: {r['engine']} → 정확도 {r['acc']:.2f}, 5년 중앙 {r['win_median']:.2f}, 최저 {r['win_min']:.2f}, 2019~ {r['recent']:.2f} "
              f"| 기본 {r['base']['acc']:.2f}/{r['base']['win_median']:.2f}")
    print(f"  평균 목표: 고른 엔진 {np.mean([r['obj'] for r in loro.values()]):.3f} · 기본 {np.mean([r['base']['obj'] for r in loro.values()]):.3f}")

    # 정답(발표한 달부터 12개월)이 2019년 전에 끝나는 달까지만 고르고 배운다: 기준월 t의 정답은 t+13월 가격까지 씀
    # (예전엔 12개월만 빼서 2017년 12월의 정답이 2019년 1월 가격까지 갔음)
    TRAIN_END = SPLIT - pd.DateOffset(months=12 + timing.PUB_OFFSET)
    cfg_t, _ = best(regions, OFF, TRAIN_END)
    per = {n: {"pick": run(cfg_t, n, regions, SPLIT, wb=TRAIN_END), "base": run(base, n, regions, SPLIT)} for n in regions}
    print(f"\n[기간 검증: 2011~2017년(이후 12개월이 2019년 전에 끝나는 달)으로 고른 엔진 = {cfg_t['name']} · 2019년~ 정확도]")
    print("  ", {n: f"{p['pick']['acc']:.2f} (기본 {p['base']['acc']:.2f})" for n, p in per.items()})

    final, obj = best(regions)
    sr = run(final, "seoul", regions)
    from regions import REGIONS
    EP = bt.ROOT / "data" / "region_engine.json"
    old = json.loads(EP.read_text()) if EP.exists() else None
    complete = set(regions) == set(REGIONS)
    provisional = "--provisional" in sys.argv and not complete and old is None  # 임시 엔진은 한 번만: 다시 고르면 새 지역이 '안 본 지역'이 아니게 됨
    final_fit = complete and (old is None or old.get("provisional") or "--refit" in sys.argv)  # 7개 지역: 임시 엔진이면 다시 골라 최종으로
    if provisional or final_fit:
        holdout = {}
        if old and old.get("provisional"):  # 임시 엔진을 고를 때 안 본 지역에서의 성적 (엔진과 무관한 시험)
            holdout = {h: run_fixed(old, h) for h in regions if h not in old["regions"]}
            for h, r in holdout.items():
                print(f"  임시 엔진({len(old['regions'])}개 지역)으로 처음 본 {h}: 정확도 {r['acc']:.2f}, 5년 중앙 {r['win_median']:.2f}, 2019~ {r['recent']:.2f}")
        pub = {h: bool(r["acc"] >= 0.40 and r["win_median"] >= 0.25) for h, r in loro.items()}
        eng = {**final, "weights": ic_weights(regions, final["window"]) if final.get("learn") else None,
               "chosen": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "regions": regions, "objective": obj,  # 같은 날 다시 골라도 실시간 기록 이름이 겹치지 않게 시각까지
               "loro": {h: {k: r[k] for k in ("engine", "acc", "win_median", "win_min", "recent")} for h, r in loro.items()},
               "publish": pub, "seoul_check": sr, "provisional": provisional,
               # --refit으로 다시 고를 때도 임시 엔진의 시험 성적(미리 정한 기록)은 그대로 둔다
               "previous": {"name": old["name"], "chosen": old["chosen"], "regions": old["regions"], "holdout": holdout} if holdout
               else (old or {}).get("previous")}
        if (old or {}).get("extra"):  # 대구 공급 보정(region_supply.py)은 한 번 정해 고정: 엔진을 다시 골라도 그대로 잇는다 (예전엔 조용히 빠졌음)
            eng["extra"] = old["extra"]
        dump(eng, EP)
        print(f"{'임시' if provisional else '최종'} 엔진 저장: data/region_engine.json · 공개", [h for h, v in pub.items() if v])
        lines = [f"## 지역 엔진 {'임시 ' if provisional else ''}고정: {final['name']}", "", f"- 지역 {len(regions)}곳, 엔진 후보 {len(CONFIGS)}개, 목표 {obj:.3f}",
                 f"- 교차검증 평균 목표: 고른 엔진 {np.mean([r['obj'] for r in loro.values()]):.3f} · 서울과 같은 엔진 {np.mean([r['base']['obj'] for r in loro.values()]):.3f}",
                 f"- 서울에 써 보면 정확도 {sr['acc']:.2f} (서울 엔진 {run(base, 'seoul', regions)['acc']:.2f})", "",
                 "| 지역 | 교차검증 엔진 | 정확도 | 5년 중앙값 | 2019~ | 서울과 같은 엔진 | 공개 |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {REGIONS[h]['name']} | {r['engine']} | {r['acc']:.2f} | {r['win_median']:.2f} | {r['recent']:.2f} | "
                  f"{r['base']['acc']:.2f} / {r['base']['win_median']:.2f} | {'공개' if pub[h] else '검증 중'} |" for h, r in loro.items()]
        if final.get("learn"):
            top = sorted(eng["weights"].items(), key=lambda x: -x[1])[:8]
            lines += ["", "비중이 큰 표: " + ", ".join(f"{k} {v:.2f}" for k, v in top)]
        subs = pd.read_pickle(bt.ROOT / "results_region" / "region_calc.pkl")["subs"]
        late = [f"{REGIONS[x['region']]['name']} {REGIONS[x['region']]['lawd'][l]}({'실거래 0건' if x.get('first') is None else format(x['first'], '%Y-%m')})"
                for l, x in subs.items() if x.get("first") is None or x["first"] > pd.Timestamp("2008-01-01")]
        if late:  # 행정구역이 바뀐 곳의 옛 거래가 지금 코드로 안 왔을 수 있음 (부천·화성의 구 등) — 확인 필요
            lines += ["", "첫 실거래가 2008년 뒤인 시군구 (옛 거래가 빠졌는지 확인): " + ", ".join(late)]
        if holdout:
            lines += ["", f"임시 엔진({old['chosen']}, {len(old['regions'])}개 지역으로 고름)을 고를 때 안 본 지역에 그대로 쓴 성적:"]
            lines += [f"- {REGIONS[h]['name']}: 정확도 {r['acc']:.2f}, 5년 중앙값 {r['win_median']:.2f}, 2019년 이후 {r['recent']:.2f}" for h, r in holdout.items()]
        (bt.ROOT / "results_region" / "engine_new.md").write_text("\n".join(lines) + "\n")
    print(f"\n[모든 지역으로 고른 엔진] {final['name']} (목표 {obj:.3f})")
    print(f"  서울에 써 보면: 정확도 {sr['acc']:.2f}, 5년 중앙 {sr['win_median']:.2f} | 서울 엔진 {run(base, 'seoul', regions)['acc']:.2f}")
    # 시간까지 나눈 점검: 고정 엔진의 비중을 2018년까지(이후 12개월이 2019년 전에 끝나는 달)의 다른 지역 자료로만 배워 2019년~에 쓴 성적.
    # 교차검증은 지역만 빼고 같은 기간으로 비중을 배우므로, 이 값이 시간상 정직한 성적에 더 가깝다 (지역 페이지에 함께 적음)
    fixed = json.loads(EP.read_text()) if EP.exists() else None
    honest = {n: run(fixed, n, regions, SPLIT, wb=TRAIN_END) for n in regions} if fixed else {}
    # 공급 보정 지역은 보정 없이 잰 같은 성적도 남긴다 (지역 페이지의 '보정 전 → 후' 숫자)
    honest_base = {n: run({**fixed, "extra": {}}, n, regions, SPLIT, wb=TRAIN_END) for n in (fixed or {}).get("extra") or {}} if fixed else {}
    # 고정 엔진을 지금 정답(발표한 달부터 12개월)으로, 그 지역만 빼고 비중을 배워 잰 성적 (지역 페이지 표시용. 공개 여부는 고정할 때 정한 그대로)
    fixed_loro = {n: run(fixed, n, regions) for n in regions} if fixed else {}
    if honest:
        print("\n[시간까지 나눈 점검: 고정 엔진, 2018년까지 배운 비중 → 2019년~]")
        print("  ", {n: f"{h['acc']:.2f} / 5년 중앙 {h['win_median']:.2f}" for n, h in honest.items()})
    dump({"regions": regions, "configs": [c["name"] for c in CONFIGS], "full": full, "loro": loro,
          "period": {"engine": cfg_t["name"], "per": per}, "honest": honest, "honest_base": honest_base, "fixed_loro": fixed_loro, "final": final, "final_obj": obj, "seoul_check": sr},
         bt.ROOT / "results_region" / "engine_study.json")

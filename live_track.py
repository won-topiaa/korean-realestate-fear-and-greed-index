"""실시간 검증 기록 (지우거나 고치지 않는 기록).

지금까지의 백테스트 성적은 엔진을 정할 때 이미 본 자료로 낸 것이라 낙관적 편향이 남는다.
그래서 매달 발표한 점수를 그때 값 그대로 쌓고, 12개월 뒤 실거래 가격이 나오면 그 기록만으로 성적을 매긴다.
나중에 자료가 수정되거나 엔진이 바뀌어도 이미 적힌 줄은 바꾸지 않는다.
"""
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

import timing

ROOT = Path(__file__).parent
LOG = ROOT / "results_zone" / "live_log.csv"
COLS = ["logged_at", "engine", "month", "region", "score"]
REL = "구상대강도-v1"  # 공포탐욕 엔진과 따로 채점


def load():
    return pd.read_csv(LOG, dtype={"month": str}) if LOG.exists() else pd.DataFrame(columns=COLS)


def record(map_data_path=ROOT / "results_zone" / "map_data.json"):
    """지도 데이터의 최신 달 점수를 아직 기록이 없을 때만 덧붙인다."""
    import v3
    d = json.loads(Path(map_data_path).read_text())
    month = d["dates"][-1]
    log = load()
    have = set(zip(log["engine"], log["month"], log["region"]))
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    eng = d.get("version", v3.VERSION)  # 지도 자료를 만든 엔진 버전 (기록 시점의 코드 버전이 아니라)
    new = [{"logged_at": now, "engine": eng, "month": month, "region": r, "score": round(reg["score"][-1], 1)}
           for r, reg in d["regions"].items() if reg["score"][-1] is not None and (eng, month, r) not in have]
    # 서울 안 상대 강도 (구, 신고가 비중의 25개 구 안 백분위): 구끼리 순위로만 채점
    new += [{"logged_at": now, "engine": REL, "month": month, "region": r, "score": reg["rel"]["pct"][-1]}
            for r, reg in d["regions"].items() if reg.get("rel") and reg["rel"]["pct"][-1] is not None and (REL, month, r) not in have]
    if new:
        pd.concat([log, pd.DataFrame(new)], ignore_index=True).to_csv(LOG, index=False)
    return len(new), month


def record_regions(out=ROOT / "results_region"):
    """수도권·광역시: 최신 달 시도·시군구 점수를 아직 기록이 없을 때만 덧붙인다 (공개 전인 지역도 검증용으로 남긴다).
    엔진 이름은 '{버전}-지역A' 또는 '{버전}-지역{고정한 날짜}' (서울 엔진과 섞이지 않게), 시군구 이름은 '부산 해운대구'처럼 시도 이름을 붙인다."""
    p = out / "summary.json"
    if not p.exists():
        return 0, None
    summ = json.loads(p.read_text())
    log = load()
    have = set(zip(log["engine"], log["month"], log["region"]))
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    new, month = [], None
    for rid, s in summ.items():
        d = json.loads((out / f"{rid}.json").read_text())
        eng = f"{d['version']}-지역{s.get('engine', 'A')}"  # A = 서울과 같은 엔진, 날짜 = 그날 고정한 지역 엔진
        if d.get("k", 1.5) != 1.5:  # 눈금을 바꾼 뒤의 점수는 다른 기록으로 (2026-10-22 지역 1.1배, 그 전 1.5배 줄은 그대로 둔다)
            eng += f"-눈금{d['k']}"
        if s.get("extra"):  # 공급 보정 지역(대구)은 다른 지역과 엔진이 달라 따로 채점
            eng += "-공급보정"
        t = d["dates"].index(s["month"])
        month = s["month"]
        for name, reg in d["regions"].items():
            v = reg["score"][t]
            label = name if reg["level"] == "top" else f"{d['top']} {name}"
            if v is not None and (eng, month, label) not in have:
                new.append({"logged_at": now, "engine": eng, "month": month, "region": label, "score": v})
    if new:
        pd.concat([log, pd.DataFrame(new)], ignore_index=True).to_csv(LOG, index=False)
    return len(new), month


def evaluate():
    """기록된 점수와 그 뒤 12개월 실거래 가격 변화의 순위상관 (엔진·지역별, 12개월 이상 쌓인 경우만).
    상대 강도는 달마다 25개 구끼리 순위를 비교해 평균한다."""
    from scipy.stats import spearmanr
    log = load()
    if log.empty:
        return {"logged_months": 0, "evaluable": 0, "by_region": {}, "relative": {"months": 0, "ic": None}}
    rs = {"서울": pd.read_csv(ROOT / "data" / "targets_extra.csv", index_col=0, parse_dates=True)["실거래지수"]}
    zc = ROOT / "results_zone" / "zone_calc.pkl"
    if zc.exists():
        zcd = pd.read_pickle(zc)
        for z, o in {**zcd["zones"], **zcd.get("gus", {})}.items():
            rs[z] = o["rs"]
    for p in sorted((ROOT / "results_region").glob("*.json")):  # 수도권·광역시 (지역 페이지 자료의 실거래 지수, 이름은 record_regions와 같게)
        x = json.loads(p.read_text())
        if "top" not in x:
            continue
        dates = pd.to_datetime(pd.Series(x["dates"]) + "-01")
        for name, reg in x["regions"].items():
            if reg.get("rs") is not None:
                rs[name if reg["level"] == "top" else f"{x['top']} {name}"] = pd.Series(reg["rs"], index=dates, dtype=float)

    def fwd(r, month):
        s = rs.get(r)
        if s is None:
            return None
        t0 = pd.Timestamp(month + "-01") + pd.DateOffset(months=timing.PUB_OFFSET)  # 발표한 달부터 (기준월 t는 t+1월에 발표)
        t1 = t0 + pd.DateOffset(months=12)
        if t1 in s.index and pd.notna(s.get(t1)) and pd.notna(s.get(t0)):
            return float(np.log(s[t1] / s[t0]))
        return None

    out = {}
    main = log[log["engine"] != REL]
    for (eng, r), sub in main.groupby(["engine", "region"]):  # 엔진별로 따로 (버전이 섞이지 않게)
        pts = [(row["score"], y) for _, row in sub.iterrows() if (y := fwd(r, row["month"])) is not None]
        ic = spearmanr(*zip(*pts)).statistic if len(pts) >= 12 else None
        out.setdefault(eng, {})[r] = {"n": len(pts), "ic": None if ic is None else round(float(ic), 3)}
    rel, months = log[log["engine"] == REL], []
    for m, sub in rel.groupby("month"):  # 같은 달 구끼리 순위 비교
        pts = [(row["score"], y) for _, row in sub.iterrows() if (y := fwd(row["region"], m)) is not None]
        if len(pts) >= 20:
            months.append(spearmanr(*zip(*pts)).statistic)
    rel_out = {"months": len(months), "ic": round(float(np.mean(months)), 3) if months else None}
    reg_eng = main["engine"].str.contains("-지역")  # 수도권·광역시 엔진은 서울 보고서의 기록 개월 수에 섞지 않는다
    seoul, region = main[~reg_eng], main[reg_eng]
    n_eval = lambda e: max((v["n"] for k, x in out.items() if (k in set(e["engine"])) for v in x.values()), default=0)
    return {"logged_months": int(seoul["month"].nunique()), "first_month": seoul["month"].min(), "evaluable": n_eval(seoul),
            "by_region": out, "relative": rel_out,
            "regions": {"logged_months": int(region["month"].nunique()), "first_month": region["month"].min() if len(region) else None,
                        "evaluable": n_eval(region)}}


if __name__ == "__main__":
    import sys
    if "--regions" in sys.argv:
        n, m = record_regions()
        print(f"지역 기록 {n}줄 추가 ({m})")
    else:
        n, m = record()
        print(f"기록 {n}줄 추가 ({m})", json.dumps(evaluate(), ensure_ascii=False))

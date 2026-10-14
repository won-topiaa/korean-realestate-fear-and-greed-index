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
    new = [{"logged_at": now, "engine": v3.VERSION, "month": month, "region": r, "score": round(reg["score"][-1], 1)}
           for r, reg in d["regions"].items() if reg["score"][-1] is not None and (v3.VERSION, month, r) not in have]
    # 서울 안 상대 강도 (구, 신고가 비중의 25개 구 안 백분위): 구끼리 순위로만 채점
    new += [{"logged_at": now, "engine": REL, "month": month, "region": r, "score": reg["rel"]["pct"][-1]}
            for r, reg in d["regions"].items() if reg.get("rel") and reg["rel"]["pct"][-1] is not None and (REL, month, r) not in have]
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

    def fwd(r, month):
        s = rs.get(r)
        if s is None:
            return None
        t0 = pd.Timestamp(month + "-01")
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
    return {"logged_months": int(main["month"].nunique()), "first_month": main["month"].min(),
            "evaluable": max((v["n"] for e in out.values() for v in e.values()), default=0), "by_region": out, "relative": rel_out}


if __name__ == "__main__":
    n, m = record()
    print(f"기록 {n}줄 추가 ({m})", json.dumps(evaluate(), ensure_ascii=False))

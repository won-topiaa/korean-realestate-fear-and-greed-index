"""backtest.py 결과의 강건성 점검: 신뢰구간, 점수화 기간 민감도, 주요 국면 스냅샷, 현재값."""
import json

import numpy as np
import pandas as pd

import backtest as bt

SHORTLIST = [
    ("분류방식 전체지수", "[2단계] 주제 그룹 균등"),
    ("분류방식 전체지수", "[2단계] 속도 그룹 균등"),
    ("분류방식 전체지수", "[2단계] 출처성격 그룹 균등"),
    ("분류방식 전체지수", "[2단계] 행위자 그룹 균등"),
    ("분류방식 전체지수", "[2단계] 시장 그룹 균등"),
    ("분류방식 전체지수", "[1단계] 31개 지표 균등"),
    ("CNN복제", "CNN 7개 대응지표"),
    ("사용자원안", "원안 전체(금리+공급+언급수)"),
    ("주제", "수급심리"), ("주제", "가격"), ("주제", "금융시장"), ("주제", "자금"),
    ("주제", "관심"), ("주제", "전세"), ("주제", "가격부담"), ("주제", "공급"),
    ("속도", "선행"), ("속도", "동행"), ("속도", "후행"),
    ("시장", "매매"), ("시장", "금융"),
    ("단일지표", "설문_매수우위"),
]
SNAP_DATES = ["2006-11-01", "2008-12-01", "2010-03-01", "2012-12-01", "2013-09-01", "2015-06-01",
              "2018-09-01", "2020-07-01", "2021-09-01", "2022-11-01", "2023-06-01", "2024-05-01",
              "2025-06-01", "2026-09-01"]


def series_for(scores, meta, cands, scheme, name):
    if scheme == "분류방식 전체지수":
        return bt.scheme_indices(scores, meta, cands)[name]
    mem = next(m for s, n, m in cands if s == scheme and n == name)
    return bt.composite(scores, mem)


def main():
    out = {}
    scores, meta, targets, mom, price = bt.load()
    cands, _, _ = bt.build_candidates(scores, meta)

    # 1) 블록 부트스트랩 90% 신뢰구간 (전체기간, 선행12)
    ci = []
    for scheme, name in SHORTLIST:
        s = series_for(scores, meta, cands, scheme, name)
        m = bt.window_mask(s.index, bt.FULL)
        lo, hi = bt.block_bootstrap_ic(s[m].to_numpy(), targets["선행12"][m].to_numpy())
        ci.append({"분류방식": scheme, "그룹": name, "IC_5%": lo, "IC_95%": hi})
    ci = pd.DataFrame(ci)
    ci.to_csv(bt.OUT / "bootstrap_ci.csv", index=False)

    # 2) 점수화 기간 민감도 (60개월 / 120개월 / 전체누적)
    sens = []
    for w in (60, 120, 10_000):
        bt.WINDOW = w
        sc, mt, tg, mo, _ = bt.load()
        cd, _, _ = bt.build_candidates(sc, mt)
        for scheme, name in SHORTLIST:
            s = series_for(sc, mt, cd, scheme, name)
            r = bt.evaluate(s, tg, mo)
            sens.append({"창": "누적" if w > 1000 else f"{w}개월", "분류방식": scheme, "그룹": name,
                         "학습_선행12": r["학습_선행12"], "검증_선행12": r["검증_선행12"],
                         "학습_동행": r["학습_동행"], "검증_동행": r["검증_동행"]})
    bt.WINDOW = 120
    sens = pd.DataFrame(sens)
    sens.to_csv(bt.OUT / "window_sensitivity.csv", index=False)

    # 3) 주요 국면 스냅샷 + 현재값
    snap = {}
    for scheme, name in SHORTLIST:
        s = series_for(scores, meta, cands, scheme, name)
        snap[name] = s.reindex(pd.to_datetime(SNAP_DATES))
    snap = pd.DataFrame(snap)
    snap["서울아파트_이후12개월"] = targets["선행12"].reindex(pd.to_datetime(SNAP_DATES))
    snap.to_csv(bt.OUT / "snapshots.csv")

    latest = scores.index[-1]
    groups_now = {t: float(bt.composite(scores, meta.index[meta["주제"] == t]).iloc[-1]) for t in sorted(meta["주제"].unique())}
    out["latest"] = str(latest.date())
    out["groups_now"] = groups_now
    out["indicators_now"] = scores.iloc[-1].round(1).dropna().to_dict()
    json.dump(out, open(bt.OUT / "latest.json", "w"), ensure_ascii=False, indent=1)

    pd.set_option("display.width", 250)
    print(ci.round(2).to_string(index=False))
    print(sens.pivot_table(index="그룹", columns="창", values=["학습_선행12", "검증_선행12"]).round(2).to_string())
    print(snap.round(0).T.to_string())
    print(json.dumps(out, ensure_ascii=False, indent=1)[:1500])


if __name__ == "__main__":
    main()

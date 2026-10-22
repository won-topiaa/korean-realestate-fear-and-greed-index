"""깨끗한 공공판 P5: KB·네이버 주가·구글 검색량 없이, 상업 이용 근거가 있는 공개 자료만 → results_v2/public_clean.json

2026-10-21, 결과를 보기 전에 정한 규칙 (대체 자료 조사 결과를 반영):
- 주가(금융위 API 공공누리 4유형·KRX Open API 비상업 전용)와 구글 트렌드(상업 이용 근거 없음)는 표에서 뺀다 (금융시장·관심 표).
- 서울: P1 정의(부동산원 매매지수 3개월 변화·12개월 평균 대비, 부동산원 수급, 부동산원 전세지수, GDP로 잰 PIR·구매력)에
    · 설문_거래활발 = 국토연 주택시장 소비심리지수, 2개월 늦춤 (공개 시점 점검 결과)
    · 가격_선도50모멘텀 = 그때 알 수 있던 거래로 추정한 시가총액 상위 50단지 지수 3개월 변화 (public_own.py)
    · 가격_상승구비율 = 그때 알 수 있던 거래로 추정한 구별 지수에서 오른 구 비율, 3개월 평균 (public_own.py)
    · 부담_전세가율역수 = −부동산원 아파트 평균 매매가격 대비 전세가격(R-ONE A_2024_00072), 1개월 늦춤.
      2012년 1월 전은 −(전세지수/매매지수)를 2012년 1월 값에 맞춰 잇는다.
- 지역: public_own_region.py 정의(그 지역 실거래 지수, 부동산원 수급·전세지수, 국토연 소비심리 2개월 늦춤)에
    부담_전세가율역수만 서울과 같이 R-ONE 전세가율로 바꾸고, 엔진은 '자료로 비중 · 120개월'에서 금융시장·관심 표를 뺀다.
판정: 서울과 지역마다 정확도(2011년 2월 이후) ≥ 0.40, 5년 구간 중앙값 ≥ 0.25면 그 판을 인덱서고용 깨끗한 공공판으로 한다.
참고로 같은 정의에 주가·구글을 넣은 판도 함께 재서, 두 자료를 뺀 비용을 보인다 (판정에는 쓰지 않음).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import backtest as bt
import public_own as PO
import public_own_region as PR
import public_variant as PV
import region_engine_study as S
import remedies as RM
import v3
from regions import REGIONS

TMP = Path("/private/tmp/claude-501/-Users-yjw/b8b4c778-0365-4340-aad1-4dbabb5624df/scratchpad/public_rt.pkl")


def ratio(rid, p, j, idx):
    """R-ONE 전세가율(%), 2012년 전은 지수 비율을 2012년 1월에 맞춰 잇는다 → 1개월 늦춤."""
    r1 = PR.reb(f"r_{rid}_전세가율")
    old = j / p
    k = r1.iloc[0] / old.reindex([r1.index[0]]).iloc[0]
    s = pd.concat([old[old.index < r1.index[0]] * k, r1])
    return PR.put(s, idx, 1)


def seoul(with_market):
    raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
    raw = raw[raw.index <= raw["__price"].last_valid_index()]
    meta, aux = v3.load_meta()
    y = RM.Y["실거래"]
    s = pd.read_pickle(PO.CACHE)["s"].reindex(raw.index)
    pub = PV.public_cols(raw)
    pub["설문_거래활발"] = pub["설문_거래활발"].shift(1)
    pub["가격_선도50모멘텀"] = s["lead_d3"]
    pub["가격_상승구비율"] = s["up3"]
    pub["부담_전세가율역수"] = -ratio("seoul", PV.reb("reb_매매지수_서울"), PV.reb("reb_전세지수_서울"), raw.index)
    pub["전세_매매선호"] = np.nan
    p5 = raw.copy()
    p5[pub.columns] = pub
    m = meta.loc[[c for c in meta.index if c != "전세_매매선호"]]
    if not with_market:
        m = m.loc[[c for c in m.index if not c.startswith(("시장_", "관심_"))]]
    r = v3.compute(p5, m, aux)
    e, w = PV.ev(r["final"], y)
    nv = r["n_votes_available"]
    return {"2011~": e["2011~"], "5년 중앙값": e["5년 중앙값"], "5년 최저": e["5년 최저"], "현재": e["현재"],
            "표 수 (2011·최신)": f"{int(nv.get(pd.Timestamp('2011-02-01'), 0))}/{int(nv.iloc[-1])}",
            "기준 통과": bool(e["2011~"] >= 0.40 and e["5년 중앙값"] >= 0.25)}, r["final"]


def regions(with_market):
    base = next(c for c in S.CONFIGS if c["name"] == "자료로 비중 · 120개월")
    cfg = dict(base, drop=[] if with_market else ["금융시장", "관심"])
    rids = list(S.DATA)
    kb_data = S.DATA
    lead = pd.read_pickle(PO.CACHE)["s"]["lead_d3"]
    rts = pd.read_pickle(TMP)
    pub = {}
    for rid in rids:
        ind = kb_data[rid]["ind"]
        o = PR.public_region(rid, ind, rts[rid], lead)
        o["설문_거래활발"] = o["설문_거래활발"].shift(1)
        o["부담_전세가율역수"] = -ratio(rid, PR.reb(f"r_{rid}_매매지수"), PR.reb(f"r_{rid}_전세지수"), ind.index)
        pub[rid] = {"ind": o, "fwd12": kb_data[rid]["fwd12"]}
    S.DATA, S.CACHE = pub, {}
    out = {}
    for h in rids:
        f = S.run(cfg, h, rids)
        out[REGIONS[h]["name"]] = {"정확도": f["acc"], "5년 중앙값": f["win_median"], "5년 최저": f["win_min"], "2019~": f["recent"],
                                   "기준 통과": bool(f["acc"] >= 0.40 and f["win_median"] >= 0.25)}
    S.DATA, S.CACHE = kb_data, {}
    return out


if __name__ == "__main__":
    res = {}
    for tag, wm in [("P5 깨끗한 공공판", False), ("참고: P5 + 주가·구글", True)]:
        sr, _ = seoul(wm)
        res[tag] = {"서울": sr, **regions(wm)}
    rows = {f"{t} | {r}": v for t, d in res.items() for r, v in d.items()}
    pd.set_option("display.width", 200)
    print(pd.DataFrame(rows).T.round(3).to_string())
    (bt.ROOT / "results_v2" / "public_clean.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))

"""공공판 P7: P6의 PIR을 대출 상한이 없는 PIR로 바꿈 → results_v2/public_p7.json

2026-10-21, 결과를 보기 전에 정한 규칙 (공공판 시험의 마지막 회차, 결과가 어떻게 나와도 그대로 받아들임):
- P6(public_keys.py)에서 부담_PIR 하나만 바꾼다.
  주택금융공사 지역별 PIR(보금자리론·디딤돌 이용자, 대출 가능 집값에 상한) → K-HAI에서 금리 부분을 뺀 PIR
    log PIR = log K-HAI − log(20년 원리금균등 상환 계수)
  K-HAI = (중간가격 × LTV 47.9% × 상환 계수 ÷ DTI 25.7%) ÷ 중간가구소득 이므로, 상수를 빼면 중간가격 ÷ 중간가구소득이다
  (HOUSTAT 표 설명의 산식). 금리는 K-HAI와 같은 한국은행 신규취급 예금은행 주담대 금리의 그 분기 평균.
  쓰는 시점은 K-HAI와 같이 분기 끝 4개월 뒤 달부터.
- 나머지(국토연 매매심리 2개월 늦춤, K-HAI 구매력, 주가·구글 없음)는 P6와 같다. 서울과 모든 지역에 같은 정의.
판정: 서울과 지역마다 정확도(2011년 2월 이후) ≥ 0.40, 5년 구간 중앙값 ≥ 0.25면 통과.
  서울은 12개월 덩어리 부트스트랩 90% 구간과 KB판과의 차이 구간, 2011~2018·2019~ 정확도를 함께 적는다.
  지역은 2017년까지 배운 비중으로 2019년 이후 정확도를 함께 적는다.
지금까지 시험한 공공판 후보 (모두 공개): P1 부동산원·국토연·GDP 대체+주가·구글, P2 P1−주가, P3 P2−구글,
  P4 자체 실거래 지표(선도50·상승구·지역 실거래 지수), P4−주가, P4−주가·구글, P5 깨끗한 공공판, P6 P5+매매심리·K-HAI·HF PIR,
  P6에서 HF PIR만 뺀 사후 확인, P7.
참고: K-HAI의 중간가격은 2012년까지 KB아파트 시세, 2013년부터 한국부동산원 아파트 시세다 (주택금융공사가 만든 통계를 HOUSTAT 약관으로 씀).
"""
import json

import numpy as np
import pandas as pd

import backtest as bt
import public_clean as PC
import public_keys as PK
import public_own as PO
import public_own_region as PR
import public_validate as PVal
import region_engine_study as S
import remedies as RM
import v3
from build_indicators import ecos
from regions import REGIONS


def khai_pir(region):
    k = PK.khai(region)  # 날짜 = 쓸 수 있는 달 (분기 끝 + 4개월)
    r = ecos("주담대금리") / 100 / 12
    rq = r.resample("QS").mean()
    af = rq / (1 - (1 + rq) ** -240)
    af.index = af.index + pd.DateOffset(months=6)  # 분기 첫 달 + 2 = 분기 끝, + 4
    return np.log(k) - np.log(af.reindex(k.index))


def p7_cols(region, idx):
    new = PK.new_cols(region, idx)
    new["부담_PIR"] = PR.put(khai_pir(region), idx, 0)
    return new


def seoul():
    raw, p5, _ = PK.seoul_frames()
    meta, aux = v3.load_meta()
    y = RM.Y["실거래"]
    m = meta.loc[[c for c in meta.index if c != "전세_매매선호" and not c.startswith(("시장_", "관심_"))]]
    new = p7_cols("서울", raw.index)
    p7 = p5.copy()
    for c in PK.SWAPS:
        p7[c] = new[c]
    e, s = PK.seoul_eval(p7, m, aux, y)
    kb = v3.compute(raw, meta, aux)["final"]
    out = {"2011~": e["2011~"], "5년 중앙값": e["5년 중앙값"], "5년 최저": e["5년 최저"], "현재": e["현재"],
           "기준 통과": bool(e["2011~"] >= 0.40 and e["5년 중앙값"] >= 0.25)}
    k = y.index >= PVal.OFF
    ci = PVal.paired_boot(kb.reindex(y.index)[k].to_numpy(), s.reindex(y.index)[k].to_numpy(), y[k].to_numpy())
    out["90% 구간"], out["차이(KB−P7) 90% 구간"] = list(ci[:, 1]), list(ci[:, 2])
    si = s.reindex(y.index)
    part = lambda a, b: bt.spearman(si[(si.index >= a) & (si.index < b)].to_numpy(), y[(y.index >= a) & (y.index < b)].to_numpy())
    out["2011~2018"], out["2019~"] = part(PVal.OFF, PVal.SPLIT), part(PVal.SPLIT, pd.Timestamp("2100-01-01"))
    a, b = kb[kb.index >= PVal.OFF], s.reindex(kb.index)[kb.index >= PVal.OFF]
    ok = a.notna() & b.notna()
    za, zb = pd.cut(a[ok], PVal.ZONES, right=False), pd.cut(b[ok], PVal.ZONES, right=False)
    out["신호 일치"] = {"지수 상관": float(a[ok].corr(b[ok])), "같은 구간 비율": float((za == zb).mean()),
                     "한 칸 안 비율": float((abs(za.cat.codes - zb.cat.codes) <= 1).mean())}
    yy = y[k]
    sc = lambda f: bt.spearman(v3.scores(f[["부담_PIR"]])["부담_PIR"].reindex(yy.index).to_numpy(), yy.to_numpy())
    out["PIR 하나 (2011~ 순위상관)"] = {"KB": sc(raw), "P5 GDP": sc(p5), "P7 K-HAI": sc(p7)}
    return out, s


def regions():
    base = next(c for c in S.CONFIGS if c["name"] == "자료로 비중 · 120개월")
    cfg = dict(base, drop=["금융시장", "관심"])
    rids = list(S.DATA)
    kb_data = S.DATA
    lead = pd.read_pickle(PO.CACHE)["s"]["lead_d3"]
    rts = pd.read_pickle(PC.TMP)
    p7 = {}
    for rid in rids:
        ind = kb_data[rid]["ind"]
        o = PR.public_region(rid, ind, rts[rid], lead)
        o["부담_전세가율역수"] = -PC.ratio(rid, PR.reb(f"r_{rid}_매매지수"), PR.reb(f"r_{rid}_전세지수"), ind.index)
        new = p7_cols(REGIONS[rid]["name"], ind.index)
        for c in PK.SWAPS:
            o[c] = new[c]
        p7[rid] = {"ind": o, "fwd12": kb_data[rid]["fwd12"]}
    S.DATA, S.CACHE = p7, {}
    out = {}
    train_end = PVal.SPLIT - pd.DateOffset(months=12)
    for h in rids:
        f = S.run(cfg, h, rids)
        late = S.run(cfg, h, rids, a=PVal.SPLIT, b=None, wb=train_end)
        out[REGIONS[h]["name"]] = {"정확도": f["acc"], "5년 중앙값": f["win_median"], "5년 최저": f["win_min"],
                                   "기간 검증 2019~": late["acc"], "기준 통과": bool(f["acc"] >= 0.40 and f["win_median"] >= 0.25)}
    S.DATA, S.CACHE = kb_data, {}
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    sr, _ = seoul()
    print(json.dumps(sr, ensure_ascii=False, indent=1, default=lambda x: round(float(x), 3)), flush=True)
    rr = regions()
    print("\n", pd.DataFrame(rr).T.round(3).to_string())
    res = {"rule": "public_p7.py docstring", "서울": sr, "지역": rr}
    (bt.ROOT / "results_v2" / "public_p7.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))

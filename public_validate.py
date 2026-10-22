"""공공판(KB 없이) 검증 → results_v2/public_validate.json

2026-10-21, 결과를 보기 전에 정한 검증:
1. 공개 시점: 각 공공 자료가 그 달 20일에 실제로 나와 있었는지 10월 21일에 받은 최신 달로 확인했다.
   국토연 주택시장 소비심리지수는 10월 21일에 8월 값이 최신(9월 값 미발표)이라 1개월이 아니라 2개월 늦춰야 한다.
   그래서 서울 P1과 지역 공공판의 설문_거래활발을 2개월 늦춤으로 고쳐 다시 잰다.
   (부동산원 매매·전세지수와 매매·전세수급은 9월 값이 있어 1개월 늦춤이 맞다. 주담대 금리 2개월·GDP 분기 끝 3개월 뒤는 그대로.)
2. 불확실성 (서울): 2011년 2월 이후 정확도의 90% 구간. 12개월 덩어리 부트스트랩 2,000번이고,
   KB판과 공공판은 같은 덩어리로 뽑아 차이의 구간도 낸다.
3. 기간 검증: 서울은 정의가 고정이라 2011-02~2018-12와 2019-01~의 정확도를 따로 본다.
   지역은 표 비중을 2017년 12월까지(이후 12개월 가격이 2019년 전에 끝나는 달)만 배우고 2019년 이후 정확도로 잰다 (평가 지역은 학습에서 뺌).
4. 신호 일치 (서울): 2011년 2월 이후 KB판과 공공판 지수의 상관, 같은 구간(0–25·25–45·45–55·55–75·75–100)에 있던 달 비율, 지금 값.
판정: 고친 공개 시점으로도 공개 기준(정확도 0.40, 5년 구간 중앙값 0.25)을 넘는지 다시 본다. 부트스트랩 구간 아래 끝이 0.40보다 낮으면 '불확실'로 적는다.
"""
import json
import time
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

OFF, SPLIT = pd.Timestamp("2011-02-01"), pd.Timestamp("2019-01-01")
TMP = Path("/private/tmp/claude-501/-Users-yjw/b8b4c778-0365-4340-aad1-4dbabb5624df/scratchpad/public_rt.pkl")
ZONES = [0, 25, 45, 55, 75, 100.01]


def paired_boot(a, b, y, n=2000, block=12, seed=0):
    m = ~(np.isnan(a) | np.isnan(b) | np.isnan(y))
    a, b, y = a[m], b[m], y[m]
    T = len(y)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(T / block))
    out = []
    for _ in range(n):
        st = rng.integers(0, T - block + 1, nb)
        i = np.concatenate([np.arange(s, s + block) for s in st])[:T]
        ry = bt.rank(y[i])
        ia, ib = np.corrcoef(bt.rank(a[i]), ry)[0, 1], np.corrcoef(bt.rank(b[i]), ry)[0, 1]
        out.append((ia, ib, ia - ib))
    return np.percentile(np.array(out), [5, 95], axis=0)


def seoul():
    raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
    raw = raw[raw.index <= raw["__price"].last_valid_index()]
    meta, aux = v3.load_meta()
    y = RM.Y["실거래"]
    pub = PV.public_cols(raw)
    pub["설문_거래활발"] = pub["설문_거래활발"].shift(1)  # indicators.csv의 1개월 늦춤 + 1 = 2개월
    p1 = raw.copy()
    p1[pub.columns] = pub
    p1_meta = meta.loc[[c for c in meta.index if c not in ("가격_상승구비율", "전세_매매선호")]]
    kb, pb = v3.compute(raw, meta, aux)["final"], v3.compute(p1, p1_meta, aux)["final"]
    out = {}
    for n, s in [("KB판", kb), ("공공판 P1", pb)]:
        e, _ = PV.ev(s, y)
        si = s.reindex(y.index)
        part = lambda a, b: bt.spearman(si[(si.index >= a) & (si.index < b)].to_numpy(), y[(y.index >= a) & (y.index < b)].to_numpy())
        out[n] = {"2011~": e["2011~"], "5년 중앙값": e["5년 중앙값"], "5년 최저": e["5년 최저"],
                  "2011~2018": part(OFF, SPLIT), "2019~": part(SPLIT, pd.Timestamp("2100-01-01")), "현재": float(s.dropna().iloc[-1])}
    m = y.index >= OFF
    ci = paired_boot(kb.reindex(y.index)[m].to_numpy(), pb.reindex(y.index)[m].to_numpy(), y[m].to_numpy())
    out["KB판"]["90% 구간"], out["공공판 P1"]["90% 구간"] = list(ci[:, 0]), list(ci[:, 1])
    out["차이(KB−공공) 90% 구간"] = list(ci[:, 2])
    a, b = kb[kb.index >= OFF], pb.reindex(kb.index)[kb.index >= OFF]
    ok = a.notna() & b.notna()
    za, zb = pd.cut(a[ok], ZONES, right=False), pd.cut(b[ok], ZONES, right=False)
    out["신호 일치"] = {"지수 상관": float(a[ok].corr(b[ok])), "같은 구간 비율": float((za == zb).mean()),
                     "한 칸 안 비율": float((abs(za.cat.codes - zb.cat.codes) <= 1).mean())}
    return out


def regions():
    cfg = next(c for c in S.CONFIGS if c["name"] == "자료로 비중 · 120개월")
    rids = list(S.DATA)
    kb_data = S.DATA
    lead = pd.read_pickle(PO.CACHE)["s"]["lead_d3"]
    rts = pd.read_pickle(TMP) if TMP.exists() else {}
    pub = {}
    for rid in rids:
        ind = kb_data[rid]["ind"]
        if rid not in rts:
            t0 = time.time()
            rts[rid] = PR.rt_series(rid, ind.index[ind.index >= "2007-01-01"])
            pd.to_pickle(rts, TMP)
            print(f"  {rid} 실거래 지표 {time.time() - t0:.0f}s", flush=True)
        o = PR.public_region(rid, ind, rts[rid], lead)
        o["설문_거래활발"] = o["설문_거래활발"].shift(1)  # 2개월 늦춤
        pub[rid] = {"ind": o, "fwd12": kb_data[rid]["fwd12"]}
    out = {}
    train_end = SPLIT - pd.DateOffset(months=12)
    for tag, data in [("KB판", kb_data), ("공공판", pub)]:
        S.DATA, S.CACHE = data, {}
        for h in rids:
            full = S.run(cfg, h, rids)
            late = S.run(cfg, h, rids, a=SPLIT, b=None, wb=train_end)
            out.setdefault(REGIONS[h]["name"], {})[tag] = {"정확도": full["acc"], "5년 중앙값": full["win_median"], "5년 최저": full["win_min"],
                                                          "기간 검증 2019~": late["acc"],
                                                          "기준 통과": bool(full["acc"] >= 0.40 and full["win_median"] >= 0.25)}
    S.DATA, S.CACHE = kb_data, {}
    return out


if __name__ == "__main__":
    res = {"서울": seoul()}
    print(json.dumps(res["서울"], ensure_ascii=False, indent=1, default=lambda x: round(float(x), 3)), flush=True)
    res["지역"] = regions()
    rows = {f"{r} {t}": v for r, d in res["지역"].items() for t, v in d.items()}
    pd.set_option("display.width", 200)
    print(pd.DataFrame(rows).T.round(3).to_string())
    (bt.ROOT / "results_v2" / "public_validate.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))

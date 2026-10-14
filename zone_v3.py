"""권역·구별 v3 지수 (zone_index.py 결과 위에 v3 엔진 적용) → results_zone/zone_v3.pkl"""
import numpy as np
import pandas as pd

import backtest as bt
import v3
from zone_fetch import ZONES

P3 = [("2006-01-01", "2012-12-01"), ("2013-01-01", "2019-12-01"), ("2020-01-01", "2026-12-01")]
Z0 = pd.read_pickle(bt.ROOT / "results_zone" / "zone_calc.pkl")
out, weight = Z0["zones"], Z0["weight"]
meta, aux_meta = v3.load_meta()
seoul = pd.read_pickle(bt.ROOT / "results_v2" / "v3_seoul.pkl")
res = {}
for z in ZONES:
    o = out[z]
    r = v3.compute(o["ind"], meta, aux_meta)
    idx = o["ind"].index
    f, y = r["final"].reindex(idx), o["fwd12"]
    sf = seoul["final"].reindex(idx)
    ic = [bt.spearman(f[bt.window_mask(idx, w)].to_numpy(), y[bt.window_mask(idx, w)].to_numpy()) for w in P3]
    ic_s = [bt.spearman(sf[bt.window_mask(idx, w)].to_numpy(), y[bt.window_mask(idx, w)].to_numpy()) for w in P3]
    r.update({"rs": o["rs"], "fwd12": y, "ic": ic, "ic_seoul": ic_s,
              "n_zone": len([c for c in o["zone_specific"] if c in meta.index])})
    res[z] = r
    print(f"{z}: 현재 {f.dropna().iloc[-1]:.1f} | 권역 v3 {np.round(ic, 2)} | 서울 v3 대입 {np.round(ic_s, 2)} | 권역 고유 지표 {r['n_zone']}개")
OFF = pd.Timestamp(v3.OFFICIAL_START)
gres = {}
for g, o in Z0["gus"].items():
    r = v3.compute(o["ind"], meta, aux_meta)
    idx = o["ind"].index
    f, y, m = r["final"].reindex(idx), o["fwd12"], idx >= OFF
    zf, sf = res[o["zone"]]["final"].reindex(idx), seoul["final"].reindex(idx)
    acc = {k: bt.spearman(s[m].to_numpy(), y[m].to_numpy()) for k, s in [("gu", f), ("zone", zf), ("seoul", sf)]}
    r.update({"rs": o["rs"], "fwd12": y, "zone": o["zone"], "acc3": acc,
              "n_own": len([c for c in o["zone_specific"] if c in meta.index])})
    gres[g] = r
    print(f"{g}({o['zone']}): 현재 {f.dropna().iloc[-1]:.1f} | 2011~ 구 지수 {acc['gu']:.2f} · 권역 지수 {acc['zone']:.2f} · 서울 지수 {acc['seoul']:.2f}")
A = pd.DataFrame({g: r["acc3"] for g, r in gres.items()}).T
print("구 25개 평균 정확도", A.mean().round(3).to_dict(), "| 구 지수가 권역 지수보다 나은 구", int((A["gu"] > A["zone"]).sum()))
pd.to_pickle({"zones": res, "weight": weight, "gus": gres, "gu_weight": Z0["gu_weight"]}, bt.ROOT / "results_zone" / "zone_v3.pkl")

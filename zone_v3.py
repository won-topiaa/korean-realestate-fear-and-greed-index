"""권역별 v3 지수 (zone_index.py 결과 위에 v3 엔진 적용) → results_zone/zone_v3.pkl"""
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
pd.to_pickle({"zones": res, "weight": weight}, bt.ROOT / "results_zone" / "zone_v3.pkl")

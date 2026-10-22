"""대구 공급 보정: 지역 엔진에 공급 표 하나를 대구에만 더한다.

정한 날 2026-10-22 (사용자 결정). 대구의 발표 기준 5년 구간 중앙값이 공개 기준(0.25)에 걸친 걸 본 뒤 정한 사후 보정이라,
화면·README에 그렇게 밝힌다.
- 가설(사용자): 대구는 공급 물량이 유난히 많아(준공이 2015~17년, 2023~24년에 몰림) 공급이 가격을 크게 움직였다.
- 표: 공급_착공물량역수 = −(2~3년 전 12개월 착공 세대 ÷ 아파트 재고). 아파트는 착공 뒤 2~3년이면 입주하므로 앞으로의 입주 물량을
  그때 알 수 있던 자료로 대신한다.
  · 착공: 부동산원 R-ONE 국토부 주택착공실적 (대구>총계, 2011년 1월~). t월 값은 t+1월 말 공개 → 기준월 t 점수(t+1월 20일 발표)에는
    t−1월까지 → t−36~t−25월 합.
  · 재고: 건축물대장(data/molit_kr/buildings.csv) 대구 단지의 사용승인 달별 세대수 누계 (새 단지가 늦게 잡히는 몫은 2개월 늦춰 무시).
  · 점수: 다른 표와 같이 과거 120개월 안 백분위.
- 비중: 대구 자기 자료로 2018년 1월 전(이후 12개월이 2019년 전에 끝나는 달)까지 잰 이 표의 순위상관 (음수면 0). 다른 표의 비중은
  지역 엔진 그대로. 한 번 정해 data/region_engine.json의 extra에 남기고 다시 고르지 않는다.
- 시험 (정하기 전, 2018년까지 배워 2019년 이후, v3.5 자료): 대구 정확도 0.68 → 0.78, 5년 구간 중앙값 0.66 → 0.72.
  다른 지역에는 쓰지 않는다: 같은 방식을 7곳에 쓰면 부산(0.39 → 0.21)·경기(0.54 → 0.48)가 나빠져 평균은 0.55 → 0.54
  (공급과 가격의 관계가 2018년 무렵 뒤집힘). 건축물대장의 실제 준공 날짜로 만든 표는 사후 자료라 쓰지 않는다.
사용: python region_supply.py --fix   # 비중을 정해 data/region_engine.json에 남김 (한 번만)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import backtest as bt

ROOT = Path(__file__).parent
COL = "공급_착공물량역수"
EXTRA = {"daegu": "대구"}  # 공급 표를 더하는 지역 → 부동산원 이름
SID, ITEM = "T233033129823134", 10001  # 부동산원 R-ONE 국토부 주택착공실적
SIDO = {"daegu": "27"}  # 단지 번호 앞 두 자리 (재고)
TRAIN_END = pd.Timestamp("2018-01-01")
OFF = pd.Timestamp("2011-02-01")


def starts(rid):
    rows = json.loads((ROOT / "data" / "raw" / "reb" / f"r_{rid}_착공.json").read_text())
    s = pd.Series({pd.Timestamp(f"{r['WRTTIME_IDTFR_ID'][:4]}-{r['WRTTIME_IDTFR_ID'][4:6]}-01"): float(r["DTA_VAL"])
                   for r in rows if r.get("DTA_VAL") not in (None, "")}).sort_index()
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="MS"))


def stock(rid, end):
    b = pd.read_csv(ROOT / "data" / "molit_kr" / "buildings.csv", dtype=str, keep_default_na=False)
    b = b[(b["status"] == "ok") & (b["useApr"].str.len() >= 6) & (b["hhld"] != "") & b["aptSeq"].str.startswith(SIDO[rid])]
    m = pd.to_datetime(b["useApr"].str[:6], format="%Y%m", errors="coerce")
    h = pd.to_numeric(b["hhld"], errors="coerce").groupby(m).sum()
    return h.reindex(pd.date_range("1970-01-01", end, freq="MS"), fill_value=0).cumsum().shift(2)


def indicator(rid, idx):
    """기준월 기준으로 놓인 표의 원값 (높을수록 탐욕 = 앞으로 입주가 적음)."""
    s = starts(rid)
    end = max(idx.max(), s.index.max()) + pd.DateOffset(months=30)
    num = s.rolling(12).sum()
    num.index = num.index + pd.DateOffset(months=25)  # 기준월 t에는 t−36~t−25월 착공 합 (자료 끝에서 잘리지 않게 날짜를 옮김)
    den = stock(rid, end)
    den.index = den.index + pd.DateOffset(months=1)  # 그 앞달 재고
    return (-(num / den.reindex(num.index).replace(0, np.nan))).reindex(idx)


def vote(ind, window=120):
    bt.WINDOW = window
    try:
        return bt.pct_score(ind[COL])
    finally:
        bt.WINDOW = 120


def combine(V, w, ind, rid, extra):
    """표 비중 합치기 (region_v3·region_engine_study 공통). extra에 rid가 있으면 공급 표를 그 비중으로 더한다."""
    ww = pd.Series(w).reindex(V.columns).fillna(0)
    num, den = (V * ww).sum(axis=1, min_count=1), V.notna().mul(ww).sum(axis=1)
    ws = (extra or {}).get(rid, {}).get(COL, 0)
    if ws > 0 and COL in ind.columns:
        v = vote(ind).reindex(V.index)
        num = num.add(ws * v, fill_value=0).where(num.notna() | v.notna())
        den = den + ws * v.notna()
    return num / den.replace(0, np.nan)


if __name__ == "__main__" and "--fix" in sys.argv:
    EP = ROOT / "data" / "region_engine.json"
    eng = json.loads(EP.read_text())
    if eng.get("extra"):
        sys.exit(f"이미 정해져 있어요: {eng['extra']} (다시 고르지 않음)")
    R = pd.read_pickle(ROOT / "results_region" / "region_calc.pkl")["regions"]
    extra = {}
    for rid in EXTRA:
        o = R[rid]
        v, y = vote(o["ind"]), o["fwd12"].reindex(o["ind"].index)
        m = (v.index >= OFF) & (v.index < TRAIN_END)
        ic = bt.spearman(v[m].to_numpy(), y[m].to_numpy())
        extra[rid] = {COL: max(0.0, float(ic)), "chosen": str(pd.Timestamp.now().date()),
                      "rule": "region_supply.py docstring", "train_ic": float(ic)}
        print(f"{rid}: 2018년 1월 전 순위상관 {ic:.3f} → 비중 {extra[rid][COL]:.3f}")
    eng["extra"] = extra
    tmp = EP.with_name(EP.name + ".tmp")
    tmp.write_text(json.dumps(eng, ensure_ascii=False, indent=1, default=float))
    tmp.replace(EP)

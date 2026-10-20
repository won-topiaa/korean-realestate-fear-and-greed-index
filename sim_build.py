"""모의 투자 ('그때 샀다면 지금 얼마?') → results_sim/ (사이트 빌드 때 site/sim/data/로 복사, 저장소에는 안 올림).

단지·평형(전용 1㎡ 단위)마다 분기별 '층 맞춘 가격'(8~10층 기준, 그 분기 거래의 중앙값, 만원)을 낸다.
거래가 없던 분기는 화면에서 가장 가까운 거래 분기 값에 그 사이 구 실거래지수(반복매매) 변화를 곱해 채운다.
같이 싣는 것: 구·서울 분기 실거래지수(log), 구·서울 월별 공포탐욕 점수(지도와 같은 값).
- results_sim/meta.json: 분기 목록, 구별 지수, 공포탐욕 점수
- results_sim/gu/{구코드}.json: {단지: [[평형, 전용면적, [[분기, 가격, 거래수], ...]], ...]}
수도권·광역시: 지역 저장소에 들어온 지역마다 results_sim/{지역id}/ (같은 형식). 시군구 지수는 apt_score.gu_market(지역),
지역 전체 지수는 그 지역 모든 거래의 반복매매지수. 공포탐욕 점수는 지수를 공개한 지역만 싣는다 (아니면 fg = null).

사용: python sim_build.py [seoul|지역id ...]   (없으면 서울과 저장소에 있는 모든 지역)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import apt_score as A
import molit_indicators as MI
from regions import REGIONS, sub_word

ROOT = Path(__file__).parent
OUT = ROOT / "results_sim"
MIN_TRADES = 3  # 평형별 전체 거래가 이보다 적으면 싣지 않음


def whole_index(rid):
    """지역 전체 실거래 반복매매지수 (log, 월). 쌍이 적은 달은 앞 값."""
    t = MI.load(df=A.store(rid))
    months = pd.date_range(t["date"].min(), t["date"].max(), freq="MS")
    rs, npairs = MI.repeat_sales(t)
    lr = np.log(rs.reindex(months))
    lr[npairs.reindex(months).fillna(0) < A.MIN_PAIRS] = np.nan
    return lr.ffill().bfill()


def fg(rid):
    """공포탐욕 월별 점수: {dates, top(지역 전체), gu: {코드: 점수}}. 지수를 공개하지 않은 지역은 None."""
    if rid is None:
        md = json.loads((ROOT / "results_zone" / "map_data.json").read_text())
        R = md["regions"]
        return {"dates": md["dates"], "top": R["서울"]["score"], "gu": {g: R[n]["score"] for g, n in A.LAWD2GU.items() if n in R}}
    import home_build
    if rid not in home_build.published():
        return None
    x = json.loads((ROOT / "results_region" / f"{rid}.json").read_text())
    R = x["regions"]
    return {"dates": x["dates"], "top": R[x["top"]]["score"], "gu": {g: R[n]["score"] for g, n in REGIONS[rid]["lawd"].items() if n in R}}


def main(rid=None):
    out = OUT if rid is None else OUT / rid
    (out / "gu").mkdir(parents=True, exist_ok=True)
    mk = A.gu_market(rid)
    df = A.trades(mk, rid)
    y, mo = df["month"].dt.year, df["month"].dt.month
    q0 = int(y.min())
    df["q"] = (y - q0) * 4 + (mo - 1) // 3
    df["v"] = df["price"] * np.exp(-df["ff"])  # 8~10층 기준 가격
    nq = int(df["q"].max()) + 1
    qs = [f"{q0 + i // 4}.{i % 4 + 1}Q" for i in range(nq)]

    agg = df.groupby(["aptSeq", "type", "q"]).agg(v=("v", "median"), n=("v", "size"), a=("area", "median")).reset_index()
    tot = agg.groupby(["aptSeq", "type"])["n"].transform("sum")
    agg = agg[tot >= MIN_TRADES]
    area = df.groupby(["aptSeq", "type"])["area"].agg(lambda s: s.iloc[-1])  # 평형 이름: 가장 최근 거래의 전용면적
    code = None if rid is None else A.home(rid)  # 단지 → 화면용 지역 코드 (단지 검색과 같은 파일 나눔)
    key = (lambda s: s[:5]) if code is None else code.get
    per_gu = {}
    for (seq, typ), sub in agg.groupby(["aptSeq", "type"], sort=False):
        ser = [[int(q), int(round(v)), int(n)] for q, v, n in zip(sub["q"], sub["v"], sub["n"])]
        per_gu.setdefault(key(seq), {}).setdefault(seq, []).append([int(typ), round(float(area.loc[(seq, typ)]), 2), ser])
    for f in (out / "gu").glob("*.json"):  # 지난 실행의 파일 (없어진 구가 남지 않게)
        f.unlink()
    size = 0
    for g, d in per_gu.items():
        for seq in d:
            d[seq].sort()
        p = out / "gu" / f"{g}.json"
        p.write_text(json.dumps(d, separators=(",", ":")))
        size += p.stat().st_size

    # 구 분기 지수 (log, 분기 안 달 평균)
    mkq = mk.copy()
    mkq.index = [(d.year - q0) * 4 + (d.month - 1) // 3 for d in mkq.index]
    mkq = mkq.groupby(level=0).mean().reindex(range(nq)).ffill().bfill()
    if rid is None:  # 서울 전체: 지도와 같은 서울 실거래 반복매매지수
        md = json.loads((ROOT / "results_zone" / "map_data.json").read_text())
        rs = np.log(pd.Series(md["regions"]["서울"]["rs"], index=pd.to_datetime(md["dates"])).astype(float))
    else:
        rs = whole_index(rid)
    rsq = rs.groupby([(d.year - q0) * 4 + (d.month - 1) // 3 for d in rs.index]).mean().reindex(range(nq)).ffill().bfill()
    names = A.LAWD2GU if rid is None else REGIONS[rid]["lawd"]
    meta = {
        "asof": df["date"].max().strftime("%Y-%m-%d"), "region": rid or "seoul", "top": "서울" if rid is None else REGIONS[rid]["name"],
        "sub_word": "구" if rid is None else sub_word(rid), "quarters": qs,
        "floor": [round(float(np.expm1(v)) * 100, 1) for v in A.params(rid)[1]],
        "gu": {g: {"name": n, "idx": [round(float(x), 4) for x in mkq[g]]} for g, n in names.items() if g in mkq},
        "top_idx": [round(float(x), 4) for x in rsq],
        "fg": fg(rid),
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")))
    n_types = sum(len(v) for d in per_gu.values() for v in d.values())
    print(f"모의 투자 {meta['top']}: 단지 {sum(len(d) for d in per_gu.values()):,} · 평형 {n_types:,} · 분기 {qs[0]}~{qs[-1]} · "
          f"{size / 1e6:.1f} MB + meta {(out / 'meta.json').stat().st_size / 1e3:.0f} KB", flush=True)


if __name__ == "__main__":
    sys.exit(A.run_all(main, sys.argv[1:]))

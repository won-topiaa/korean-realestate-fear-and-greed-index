"""모의 투자 ('그때 샀다면 지금 얼마?') → results_sim/ (사이트 빌드 때 site/sim/data/로 복사, 저장소에는 안 올림).

단지·평형(전용 1㎡ 단위)마다 분기별 '층 맞춘 가격'(8~10층 기준, 그 분기 거래의 중앙값, 만원)을 낸다.
거래가 없던 분기는 화면에서 가장 가까운 거래 분기 값에 그 사이 구 실거래지수(반복매매) 변화를 곱해 채운다.
같이 싣는 것: 구·서울 분기 실거래지수(log), 구·서울 월별 공포탐욕 점수(지도와 같은 값).
- results_sim/meta.json: 분기 목록, 구별 지수, 공포탐욕 점수
- results_sim/gu/{구코드}.json: {단지: [[평형, 전용면적, [[분기, 가격, 거래수], ...]], ...]}
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import apt_score as A

ROOT = Path(__file__).parent
OUT = ROOT / "results_sim"
MIN_TRADES = 3  # 평형별 전체 거래가 이보다 적으면 싣지 않음


def main():
    (OUT / "gu").mkdir(parents=True, exist_ok=True)
    mk = A.gu_market()
    df = A.trades(mk)
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
    per_gu = {}
    for (seq, typ), sub in agg.groupby(["aptSeq", "type"], sort=False):
        ser = [[int(q), int(round(v)), int(n)] for q, v, n in zip(sub["q"], sub["v"], sub["n"])]
        per_gu.setdefault(seq[:5], {}).setdefault(seq, []).append([int(typ), round(float(area.loc[(seq, typ)]), 2), ser])
    size = 0
    for g, d in per_gu.items():
        for seq in d:
            d[seq].sort()
        p = OUT / "gu" / f"{g}.json"
        p.write_text(json.dumps(d, separators=(",", ":")))
        size += p.stat().st_size

    # 구 분기 지수 (log, 분기 안 달 평균)
    mkq = mk.copy()
    mkq.index = [(d.year - q0) * 4 + (d.month - 1) // 3 for d in mkq.index]
    mkq = mkq.groupby(level=0).mean().reindex(range(nq)).ffill().bfill()
    md = json.loads((ROOT / "results_zone" / "map_data.json").read_text())
    R, dates = md["regions"], md["dates"]
    rs = pd.Series(R["서울"]["rs"], index=pd.to_datetime(dates)).astype(float)
    rsq = np.log(rs).groupby([(d.year - q0) * 4 + (d.month - 1) // 3 for d in rs.index]).mean().reindex(range(nq)).ffill().bfill()
    meta = {
        "asof": df["date"].max().strftime("%Y-%m-%d"), "quarters": qs,
        "gu": {g: {"name": n, "idx": [round(float(x), 4) for x in mkq[g]]} for g, n in A.LAWD2GU.items() if g in mkq},
        "seoul_idx": [round(float(x), 4) for x in rsq],
        "fg": {"dates": dates, "seoul": R["서울"]["score"], "gu": {g: R[n]["score"] for g, n in A.LAWD2GU.items() if n in R}},
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")))
    n_types = sum(len(v) for d in per_gu.values() for v in d.values())
    print(f"모의 투자: 단지 {sum(len(d) for d in per_gu.values()):,} · 평형 {n_types:,} · 분기 {qs[0]}~{qs[-1]} · "
          f"{size / 1e6:.1f} MB + meta {(OUT / 'meta.json').stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()

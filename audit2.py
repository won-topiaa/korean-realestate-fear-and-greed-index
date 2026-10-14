"""엔진이 단순 기준보다 나은지: 5년 이동 구간 순위상관 분포."""
import numpy as np
import pandas as pd

import backtest as bt
import remedies as RM
import v3

raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
raw = raw[raw.index <= raw["__price"].last_valid_index()]
meta, _ = v3.load_meta()
y = RM.Y["실거래"]
LAG1 = [c for c in meta.index if (c.startswith("거래_") and c not in ("거래_신고가비중", "거래_급락거래역수")) or c.startswith("관심_")
        or c.startswith("시장_") or c in ("공급_미분양역수", "자금_기준금리수준", "자금_기준금리변화", "자금_국고채10년변화")]
R = raw.copy(); R[LAG1] = R[LAG1].shift(1)
tg = pd.read_csv(bt.ROOT / "data" / "targets_extra.csv", index_col=0, parse_dates=True)
rs = tg["실거래지수"].reindex(raw.index)
cands = {
    "v3 (현재)": v3.compute(raw[meta.index], meta)["final"],
    "v3 (공개 시차 반영)": v3.compute(R[meta.index], meta)["final"],
    "단순: KB 3개월 가격변화": bt.pct_score(np.log(raw["__price"]).diff(3)),
    "단순: 실거래 6개월 가격변화 (2개월 늦게 앎)": bt.pct_score((np.log(rs) - np.log(rs).shift(6)).shift(2)),
    "단순: KB 매수우위지수 하나": bt.pct_score(raw["설문_매수우위"]),
}
starts = pd.date_range("2008-01-01", "2020-01-01", freq="12MS")
rows = []
for n, s in cands.items():
    s = s.reindex(y.index)
    w = [bt.spearman(s[(s.index >= a) & (s.index < a + pd.DateOffset(years=5))].to_numpy(), y[(y.index >= a) & (y.index < a + pd.DateOffset(years=5))].to_numpy()) for a in starts]
    w = np.array(w)
    full = bt.spearman(s[s.index >= "2008-01-01"].to_numpy(), y[y.index >= "2008-01-01"].to_numpy())
    rows.append({"후보": n, "전체(2008~)": full, "5년구간 최저": np.nanmin(w), "중앙값": np.nanmedian(w), "0.3 미만 구간": int((w < 0.3).sum()), "구간수": len(w),
                 **{str(a.year): v for a, v in zip(starts, w)}})
pd.set_option("display.width", 260)
print(pd.DataFrame(rows).set_index("후보").round(2).to_string())

"""네이버 금융 월봉 (건설주 바스켓, KOSPI). 키 불필요."""
import json
import subprocess
from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent / "data" / "raw" / "market"
OUT.mkdir(parents=True, exist_ok=True)
TICKERS = {"현대건설": "000720", "GS건설": "006360", "대우건설": "047040", "계룡건설": "013580",
           "태영건설": "009410", "동부건설": "005960", "대림산업_DL": "000210"}


def monthly(path):
    url = f"https://api.stock.naver.com/chart/domestic/{path}/month?startDateTime=199801010000&endDateTime=202612310000"
    raw = subprocess.run(["curl", "-sS", "--http1.1", "-m", "120", url], capture_output=True).stdout
    rows = json.loads(raw)
    s = pd.Series({pd.Timestamp(r["localDate"]): float(r["closePrice"]) for r in rows})
    return s.sort_index()


if __name__ == "__main__":
    out = {k: monthly(f"item/{t}") for k, t in TICKERS.items()}
    out["KOSPI"] = monthly("index/KOSPI")
    for k, s in out.items():
        print(k, len(s), s.index.min().date(), s.index.max().date())
    df = pd.DataFrame(out)
    df.index = df.index.to_period("M").to_timestamp()
    df.to_csv(OUT / "stocks_monthly.csv")

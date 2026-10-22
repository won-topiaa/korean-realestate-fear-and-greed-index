"""구글 트렌드 (한국, 월간, 2004~오늘). 키 불필요하지만 429가 잦아 키워드별로 천천히 수집."""
import datetime as dt
import sys
import time
from pathlib import Path

import pandas as pd
from pytrends.request import TrendReq

OUT = Path(__file__).parent / "data" / "raw" / "trends"
KEYWORDS = ["아파트", "부동산", "집값", "청약", "급매", "미분양", "갭투자", "전세"]

if __name__ == "__main__":
    kws = sys.argv[1:] or KEYWORDS
    py = TrendReq(hl="ko-KR", tz=-540, timeout=(10, 60))
    for kw in kws:
        path = OUT / f"{kw}.csv"
        if path.exists():
            continue
        for attempt in range(4):
            try:
                py.build_payload([kw], timeframe=f"2004-01-01 {dt.date.today().isoformat()}", geo="KR")
                df = py.interest_over_time()
                df[[kw]].to_csv(path)
                print("OK", kw, len(df), df.index.min().date(), df.index.max().date(), flush=True)
                break
            except Exception as e:
                print("retry", kw, repr(e)[:120], flush=True)
                time.sleep(20 * (attempt + 1))
        time.sleep(8)

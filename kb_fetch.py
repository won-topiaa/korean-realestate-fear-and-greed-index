"""KB부동산 데이터허브(data-api.kbland.kr) 원자료 수집. 키 불필요, 응답은 data/raw/kb/*.json 에 캐시."""
import json
import sys
import time
import warnings
from pathlib import Path

import requests

warnings.filterwarnings("ignore")

BASE = "https://data-api.kbland.kr/bfmstat/weekMnthlyHuseTrnd/"
CACHE = Path(__file__).parent / "data" / "raw" / "kb"
CACHE.mkdir(parents=True, exist_ok=True)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://kbland.kr/",
    "Accept": "application/json",
}


def fetch(endpoint: str, params: dict, name: str, refresh: bool = False):
    path = CACHE / f"{name}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    last = None
    for attempt in range(6):
        try:
            r = requests.get(BASE + endpoint, params=params, headers=HEADERS, verify=False, timeout=90)
            r.raise_for_status()
            j = r.json()
            data = j["dataBody"]["data"]
            if not data:
                raise ValueError("빈 응답")
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False))
            tmp.replace(path)  # 다 받은 뒤에만 바꿔 씀
            time.sleep(1.5)
            return data
        except Exception as e:  # 연결 리셋이 잦아 재시도
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{name}: {last}")


JOBS = {
    # 시장동향 설문 (중개업소 대상)
    "매수우위_월간": ("maktTrnd", {"메뉴코드": "01", "월간주간구분코드": "01"}),
    "매수우위_주간": ("maktTrnd", {"메뉴코드": "01", "월간주간구분코드": "02"}),
    "매매거래활발_월간": ("maktTrnd", {"메뉴코드": "02", "월간주간구분코드": "01"}),
    "매매거래활발_주간": ("maktTrnd", {"메뉴코드": "02", "월간주간구분코드": "02"}),
    "전세수급_월간": ("maktTrnd", {"메뉴코드": "03", "월간주간구분코드": "01"}),
    "전세거래활발_월간": ("maktTrnd", {"메뉴코드": "04", "월간주간구분코드": "01"}),
    "매매가격전망_월간": ("maktTrnd", {"메뉴코드": "05", "월간주간구분코드": "01"}),
    "전세가격전망_월간": ("maktTrnd", {"메뉴코드": "06", "월간주간구분코드": "01"}),
    # 가격지수
    "아파트매매지수_월간": ("priceIndex", {"월간주간구분코드": "01", "매물종별구분": "01", "매매전세코드": "01", "기간": "99"}),
    "아파트매매지수_주간": ("priceIndex", {"월간주간구분코드": "02", "매물종별구분": "01", "매매전세코드": "01", "기간": "99"}),
    "아파트전세지수_월간": ("priceIndex", {"월간주간구분코드": "01", "매물종별구분": "01", "매매전세코드": "02", "기간": "99"}),
    "연립매매지수_월간": ("priceIndex", {"월간주간구분코드": "01", "매물종별구분": "08", "매매전세코드": "01", "기간": "99"}),
    "선도50": ("leadApt50Indx", {}),
    "전세가율_아파트": ("dealCntstTnantRato", {"매물종별구분": "01"}),
    "HAI": ("HAI", {}),
    "PIR": ("pir", {"메뉴코드": "01"}),
}

if __name__ == "__main__":
    names = sys.argv[1:] or list(JOBS)
    for n in names:
        ep, p = JOBS[n]
        try:
            d = fetch(ep, p, n)
            keys = list(d.keys()) if isinstance(d, dict) else type(d)
            print("OK  ", n, keys)
        except Exception as e:
            print("FAIL", n, e)

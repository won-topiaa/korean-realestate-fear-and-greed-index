"""청약홈 (한국부동산원) 분양정보·경쟁률 전체 수집 → data/raw/applyhome/*.json"""
import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "raw" / "applyhome"
OUT.mkdir(parents=True, exist_ok=True)
KEY = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().split())["DATA_GO_KR_KEY"]
APIS = {
    "APT_분양공고": "ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail",
    "APT_경쟁률": "ApplyhomeInfoCmpetRtSvc/v1/getAPTLttotPblancCmpet",
    "무순위_경쟁률": "ApplyhomeInfoCmpetRtSvc/v1/getRemndrLttotPblancCmpet",
    "무순위_분양공고": "ApplyhomeInfoDetailSvc/v1/getRemndrLttotPblancDetail",
}


def get(path, page, per=1000, **cond):
    q = {"page": page, "perPage": per, **{f"cond[{k}]": v for k, v in cond.items()}}
    url = f"https://api.odcloud.kr/api/{path}?serviceKey={KEY}&" + urllib.parse.urlencode(q)
    for attempt in range(5):
        out = subprocess.run(["curl", "-sS", "--http1.1", "-m", "120", url], capture_output=True, text=True)
        try:
            return json.loads(out.stdout)
        except json.JSONDecodeError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(out.stdout[:300].replace(KEY, "***"))


def fetch_all(name):
    path = OUT / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    rows, page = [], 1
    while True:
        j = get(APIS[name], page)
        if "data" not in j:
            raise RuntimeError(f"{name}: {str(j)[:200]}")
        rows += j["data"]
        print(f"{name} p{page} {len(rows)}/{j.get('totalCount')}", flush=True)
        if len(rows) >= j.get("totalCount", 0) or not j["data"]:
            break
        page += 1
        time.sleep(0.3)
    path.write_text(json.dumps(rows, ensure_ascii=False))
    return rows


if __name__ == "__main__":
    for n in sys.argv[1:] or APIS:
        r = fetch_all(n)
        print("==", n, len(r), "| 필드:", list(r[0].keys()) if r else None)

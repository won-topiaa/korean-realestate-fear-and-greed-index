"""한국부동산원 R-ONE Open API. 응답은 data/raw/reb/*.json 에 캐시 (키는 .env)."""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "data" / "raw" / "reb"
CACHE.mkdir(parents=True, exist_ok=True)
KEY = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().split())["REB_KEY"]
BASE = "https://www.reb.or.kr/r-one/openapi/"


def call(endpoint, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}{endpoint}?KEY={KEY}&Type=json&{q}"
    for attempt in range(5):
        out = subprocess.run(["curl", "-sS", "--http1.1", "-m", "120", url], capture_output=True, text=True)
        try:
            return json.loads(out.stdout)
        except json.JSONDecodeError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{endpoint} {params}: {out.stdout[:200]}")


def rows(j, name):
    blk = j.get(name)
    if not blk:
        return [], j.get("RESULT") or j
    return (blk[1]["row"] if len(blk) > 1 else []), blk[0]["head"]


def items(statbl_id):
    """통계표의 분류(지역 등)·항목 목록."""
    path = CACHE / f"items_{statbl_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    out = []
    for p in range(1, 50):
        r, head = rows(call("SttsApiTblItm.do", STATBL_ID=statbl_id, pIndex=p, pSize=1000), "SttsApiTblItm")
        out += r
        if len(r) < 1000:
            break
    path.write_text(json.dumps(out, ensure_ascii=False))
    return out


def data(statbl_id, cycle="MM", name=None, refresh=False, **filters):
    """통계 데이터 전체 (페이지 순회)."""
    path = CACHE / f"{name or statbl_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    out = []
    for p in range(1, 2000):
        r, head = rows(call("SttsApiTblData.do", STATBL_ID=statbl_id, DTACYCLE_CD=cycle, pIndex=p, pSize=1000, **filters), "SttsApiTblData")
        out += r
        if len(r) < 1000:
            break
        time.sleep(0.3)
    path.write_text(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    for sid in sys.argv[1:]:
        its = items(sid)
        print("=====", sid, len(its))
        for it in its[:60]:
            print({k: v for k, v in it.items() if k in ("ITM_ID", "ITM_NM", "PAR_ITM_ID", "ITM_TAG", "ITM_FULLNM", "UI_NM", "UI_ID")})

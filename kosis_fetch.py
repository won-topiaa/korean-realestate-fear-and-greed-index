"""KOSIS Open API. 응답은 data/raw/kosis/*.json 에 캐시 (키는 .env)."""
import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "data" / "raw" / "kosis"
CACHE.mkdir(parents=True, exist_ok=True)
KEY = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().split())["KOSIS_KEY"]
BASE = "https://kosis.kr/openapi/"


def call(path, **params):
    q = urllib.parse.urlencode({"apiKey": KEY, "format": "json", "jsonVD": "Y", **params})
    for attempt in range(5):
        out = subprocess.run(["curl", "-sS", "-m", "120", f"{BASE}{path}?{q}"], capture_output=True, text=True)
        try:
            j = json.loads(out.stdout)
        except json.JSONDecodeError:
            time.sleep(3 * (attempt + 1))
            continue
        if isinstance(j, dict) and j.get("err"):
            raise RuntimeError(f"{params.get('tblId')}: {j.get('err')} {j.get('errMsg')}")
        return j
    raise RuntimeError(f"{params.get('tblId')}: {out.stdout.replace(KEY, '***')[:200]}")  # 키를 지운 뒤 자름


def meta(org, tbl, kind="ITM"):
    """통계표의 항목·분류 목록 (kind: ITM, PRD, TBL, UNIT …)."""
    return call("statisticsData.do", method="getMeta", type=kind, orgId=org, tblId=tbl)


def data(org, tbl, name, prd="M", start="200001", end="209912", refresh=False, **objs):
    """통계표 자료 (objL1·objL2·itmId 기본은 ALL)."""
    path = CACHE / f"{name}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    p = {"itmId": "ALL", "objL1": "ALL", **objs}
    rows = call("Param/statisticsParameterData.do", method="getList", orgId=org, tblId=tbl, prdSe=prd, startPrdDe=start, endPrdDe=end, **p)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False))
    tmp.replace(path)
    return rows


if __name__ == "__main__":
    org, tbl = sys.argv[1], sys.argv[2]
    for it in meta(org, tbl):
        print({k: v for k, v in it.items() if k in ("OBJ_ID", "OBJ_NM", "ITM_ID", "ITM_NM", "UP_ITM_ID", "UNIT_NM")})

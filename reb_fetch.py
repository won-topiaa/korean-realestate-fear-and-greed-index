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
    raise RuntimeError(f"{endpoint} {params}: {out.stdout.replace(KEY, '***')[:200]}")  # 키를 지운 뒤에 자른다 (오류 화면이 요청 주소를 되풀이할 때)


def rows(j, name):
    """(행, {code, msg, total}). 오류 응답은 데이터 블록 없이 RESULT만 온다."""
    blk = j.get(name)
    if not blk:
        res = j.get("RESULT") or {}
        return [], {"code": res.get("CODE"), "msg": res.get("MESSAGE"), "total": None}
    head = blk[0]["head"]
    total = next((h["list_total_count"] for h in head if "list_total_count" in h), None)
    res = next((h["RESULT"] for h in head if "RESULT" in h), {})
    return (blk[1]["row"] if len(blk) > 1 else []), {"code": res.get("CODE"), "msg": res.get("MESSAGE"), "total": total}


def _save(path, rows_):
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows_, ensure_ascii=False))
    tmp.replace(path)  # 다 받은 뒤에만 바꿔 씀 (중간에 끊겨도 지난 파일 유지)


def items(statbl_id):
    """통계표의 분류(지역 등)·항목 목록."""
    path = CACHE / f"items_{statbl_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    out = []
    for p in range(1, 50):
        r, h = rows(call("SttsApiTblItm.do", STATBL_ID=statbl_id, pIndex=p, pSize=1000), "SttsApiTblItm")
        if h["code"] != "INFO-000":
            if h["code"] == "INFO-200" and out:
                break
            raise RuntimeError(f"{statbl_id} 항목 {p}쪽: {h['code']} {h['msg']}")
        out += r
        if len(r) < 1000:
            break
    _save(path, out)
    return out


def data(statbl_id, cycle="MM", name=None, refresh=False, **filters):
    """통계 데이터 전체 (페이지 순회)."""
    path = CACHE / f"{name or statbl_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    out, total = [], None
    for p in range(1, 2000):
        r, h = rows(call("SttsApiTblData.do", STATBL_ID=statbl_id, DTACYCLE_CD=cycle, pIndex=p, pSize=1000, **filters), "SttsApiTblData")
        if h["code"] == "INFO-200" and total is not None and len(out) >= total:
            break  # 1,000건으로 딱 나눠떨어질 때 마지막 다음 쪽
        if h["code"] != "INFO-000":
            raise RuntimeError(f"{name or statbl_id} {p}쪽: {h['code']} {h['msg']}")
        total = h["total"] if total is None else total
        out += r
        if len(r) < 1000 or (total is not None and len(out) >= total):
            break
        time.sleep(0.3)
    if total is None or len(out) != total:
        raise RuntimeError(f"{name or statbl_id}: {len(out)}/{total}건만 받음 (지난 파일 유지)")
    _save(path, out)
    return out


if __name__ == "__main__":
    for sid in sys.argv[1:]:
        its = items(sid)
        print("=====", sid, len(its))
        for it in its[:60]:
            print({k: v for k, v in it.items() if k in ("ITM_ID", "ITM_NM", "PAR_ITM_ID", "ITM_TAG", "ITM_FULLNM", "UI_NM", "UI_ID")})

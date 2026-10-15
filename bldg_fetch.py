"""건축물대장(국토부 건축HUB) → 단지 기본정보 data/molit/buildings.csv
(세대수·동수·용적률·건폐율·대지·연면적·주차·사용승인일·최고층).

실거래 단지 표(complexes.csv)의 시군구·법정동·본번·부번으로 조회한다 (이름으로 어림잡아 맞추지 않음).
총괄표제부(단지 전체)가 있으면 그 값을, 없으면 표제부(동별)를 합친다. 최고층은 표제부에서.
처음엔 9천여 단지라 여러 번에 나눠 받고(받은 만큼 바로 저장), 이후엔 새 단지만 받는다.
data.go.kr에서 '국토교통부_건축HUB_건축물대장정보 서비스' 활용신청이 필요하다 (키는 DATA_GO_KR_KEY 그대로).

사용: python bldg_fetch.py [최대 단지 수]
"""
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

import molit_store

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "molit" / "buildings.csv"
URL = "https://apis.data.go.kr/1613000/BldRgstHubService"
COLS = ["aptSeq", "hhld", "dong", "vlRat", "bcRat", "platArea", "totArea", "pkng", "useApr", "maxFlr", "src", "fetched", "status"]
APT = ("공동주택", "아파트")


class NotRegistered(Exception):
    pass


class QuotaExceeded(Exception):
    pass


def _key():
    env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().split() if "=" in l)
    return env["DATA_GO_KR_KEY"].strip()


def call(op, params, key):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{URL}/{op}?serviceKey={key}&{q}&numOfRows=100&pageNo=1&_type=json"
    for attempt in range(4):
        out = subprocess.run(["curl", "-sS", "--http1.1", "-m", "30", url], capture_output=True, text=True).stdout
        try:
            d = json.loads(out)
            break
        except json.JSONDecodeError:
            if "SERVICE_KEY_IS_NOT_REGISTERED" in out:
                raise NotRegistered
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in out:
                raise QuotaExceeded
            time.sleep(2 * 2 ** attempt)
    else:
        raise RuntimeError(f"{op}: 응답 해석 실패 · {out.replace(key, '***')[:120]}")
    err = d.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader")
    if err:
        code = str(err.get("returnReasonCode", ""))
        if code == "30" or "NOT_REGISTERED" in str(err.get("errMsg", "")):
            raise NotRegistered
        if code == "22":
            raise QuotaExceeded
        raise RuntimeError(f"{op}: {err.get('errMsg')}")
    resp = d.get("response", {})
    code = str(resp.get("header", {}).get("resultCode", ""))
    if code not in ("00", "000"):
        if code == "22":
            raise QuotaExceeded
        raise RuntimeError(f"{op}: code {code} {resp.get('header', {}).get('resultMsg')}")
    items = (resp.get("body", {}) or {}).get("items") or {}
    items = items.get("item", []) if isinstance(items, dict) else []
    return [items] if isinstance(items, dict) else items


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def lot(row, umd):
    """complexes.csv 한 줄 → 건축물대장 조회 값. 법정동 코드가 없으면 같은 구의 동 이름으로 찾는다."""
    sgg = row["aptSeq"][:5]
    bj = row["umdCd"] or umd.get((sgg, row["umdNm"]), "")
    if row["bonbun"]:
        bun, ji, gb = row["bonbun"], row["bubun"] or "0000", "0"
    else:
        m = re.fullmatch(r"(산)?\s*(\d+)(?:-(\d+))?", row["jibun"].strip())
        if not m:
            return None
        gb, bun, ji = ("1" if m.group(1) else "0"), m.group(2).zfill(4), (m.group(3) or "0").zfill(4)
    if not bj:
        return None
    return {"sigunguCd": sgg, "bjdongCd": bj, "platGbCd": gb, "bun": bun, "ji": ji}


def fetch_one(params, key):
    recap = call("getBrRecapTitleInfo", params, key)
    titles = call("getBrTitleInfo", params, key)
    apt = [t for t in titles if any(a in str(t.get("mainPurpsCdNm", "")) for a in APT)] or titles
    r = {"maxFlr": int(max([num(t.get("grndFlrCnt")) for t in apt] or [0])) or ""}
    if recap:
        c = max(recap, key=lambda x: num(x.get("hhldCnt")))
        r.update(src="총괄표제부", hhld=num(c.get("hhldCnt")), dong=num(c.get("mainBldCnt")), vlRat=num(c.get("vlRat")),
                 bcRat=num(c.get("bcRat")), platArea=num(c.get("platArea")), totArea=num(c.get("totArea")),
                 pkng=num(c.get("totPkngCnt")), useApr=str(c.get("useAprDay") or "").strip())
    elif apt:
        first = next((t for t in apt if num(t.get("vlRat"))), apt[0])
        pk = sum(num(t.get(k)) for t in apt for k in ("indrMechUtcnt", "oudrMechUtcnt", "indrAutoUtcnt", "oudrAutoUtcnt"))
        r.update(src="표제부", hhld=sum(num(t.get("hhldCnt")) for t in apt), dong=len(apt), vlRat=num(first.get("vlRat")),
                 bcRat=num(first.get("bcRat")), platArea=num(first.get("platArea")), totArea=sum(num(t.get("totArea")) for t in apt),
                 pkng=pk, useApr=min((str(t.get("useAprDay") or "").strip() for t in apt if t.get("useAprDay")), default=""))
    else:
        return None
    for k in ("hhld", "dong", "pkng", "platArea", "totArea"):
        r[k] = int(round(r[k])) or ""
    for k in ("vlRat", "bcRat"):
        r[k] = round(r[k], 1) or ""
    return r


def save(rows):
    df = pd.DataFrame(rows).reindex(columns=COLS).fillna("").sort_values("aptSeq")
    tmp = OUT.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(OUT)


def run(limit=None, budget_s=None):
    """아직 안 받은 단지를 최근 거래 순으로 받는다. 반환: 요약 문장."""
    key = _key()
    cx = molit_store.load_complexes()
    umd = {(r.aptSeq[:5], r.umdNm): r.umdCd for r in cx.itertuples() if r.umdCd}
    old = pd.read_csv(OUT, dtype=str, keep_default_na=False) if OUT.exists() else pd.DataFrame(columns=COLS)
    rows = {r["aptSeq"]: r for r in old.to_dict("records")}
    todo = [r for r in cx.sort_values("last", ascending=False).to_dict("records")
            if rows.get(r["aptSeq"], {}).get("status") not in ("ok", "none")]
    if limit:
        todo = todo[:limit]
    t0, done, ok, nocode = time.time(), 0, 0, 0
    today = dt.date.today().isoformat()
    try:
        for r in todo:
            if budget_s and time.time() - t0 > budget_s:
                break
            p = lot(r, umd)
            if p is None:
                rows[r["aptSeq"]] = {"aptSeq": r["aptSeq"], "fetched": today, "status": "nocode"}
                nocode += 1
                continue
            got = fetch_one(p, key)
            rows[r["aptSeq"]] = {"aptSeq": r["aptSeq"], **(got or {}), "fetched": today, "status": "ok" if got else "none"}
            done += 1
            ok += bool(got)
            if done % 50 == 0:
                save(list(rows.values()))
            time.sleep(0.1)
    except NotRegistered:
        return "건축물대장: 활용신청 전이라 건너뜀 (data.go.kr '국토교통부_건축HUB_건축물대장정보 서비스')"
    except QuotaExceeded:
        save(list(rows.values()))
        return f"건축물대장: 하루 호출 한도 — {done}곳 받고 중단 (다음 실행에 이어받음)"
    finally:
        if done:
            save(list(rows.values()))
    have = sum(1 for v in rows.values() if v.get("status") == "ok")
    left = sum(1 for r in cx["aptSeq"] if rows.get(r, {}).get("status") not in ("ok", "none"))
    return f"건축물대장: 이번에 {done}곳 조회 ({ok}곳 찾음, 주소 코드 없음 {nocode}) · 전체 {have:,}곳 보유 · 남은 단지 {left:,}"


if __name__ == "__main__":
    print(run(int(sys.argv[1]) if len(sys.argv) > 1 else None))

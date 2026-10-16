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
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

import molit_store

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "molit" / "buildings.csv"
BJ = ROOT / "data" / "molit" / "bjdong.csv"  # 서울 법정동 코드표 (구·동 이름 → 코드)
URL = "https://apis.data.go.kr/1613000/BldRgstHubService"
COLS = ["aptSeq", "lot", "via", "regNm", "hhld", "dong", "vlRat", "bcRat", "platArea", "totArea", "pkng", "useApr", "maxFlr", "src", "fetched", "status"]
APT = ("공동주택", "아파트")


class NotRegistered(Exception):
    pass


class QuotaExceeded(Exception):
    pass


def _key():
    env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().split() if "=" in l)
    return env["DATA_GO_KR_KEY"].strip()


def call(op, params, key, page=1, rows=100, maxpage=10, _try=0):
    """한 페이지(rows건) 조회. 더 있으면 maxpage까지 다음 페이지를 이어 붙인다 (동이 많은 대단지)."""
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{URL}/{op}?serviceKey={key}&{q}&numOfRows={rows}&pageNo={page}&_type=json"
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
        if "PER_SECOND" in str(err.get("errMsg", "")) and _try < 10:  # 초당 한도: 잠깐 쉬고 다시
            time.sleep(1 + _try)
            return call(op, params, key, page, rows, maxpage, _try + 1)
        raise RuntimeError(f"{op}: {err.get('errMsg')}")
    resp = d.get("response", {})
    code = str(resp.get("header", {}).get("resultCode", ""))
    if code not in ("00", "000"):
        if code == "22":
            raise QuotaExceeded
        raise RuntimeError(f"{op}: code {code} {resp.get('header', {}).get('resultMsg')}")
    body = resp.get("body", {}) or {}
    items = body.get("items") or {}
    items = items.get("item", []) if isinstance(items, dict) else []
    items = [items] if isinstance(items, dict) else items
    if page * rows < int(num(body.get("totalCount"))) and page < maxpage:
        items += call(op, params, key, page + 1, rows, maxpage)
    return items


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
        bun, ji, gb = row["bonbun"], row["bubun"] or "0000", "1" if row["jibun"].strip().startswith("산") else "0"
    else:
        m = re.fullmatch(r"(산)?\s*(\d+)(?:-(\d+))?", row["jibun"].strip())
        if not m:
            return None
        gb, bun, ji = ("1" if m.group(1) else "0"), m.group(2).zfill(4), (m.group(3) or "0").zfill(4)
    if not bj:
        return None
    return {"sigunguCd": sgg, "bjdongCd": bj, "platGbCd": gb, "bun": bun, "ji": ji}


def fetch_one(params, key):
    """총괄표제부(단지 전체) 값을 쓰고, 비어 있는 칸(오래된 구대장은 대지면적·용적률 등이 0)은 표제부(동별)로 채운다.
    동수는 세대가 있는 동만 센다 (총괄표제부의 주건축물 수엔 상가·경비실·주차장이 들어간다)."""
    recap = call("getBrRecapTitleInfo", params, key)
    titles = call("getBrTitleInfo", params, key)
    if not recap and not titles:
        return None
    homes = [t for t in titles if num(t.get("hhldCnt")) > 0]
    apt = homes or [t for t in titles if any(a in str(t.get("mainPurpsCdNm", "")) for a in APT)] or titles
    c = max(recap, key=lambda x: num(x.get("hhldCnt"))) if recap else {}
    one = apt[0] if len(apt) == 1 else {}  # 총괄표제부가 없는 한 동짜리 단지는 그 동의 값이 곧 단지 값
    pk = ("indrMechUtcnt", "oudrMechUtcnt", "indrAutoUtcnt", "oudrAutoUtcnt")
    plat = num(c.get("platArea")) or num(one.get("platArea"))
    est = num(c.get("vlRatEstmTotArea")) or num(one.get("vlRatEstmTotArea"))
    arch = num(c.get("archArea")) or num(one.get("archArea"))
    days = [str(t.get("useAprDay") or "").strip() for t in apt]
    r = {
        "src": "총괄표제부" if c else "표제부",
        "regNm": str(c.get("bldNm") or (apt[0].get("bldNm") if apt else "") or "").strip(),
        "hhld": num(c.get("hhldCnt")) or sum(num(t.get("hhldCnt")) for t in titles),
        "dong": len(homes) or num(c.get("mainBldCnt")),
        "vlRat": num(c.get("vlRat")) or num(one.get("vlRat")) or (est / plat * 100 if plat and est else 0),
        "bcRat": num(c.get("bcRat")) or num(one.get("bcRat")) or (arch / plat * 100 if plat and arch else 0),
        "platArea": plat,
        "totArea": num(c.get("totArea")) or sum(num(t.get("totArea")) for t in apt),
        "pkng": (num(c.get("totPkngCnt")) or sum(num(c.get(k)) for k in pk)) if c else sum(num(one.get(k)) for k in pk),
        "useApr": str(c.get("useAprDay") or "").strip() or min((d for d in days if len(d) == 8), default=""),
        "maxFlr": max([num(t.get("grndFlrCnt")) for t in apt] or [0]),
    }
    if not r["hhld"]:
        return None  # 세대가 하나도 없으면 아파트 대장이 아니다 (상가 등)
    # 대장 입력 오류 걸러내기 (예: 연면적이 세대당 수천㎡)
    if r["totArea"] > 1000 * r["hhld"]:
        r["totArea"] = 0
    if not 0 < r["vlRat"] <= 1500:
        r["vlRat"] = 0
    if not 0 < r["bcRat"] <= 100:
        r["bcRat"] = 0
    for k in ("hhld", "dong", "pkng", "platArea", "totArea", "maxFlr"):
        r[k] = int(round(r[k])) or ""
    for k in ("vlRat", "bcRat"):
        r[k] = round(r[k], 1) or ""
    return r


def bjdong_codes(key, cx):
    """(구 코드, 동 이름) → 법정동 코드. 실거래 자료에 있는 것 + 코드표(없으면 건축물대장에 동 코드를 하나씩 물어 만든다)."""
    umd = {(r.aptSeq[:5], r.umdNm): r.umdCd for r in cx.itertuples() if r.umdCd}
    need = {(r.aptSeq[:5], r.umdNm) for r in cx.itertuples()} - set(umd)
    if not BJ.exists() and need:
        def probe(sc):
            for op in ("getBrRecapTitleInfo", "getBrTitleInfo"):
                for it in call(op, {"sigunguCd": sc[0], "bjdongCd": sc[1]}, key, rows=5, maxpage=1):
                    w = str(it.get("platPlc") or "").split()
                    if len(w) >= 3 and w[0].startswith("서울"):
                        return sc[0], w[2], sc[1]
            return None

        def scan(g):  # 10100부터 100씩 올리며 묻고, 20개 연달아 비면 그 구는 끝
            out, miss = [], 0
            for c in range(101, 200):
                x = probe((g, f"{c}00"))
                out += [x] if x else []
                miss = 0 if x else miss + 1
                if miss >= 20:
                    break
                time.sleep(0.1)
            return out
        with ThreadPoolExecutor(2) as ex:
            got = [x for xs in ex.map(scan, sorted({k[0] for k in need})) for x in xs]
        pd.DataFrame(got, columns=["sgg", "name", "bjdong"]).drop_duplicates(["sgg", "name"]).to_csv(BJ, index=False)
    if BJ.exists():
        for r in pd.read_csv(BJ, dtype=str).itertuples():
            umd.setdefault((r.sgg, r.name), r.bjdong)
    return umd


def _nm(s):
    s = re.sub(r"\(.*?\)", "", str(s or ""))
    return re.sub(r"[\s·.,\-_'’]|아파트", "", s).lower()


def name_match(names, items):
    """단지 이름(옛 이름 포함)과 가장 비슷한 대장 한 건. 숫자(2차·3단지 등)가 다르면 다른 단지로 본다."""
    best, top = None, 0.0
    for it in items:
        n2 = _nm(it.get("bldNm"))
        if len(n2) < 2:
            continue
        for n1 in names:
            if len(n1) < 2 or re.sub(r"\D", "", n1) != re.sub(r"\D", "", n2):
                continue
            sc = 1.0 if n1 == n2 else 0.9 if min(len(n1), len(n2)) >= 3 and (n1 in n2 or n2 in n1) else SequenceMatcher(None, n1, n2).ratio()
            if sc > top:
                best, top = it, sc
    return best if top >= 0.85 else None


def fill(workers=2, budget_s=None, retry_days=90):
    """지번으로 못 찾은 단지를 그 동네 건축물대장 전체에서 이름으로 다시 찾는다 (총괄표제부 → 표제부 순).
    이름으로도 없으면 status=missing (새 단지는 대장에 늦게 올라오므로 retry_days 뒤 다시 찾는다)."""
    key = _key()
    cx = molit_store.load_complexes().set_index("aptSeq")
    umd = bjdong_codes(key, cx.reset_index())
    old = pd.read_csv(OUT, dtype=str, keep_default_na=False)
    rows = {r["aptSeq"]: r for r in old.to_dict("records")}
    cut = (dt.date.today() - dt.timedelta(days=retry_days)).isoformat()
    miss = [s for s, r in rows.items() if s in cx.index and
            (r["status"] in ("none", "nocode", "error") or (r["status"] == "missing" and r["fetched"] < cut))]
    today = dt.date.today().isoformat()
    cache = {}

    def area_items(op, sgg, bj):
        k = (op, sgg, bj)
        if k not in cache:  # 동네 전체 목록 (표제부는 너무 많으면 앞 2,000건까지만)
            cache[k] = call(op, {"sigunguCd": sgg, "bjdongCd": bj}, key, maxpage=80 if op == "getBrRecapTitleInfo" else 20)
        return cache[k]

    def one(seq):
        c = cx.loc[seq]
        bj = c["umdCd"] or umd.get((seq[:5], c["umdNm"]), "")
        if not bj:
            return seq, None, "nocode"
        p = lot({**c.to_dict(), "aptSeq": seq}, umd)
        got = fetch_one(p, key) if p else None  # 코드표로 동 코드가 새로 생긴 단지는 지번으로 먼저
        if got:
            got.update(lot="-".join(p.values()), via="지번")
            return seq, got, "ok"
        names = [_nm(n) for n in [c["aptNm"], *str(c["names"]).split("|")] if n]
        for op in ("getBrRecapTitleInfo", "getBrTitleInfo"):
            items = area_items(op, seq[:5], bj)
            if op == "getBrTitleInfo":
                items = [t for t in items if num(t.get("hhldCnt")) > 0]
            m = name_match(names, items)
            if m:
                q = {k: str(m[k]) for k in ("sigunguCd", "bjdongCd", "platGbCd", "bun", "ji")}
                got = fetch_one(q, key)
                if got:
                    got.update(lot="-".join(q.values()), via="이름")
                    return seq, got, "ok"
        return seq, None, "missing"

    miss.sort(key=lambda s: (s[:5], cx.loc[s, "umdNm"]))  # 같은 동네끼리 붙여서 (동네 목록을 한 번만 받게)
    t0, done, found, msg = time.time(), 0, 0, ""
    try:
        with ThreadPoolExecutor(workers) as ex:
            for i in range(0, len(miss), 20):
                if budget_s and time.time() - t0 > budget_s:
                    msg = " (시간 한도로 중단, 다음 실행에 이어서)"
                    break
                for seq, got, status in ex.map(one, miss[i:i + 20]):
                    rows[seq] = {"aptSeq": seq, **(got or {}), "fetched": today, "status": status}
                    done += 1
                    found += status == "ok"
                save(list(rows.values()))
    except QuotaExceeded:
        msg = " (하루 호출 한도로 중단, 다음 실행에 이어서)"
    save(list(rows.values()))
    left = sum(1 for r in rows.values() if r["status"] != "ok")
    return f"건축물대장 다시 찾기: {done}/{len(miss)}곳 확인, {found}곳 찾음{msg} · 아직 정보 없는 단지 {left}"


def save(rows):
    df = pd.DataFrame(rows).reindex(columns=COLS).fillna("").astype(str).sort_values("aptSeq")
    df = df.apply(lambda c: c.str.replace(r"\.0$", "", regex=True))  # 정수가 84.0으로 저장되지 않게
    tmp = OUT.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(OUT)


def run(limit=None, budget_s=None, workers=4):
    """아직 안 받은 단지를 최근 거래 순으로 받는다 (workers곳씩 동시에). 반환: 요약 문장."""
    key = _key()
    cx = molit_store.load_complexes()
    umd = bjdong_codes(key, cx)
    old = pd.read_csv(OUT, dtype=str, keep_default_na=False) if OUT.exists() else pd.DataFrame(columns=COLS)
    rows = {r["aptSeq"]: r for r in old.to_dict("records")}
    todo = [r for r in cx.sort_values("last", ascending=False).to_dict("records")
            if rows.get(r["aptSeq"], {}).get("status") not in ("ok", "none", "missing")]
    if limit:
        todo = todo[:limit]
    t0, done, ok, nocode, err = time.time(), 0, 0, 0, 0
    today = dt.date.today().isoformat()

    def one(r):
        p = lot(r, umd)
        if p is None:
            return r["aptSeq"], None, "nocode"
        try:
            got = fetch_one(p, key)
        except RuntimeError:  # 한 단지의 이상한 응답 때문에 전체를 멈추지 않는다 (다음 실행에 다시 시도)
            return r["aptSeq"], None, "error"
        if got:
            got.update(lot="-".join(p.values()), via="지번")
        return r["aptSeq"], got, "ok" if got else "none"

    try:
        with ThreadPoolExecutor(workers) as ex:
            for i in range(0, len(todo), 50):
                if budget_s and time.time() - t0 > budget_s:
                    break
                for seq, got, status in ex.map(one, todo[i:i + 50]):
                    rows[seq] = {"aptSeq": seq, **(got or {}), "fetched": today, "status": status}
                    nocode += status == "nocode"
                    err += status == "error"
                    done += status not in ("nocode", "error")
                    ok += status == "ok"
                save(list(rows.values()))
    except NotRegistered:
        return "건축물대장: 활용신청 전이라 건너뜀 (data.go.kr '국토교통부_건축HUB_건축물대장정보 서비스')"
    except QuotaExceeded:
        save(list(rows.values()))
        return f"건축물대장: 하루 호출 한도 — {done}곳 받고 중단 (다음 실행에 이어받음)"
    have = sum(1 for v in rows.values() if v.get("status") == "ok")
    left = sum(1 for r in cx["aptSeq"] if rows.get(r, {}).get("status") not in ("ok", "none", "missing"))
    return f"건축물대장: 이번에 {done}곳 조회 ({ok}곳 찾음, 주소 코드 없음 {nocode}, 오류 {err}) · 전체 {have:,}곳 보유 · 남은 단지 {left:,}"


if __name__ == "__main__":
    if sys.argv[1:] == ["fill"]:
        print(fill())
    else:
        print(run(int(sys.argv[1]) if len(sys.argv) > 1 else None))

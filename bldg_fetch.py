"""건축물대장(국토부 건축HUB) → 단지 기본정보 data/molit/buildings.csv
(세대수·동수·용적률·건폐율·대지·연면적·주차·사용승인일·최고층).

실거래 단지 표(complexes.csv)의 시군구·법정동·본번·부번으로 조회한다 (이름으로 어림잡아 맞추지 않음).
총괄표제부(단지 전체)가 있으면 그 값을, 없으면 표제부(동별)를 합친다. 최고층은 표제부에서.
처음엔 9천여 단지라 여러 번에 나눠 받고(받은 만큼 바로 저장), 이후엔 새 단지만 받는다.
data.go.kr에서 '국토교통부_건축HUB_건축물대장정보 서비스' 활용신청이 필요하다 (키는 DATA_GO_KR_KEY 그대로).
수도권·광역시(--regions): 지역 단지 표(data/molit_kr/complexes.csv) → data/molit_kr/buildings.csv. 건축물대장은 지금 지역 코드를
쓰므로(2026-10 확인: 광주 충장고운라피네는 옛 29110으로는 없고 12210으로 나옴) 그 단지 거래가 들어온 지금 코드로 먼저 묻고,
없으면 단지 번호 앞자리(옛 코드)로 한 번 더 묻는다.

사용: python bldg_fetch.py [--regions] [최대 단지 수]
      python bldg_fetch.py fill|land [--regions]
"""
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pandas as pd

import molit_store

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "molit" / "buildings.csv"
OUT_KR = ROOT / "data" / "molit_kr" / "buildings.csv"  # 수도권·광역시
BJ = ROOT / "data" / "molit" / "bjdong.csv"  # 서울 법정동 코드표 (구·동 이름 → 코드)
URL = "https://apis.data.go.kr/1613000/BldRgstHubService"
COLS = ["aptSeq", "lot", "via", "regNm", "hhld", "dong", "vlRat", "bcRat", "platArea", "totArea", "pkng", "useApr", "maxFlr", "src", "landSrc", "fetched", "status"]
VW = "https://api.vworld.kr/ned/data/ladfrlList"  # 브이월드 토지임야목록 (토지대장 면적)
APT = ("공동주택", "아파트")


class NotRegistered(Exception):
    pass


class Stop(Exception):
    """이번 실행을 멈추고 다음 실행에 이어서 (받은 만큼은 저장돼 있다)."""


class QuotaExceeded(Stop):
    pass


class TimeUp(Stop):
    pass


class Unreachable(Stop):
    pass


# call()이 호출마다 확인: 이번 실행의 마감 시각 · 멈춘 까닭(한 스레드가 멈추면 나머지도 다음 호출에서 같이 멈춤) · 응답을 연달아 못 받은 호출 수
# · 하루 한도가 찬 기능 {op: 까닭} (data.go.kr 하루 한도는 기능마다 따로라 그 기능만 막는다: 용적률 단계가 총괄표제부 한도에도 층별개요로 어림하게)
_until, _stop, _bad, _quota = None, None, 0, {}
BAD_MAX = 8  # 이만큼 연달아 응답이 이상하면 서버 문제로 보고 멈춘다 (2026-10-21: 응답 없는 서버에 단지 150곳을 붙잡고 98분, 시간 한도도 넘김)


def start(budget_s=None):
    """이번 실행의 마감. 응답이 느려도 단지 묶음 사이가 아니라 호출마다 확인해 마감을 넘기지 않는다."""
    global _until, _stop, _bad, _quota
    _until, _stop, _bad, _quota = (time.time() + budget_s if budget_s else None), None, 0, {}


def halt(e, op=None):
    """op를 주면(하루 한도) 그 기능만, 아니면(시간·서버) 이번 실행의 모든 호출을 멈춘다."""
    global _stop
    if op:
        _quota[op] = e
    else:
        _stop = e
    raise e


def bad(msg):
    """응답 이상 한 번이면 그 단지만 건너뛰게 RuntimeError, BAD_MAX번 연달아면 이번 실행을 멈춘다."""
    global _bad
    _bad += 1
    if _bad >= BAD_MAX:
        halt(Unreachable(f"{msg} ({_bad}번 연달아)"))
    raise RuntimeError(msg)


def why(e):
    return {QuotaExceeded: "하루 호출 한도", TimeUp: "시간 한도", NotRegistered: "인증키 오류(활용신청 확인)"}.get(type(e), "서버 오류")


def _env():
    return dict(l.split("=", 1) for l in (ROOT / ".env").read_text().split() if "=" in l)


def _key():
    return _env()["DATA_GO_KR_KEY"].strip()


def call(op, params, key, page=1, rows=100, maxpage=10, _try=0):
    """한 페이지(rows건) 조회. 더 있으면 maxpage까지 다음 페이지를 이어 붙인다 (동이 많은 대단지)."""
    global _bad
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{URL}/{op}?serviceKey={key}&{q}&numOfRows={rows}&pageNo={page}&_type=json"
    for attempt in range(4):
        if _stop:
            raise type(_stop)(*_stop.args)
        if op in _quota:
            raise QuotaExceeded(*_quota[op].args)
        if _until and time.time() > _until:
            halt(TimeUp(f"{op}: 시간 한도"))
        out = subprocess.run(["curl", "-sS", "--http1.1", "-m", "30", url], capture_output=True, text=True).stdout
        try:
            d = json.loads(out)
            break
        except json.JSONDecodeError:
            if "SERVICE_KEY_IS_NOT_REGISTERED" in out:
                raise NotRegistered(f"{op}: SERVICE_KEY_IS_NOT_REGISTERED")
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in out:
                halt(QuotaExceeded(f"{op}: LIMITED_NUMBER_OF_SERVICE_REQUESTS"), op)
            time.sleep(2 * 2 ** attempt)
    else:
        bad(f"{op}: 응답 해석 실패 · {out.replace(key, '***')[:120]}")
    err = d.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader")
    if err:
        code = str(err.get("returnReasonCode", ""))
        if code == "30" or "NOT_REGISTERED" in str(err.get("errMsg", "")):
            raise NotRegistered(f"{op}: code {code} {err.get('errMsg')}")
        if code == "22":
            halt(QuotaExceeded(f"{op}: {err.get('errMsg')}"), op)
        if "PER_SECOND" in str(err.get("errMsg", "")):
            if _try < 5:  # 초당 한도: 잠깐 쉬고 다시 (1+2+3+4+5초)
                time.sleep(1 + _try)
                return call(op, params, key, page, rows, maxpage, _try + 1)
            halt(QuotaExceeded(f"{op}: {err.get('errMsg')} (6번 연속)"), op)  # 계속이면 하루 한도가 찬 것 (서버가 하루 한도도 초당 한도로 답할 때가 있다) → 다음 실행에
        if "SERVICETIMEOUT" in str(err.get("errMsg", "")) and _try < 3:  # 대장 서버가 바쁠 때 (2026-10-23 부속지번 조회가 연달아): 쉬었다 다시 (2+4+6초)
            time.sleep(2 + 2 * _try)
            return call(op, params, key, page, rows, maxpage, _try + 1)
        bad(f"{op}: {err.get('errMsg')}")
    resp = d.get("response", {})
    code = str(resp.get("header", {}).get("resultCode", ""))
    if code not in ("00", "000"):
        if code == "22":
            halt(QuotaExceeded(f"{op}: code 22"), op)
        bad(f"{op}: code {code} {resp.get('header', {}).get('resultMsg')}")
    _bad = 0
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


def complexes(region=False):
    """단지 표 + 건축물대장 조회용 시군구 코드(sgg). 서울은 단지 번호 앞 5자리, 지역은 그 단지 거래가 가장 많이 들어온 지금 지역 코드
    (지역 저장소에 아직 없는 단지는 단지 번호 앞자리)."""
    if not region:
        cx = molit_store.load_complexes()
        return cx.assign(sgg=cx["aptSeq"].str[:5])
    import region_store
    cx = region_store.load_complexes()
    home = pd.Series(dtype=str)
    if region_store.exists():
        home = region_store.load().groupby("aptSeq")["lawd"].agg(lambda x: x.value_counts().index[0])
    return cx.assign(sgg=cx["aptSeq"].map(home).fillna(cx["aptSeq"].str[:5]))


def other_code(p, seq):
    """지금 코드로 없을 때 한 번 더 물을 옛 코드 조회 값 (같으면 None)."""
    return {**p, "sigunguCd": seq[:5]} if p and p["sigunguCd"] != seq[:5] else None


def lot(row, umd):
    """complexes.csv 한 줄 → 건축물대장 조회 값. 법정동 코드가 없으면 같은 구의 동 이름으로 찾는다."""
    sgg = row.get("sgg") or row["aptSeq"][:5]
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


def bjdong_codes(key, cx, region=False):
    """(구 코드, 동 이름) → 법정동 코드. 실거래 자료에 있는 것 + 코드표(없으면 건축물대장에 동 코드를 하나씩 물어 만든다, 서울만)."""
    umd = {(r.sgg, r.umdNm): r.umdCd for r in cx.itertuples() if r.umdCd}
    need = {(r.sgg, r.umdNm) for r in cx.itertuples()} - set(umd)
    if region:
        return umd
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


def fill(workers=2, budget_s=None, retry_days=90, region=False):
    """지번으로 못 찾은 단지를 그 동네 건축물대장 전체에서 이름으로 다시 찾는다 (총괄표제부 → 표제부 순).
    이름으로도 없으면 status=missing (새 단지는 대장에 늦게 올라오므로 retry_days 뒤 다시 찾는다)."""
    key = _key()
    start(budget_s)
    out = OUT_KR if region else OUT
    if not out.exists():
        return "건축물대장 다시 찾기: 아직 받은 단지 없음"
    cx = complexes(region).set_index("aptSeq")
    umd = bjdong_codes(key, cx.reset_index(), region)
    old = pd.read_csv(out, dtype=str, keep_default_na=False)
    rows = {r["aptSeq"]: r for r in old.to_dict("records")}
    cut = (dt.date.today() - dt.timedelta(days=retry_days)).isoformat()
    miss = [s for s, r in rows.items() if s in cx.index and
            (r["status"] in ("none", "nocode", "error") or (r["status"] == "missing" and r["fetched"] < cut))]
    today = dt.date.today().isoformat()
    cache, locks, guard = {}, {}, threading.Lock()

    def area_items(op, sgg, bj):
        k = (op, sgg, bj)
        with guard:
            lock = locks.setdefault(k, threading.Lock())
        with lock:  # 같은 동네의 두 단지가 동시에 와도 목록은 한 번만 받는다 (늦은 스레드는 기다렸다 캐시를 쓴다)
            if k not in cache:  # 동네 전체 목록 (표제부는 너무 많으면 앞 2,000건까지만)
                cache[k] = call(op, {"sigunguCd": sgg, "bjdongCd": bj}, key, maxpage=80 if op == "getBrRecapTitleInfo" else 20)
        return cache[k]

    def one(seq):
        try:
            return one_(seq)
        except RuntimeError:  # 한 단지의 이상한 응답 때문에 전체를 멈추지 않는다 (다음 실행에 다시)
            return seq, None, "error"

    def one_(seq):
        c = cx.loc[seq]
        bj = c["umdCd"] or umd.get((c["sgg"], c["umdNm"]), "")
        if not bj:
            return seq, None, "nocode"
        p = lot({**c.to_dict(), "aptSeq": seq}, umd)
        got = fetch_one(p, key) if p else None  # 코드표로 동 코드가 새로 생긴 단지는 지번으로 먼저
        if not got and other_code(p, seq):
            p = other_code(p, seq)
            got = fetch_one(p, key)
        if got:
            got.update(lot="-".join(p.values()), via="지번")
            return seq, got, "ok"
        names = [_nm(n) for n in [c["aptNm"], *str(c["names"]).split("|")] if n]
        for op in ("getBrRecapTitleInfo", "getBrTitleInfo"):
            items = area_items(op, c["sgg"], bj)
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

    miss.sort(key=lambda s: (cx.loc[s, "sgg"], cx.loc[s, "umdNm"]))  # 같은 동네끼리 붙여서 (동네 목록을 한 번만 받게)
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
                save(list(rows.values()), out)
    except (Stop, NotRegistered) as e:  # 인증키 오류도 받은 만큼 저장하고 끝낸다 (워크플로의 다음 단계가 돌게)
        msg = f" ({why(e)}로 중단, 다음 실행에 이어서)"
    save(list(rows.values()), out)
    left = sum(1 for r in rows.values() if r["status"] != "ok")
    return f"건축물대장 다시 찾기: {done}/{len(miss)}곳 확인, {found}곳 찾음{msg} · 아직 정보 없는 단지 {left}"


def land_area(lot, vkey):
    """한 필지의 토지대장 면적(㎡). 없는 지번이면 None."""
    sgg, bj, gb, bun, ji = lot
    try:
        pnu = f"{sgg}{bj}{'2' if gb == '1' else '1'}{int(bun):04d}{int(ji):04d}"  # 토지 고유번호: 산이면 2
    except ValueError:
        return None
    url = f"{VW}?key={vkey}&pnu={pnu}&format=json&numOfRows=10&pageNo=1"
    for attempt in range(4):
        out = subprocess.run(["curl", "-sS", "-m", "30", url], capture_output=True, text=True).stdout
        try:
            j = json.loads(out)
            if "ladfrlVOList" not in j and str(j.get("response", {}).get("totalCount")) == "0":
                return None  # 토지대장에 없는 지번 (합쳐지거나 나뉘어 없어진 지번 등)
            items = j["ladfrlVOList"]["ladfrlVOList"]
            return sum(float(x["lndpclAr"]) for x in items) if items else None
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            time.sleep(1 + attempt)
    raise RuntimeError(f"토지 면적: 응답 해석 실패 · {out.replace(vkey, '***')[:120]}")


FAIL_MAX = 3  # 용적률 계산이 이만큼(실행마다 한 번) 실패한 단지는 남은 일로 세지 않는다 (계속 실패하는 단지 하나로 '다 찼음' 재배포가 영영 안 돌지 않게)


def _fails(src):
    """landSrc 끝 '·오류N': 용적률 계산이 N번 실패한 단지 (다음 실행에도 다시 해 보고, 되면 지워진다)."""
    m = re.search(r"·오류(\d+)$", src)
    return int(m.group(1)) if m else 0


def _base(src):
    return re.sub(r"·오류\d+$", "", src)


def ratio_todo(r):
    """용적률 단계에서 볼 단지: 대지는 있는데 용적률·건폐율이 비었거나, 하루 한도로 층별 어림값을 쓴 단지(대장 값으로 다시)."""
    src = _base(r.get("landSrc", ""))
    return bool(r["status"] == "ok" and r["lot"] and r["platArea"]
                and (((not r["vlRat"] or not r["bcRat"]) and src in ("", "면적")) or src.endswith("·층별")))


def fill_land(workers=3, budget_s=None, region=False):
    """오래된 단지(구대장)는 대장에 대지면적·용적률·건폐율이 0이다. 토지대장 면적으로 채운다.
    1단계: 대지 = 대표 지번 + 대장의 부속지번 토지대장 면적 합 (대지면적이 있는 단지 80곳으로 시험: 99%가 ±5% 안).
           지번 중 하나라도 토지대장에 없으면 채우지 않는다.
    2단계: 용적률 = 용적률 산정 연면적 ÷ 대지, 건폐율 = 건축면적 ÷ 대지 (연면적·건축면적은 대장 값).
    landSrc: '' 아직 · '없음' 토지대장에 없음 · '면적' 대지만 채움(비율은 다음에) · '토지대장' 비율까지 · '대장' 대장 대지로 비율만 계산.
    '·층별'이 붙으면 대장 하루 한도로 층별개요 합을 쓴 어림값 (다음 실행에 대장 값으로 다시 계산).
    '·오류N'이 붙으면 용적률 계산이 N번 실패한 단지 (FAIL_MAX번부터는 land_left가 세지 않음)."""
    vkey = _env().get("VWORLD_KEY", "").strip()  # 없으면(자동 갱신 등) 1단계는 건너뛰고 2단계만
    key = _key()
    start(budget_s)
    out = OUT_KR if region else OUT
    if not out.exists():
        return "토지 면적으로 채우기: 아직 받은 단지 없음"
    old = pd.read_csv(out, dtype=str, keep_default_na=False)
    rows = {r["aptSeq"]: r for r in old.to_dict("records")}
    ok = [r for r in rows.values() if r["status"] == "ok" and r["lot"]]
    params = lambda r: dict(zip(("sigunguCd", "bjdongCd", "platGbCd", "bun", "ji"), r["lot"].split("-")))

    errs = []  # 단지 하나만 실패한 까닭 (요약에 첫 것만)

    def skip(r, e):
        errs.append(f"{r['aptSeq']} {type(e).__name__}: {e}"[:100])

    # 단지 하나가 실패하면 그 단지만 건너뛰고 다음 실행에 (예전엔 서버 오류만 잡아, 응답 모양이 다른 단지 하나에 실행 전체가 멈췄음:
    # 2026-10-23 빈 부속지번 줄 KeyError). 한도·시간·서버 전체 문제(Stop)와 인증키 오류는 그대로 올려 이번 실행을 멈춘다
    def area(r):
        try:
            return area_(r)
        except (Stop, NotRegistered):
            raise
        except Exception as e:
            skip(r, e)
            return r["aptSeq"], "skip"

    def area_(r):
        p = params(r)
        lots = {tuple(p.values())} | {(x["atchSigunguCd"], x["atchBjdongCd"], str(x["atchPlatGbCd"]), x["atchBun"], x["atchJi"])
                                      for x in call("getBrAtchJibunInfo", p, key, maxpage=30)
                                      if str(x.get("atchBjdongCd", "")).strip() and str(x.get("atchBun", "")).strip("0 ")}
        # 부속지번이 없으면 빈 줄(법정동 없음, 번지 0000)이 올 때가 있다 (대전 신탄진동 162-12): 지번으로 치지 않는다
        areas = [land_area(x, vkey) for x in sorted(lots)]
        return r["aptSeq"], None if any(a is None for a in areas) else int(round(sum(areas)))

    def ratio(r):
        try:
            return ratio_(r)
        except (Stop, NotRegistered):
            raise
        except Exception as e:
            skip(r, e)
            return r["aptSeq"], None, None, None

    def ratio_(r):
        """(단지, 용적률, 건폐율, landSrc). 연면적·건축면적은 총괄표제부 → 동별 표제부 합 → 층별개요 합 순으로,
        용적률과 건폐율을 따로 처음 말이 되는 값(용적률 60~1,000%, 건폐율 3~90%)에서 고른다.
        오래된 대장은 건축면적에 연면적을 적는 등 한 칸만 틀린 경우가 있다 (자양동 한양: 총괄 건축면적 66,577㎡ → 동별 합 6,178㎡).
        층별개요: 지상층 면적 합 ≈ 용적률 산정 연면적, 1층 면적 합 ≈ 건축면적 (은마: 485,684 vs 488,473㎡, 48,105 = 48,105㎡).
        landSrc 끝 '·층별' = 하루 한도로 층별 합을 쓴 어림값(다음 실행에 대장 값으로 다시), '·층별확인' = 대장 값이 맞지 않아 층별 합을 쓴 값(그대로 둠)."""
        p, plat = params(r), num(r["platArea"])
        src = _base(r.get("landSrc", ""))
        base = "대장" if src.split("·")[0] in ("", "대장") else "토지대장"
        ok_vl = lambda e: 60 <= e / plat * 100 <= 1000
        ok_bc = lambda a: 3 <= a / plat * 100 <= 90
        cands, quota = [], False
        try:
            recap = call("getBrRecapTitleInfo", p, key)
            c = max(recap, key=lambda x: num(x.get("hhldCnt"))) if recap else {}
            cands.append((num(c.get("vlRatEstmTotArea")), num(c.get("archArea"))))
            if not (ok_vl(cands[0][0]) and ok_bc(cands[0][1])):  # 총괄표제부가 없거나 한 칸이라도 맞지 않으면 동별 표제부 합
                titles = call("getBrTitleInfo", p, key)
                cands.append((sum(num(t.get("vlRatEstmTotArea")) for t in titles), sum(num(t.get("archArea")) for t in titles)))
        except QuotaExceeded:
            if src.endswith("·층별"):
                raise  # 이미 어림값이 있는 단지들: 한도가 찼으면 이 단계를 멈추고 다음 실행에 대장 값으로 다시
            quota = True
        est = next((e for e, _ in cands if ok_vl(e)), 0)
        arch = next((a for _, a in cands if ok_bc(a)), 0)
        how = base
        if not est or not arch:
            up = [x for x in call("getBrFlrOulnInfo", p, key, maxpage=60) if x.get("flrGbCdNm") == "지상"]
            fe = sum(num(x.get("area")) for x in up)
            fa = sum(num(x.get("area")) for x in up if str(x.get("flrNo")) == "1")
            cands.append((fe, fa))
            if (not est and ok_vl(fe)) or (not arch and ok_bc(fa)):
                how = base + ("·층별" if quota else "·층별확인")
            est = est or (fe if ok_vl(fe) else 0)
            arch = arch or (fa if ok_bc(fa) else 0)
        if not any(e for e, _ in cands):  # 건물 면적을 못 받으면 대지는 그대로 두고 비율만 비운다
            return r["aptSeq"], "", "", how
        if not est:  # 어느 값으로도 용적률이 말이 안 되면 지번 짝이 일부만 맞은 것 (대지나 연면적이 일부만 잡힘)
            return r["aptSeq"], "", "", "없음" if base == "토지대장" else base
        return r["aptSeq"], round(est / plat * 100, 1), (round(arch / plat * 100, 1) if arch else ""), how

    msg, n_area, n_ratio, failed, stopped = "", 0, 0, [], False
    try:
        with ThreadPoolExecutor(workers) as ex:
            t0 = time.time()
            over = lambda: budget_s and time.time() - t0 > budget_s
            todo = [r for r in ok if not r["platArea"] and not r.get("landSrc")] if vkey else []
            for i in range(0, len(todo), 30):
                if over():
                    break
                for seq, plat in ex.map(area, todo[i:i + 30]):
                    if plat == "skip":
                        continue
                    if plat and plat > 500 * num(rows[seq]["hhld"]):
                        plat = None  # 세대당 땅이 500㎡ 넘으면 대장과 지번 짝이 잘못 맞은 것으로 본다
                    rows[seq]["platArea"] = plat or ""
                    rows[seq]["landSrc"] = "면적" if plat else "없음"
                    n_area += bool(plat)
                save(list(rows.values()), out)
            todo = [r for r in ok if ratio_todo(r)]
            for i in range(0, len(todo), 30):
                if over():
                    msg = " (시간 한도로 중단, 다음 실행에 이어서)"
                    break
                for seq, vl, bc, how in ex.map(ratio, todo[i:i + 30]):
                    if how is None:
                        failed.append(seq)
                        continue
                    r = rows[seq]
                    if how == "없음":
                        r.update(platArea="", vlRat="", bcRat="", landSrc="없음")
                        continue
                    redo = _base(r.get("landSrc", "")).endswith("·층별")
                    r["vlRat"] = vl if redo and vl != "" else r["vlRat"] or vl
                    r["bcRat"] = bc if redo and bc != "" else r["bcRat"] or bc
                    r["landSrc"] = how
                    n_ratio += bool(vl)
                save(list(rows.values()), out)
    except (Stop, NotRegistered) as e:  # 인증키 오류도 받은 만큼 저장하고 끝낸다
        msg, stopped = f" (건축물대장 {why(e)}로 중단, 다음 실행에 이어서 · {e})", True
    if not stopped:  # 한도·시간·서버 전체 문제로 멈춘 실행의 실패는 단지 탓이 아니라 세지 않는다
        for seq in failed:
            s = rows[seq].get("landSrc", "")
            rows[seq]["landSrc"] = f"{_base(s)}·오류{_fails(s) + 1}"
    save(list(rows.values()), out)
    still = sum(1 for r in rows.values() if r["status"] == "ok" and not r["vlRat"])
    return (f"토지 면적으로 채우기: 대지면적 {n_area}곳, 용적률 {n_ratio}곳 채움{msg} · 용적률 빈 단지 {still}"
            + (f" · 건너뛴 단지 {len(errs)}곳 (예: {errs[0]})" if errs else ""))


def save(rows, out=OUT):
    df = pd.DataFrame(rows).reindex(columns=COLS).fillna("").astype(str).sort_values("aptSeq")
    df = df.apply(lambda c: c.str.replace(r"\.0$", "", regex=True))  # 정수가 84.0으로 저장되지 않게
    tmp = out.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(out)


def run(limit=None, budget_s=None, workers=4, region=False):
    """아직 안 받은 단지를 최근 거래 순으로 받는다 (workers곳씩 동시에). 반환: 요약 문장."""
    key = _key()
    start(budget_s)
    out = OUT_KR if region else OUT
    cx = complexes(region)
    umd = bjdong_codes(key, cx, region)
    old = pd.read_csv(out, dtype=str, keep_default_na=False) if out.exists() else pd.DataFrame(columns=COLS)
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
            if not got and other_code(p, r["aptSeq"]):  # 지역: 지금 코드로 없으면 옛 코드로
                p = other_code(p, r["aptSeq"])
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
                save(list(rows.values()), out)
    except NotRegistered:
        return "건축물대장: 활용신청 전이라 건너뜀 (data.go.kr '국토교통부_건축HUB_건축물대장정보 서비스')"
    except Stop as e:
        save(list(rows.values()), out)
        return f"{'지역 ' if region else ''}건축물대장: {why(e)} — {done}곳 받고 중단 (다음 실행에 이어받음)"
    have = sum(1 for v in rows.values() if v.get("status") == "ok")
    left = sum(1 for r in cx["aptSeq"] if rows.get(r, {}).get("status") not in ("ok", "none", "missing"))
    return (f"{'지역 ' if region else ''}건축물대장: 이번에 {done}곳 조회 ({ok}곳 찾음, 주소 코드 없음 {nocode}, 오류 {err}) · "
            f"전체 {have:,}곳 보유 · 남은 단지 {left:,}")


def left(region=False):
    """아직 할 일이 남은 단지 수: 조회 전·오류, 또는 지번으로 못 찾아 이름으로 다시 찾을 단지(none) (워크플로가 볼 때)."""
    out = OUT_KR if region else OUT
    old = pd.read_csv(out, dtype=str, keep_default_na=False) if out.exists() else pd.DataFrame(columns=COLS)
    st = dict(zip(old["aptSeq"], old["status"]))
    return sum(1 for s in complexes(region)["aptSeq"] if st.get(s) not in ("ok", "missing", "nocode"))


def land_left(region=False):
    """용적률 단계에 남은 단지 수 (토지대장 키 없이 자동 갱신에서도 할 수 있는 일: 워크플로가 볼 때)."""
    out = OUT_KR if region else OUT
    if not out.exists():
        return 0
    rows = pd.read_csv(out, dtype=str, keep_default_na=False).to_dict("records")
    return sum(ratio_todo(r) and _fails(r.get("landSrc", "")) < FAIL_MAX for r in rows)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("what", nargs="?", default="run", help="run(기본) · fill · land · left · 최대 단지 수")
    ap.add_argument("--regions", action="store_true", help="수도권·광역시 단지 (data/molit_kr)")
    ap.add_argument("--minutes", type=float, help="시간 한도 (분)")
    a = ap.parse_args()
    budget = a.minutes * 60 if a.minutes else None
    if a.what == "fill":
        print(fill(budget_s=budget, region=a.regions))
    elif a.what == "land":
        print(fill_land(budget_s=budget, region=a.regions))
    elif a.what == "left":
        print(left(a.regions))
    else:
        print(run(None if a.what == "run" else int(a.what), budget_s=budget, region=a.regions))

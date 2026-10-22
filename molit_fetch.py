"""국토부 아파트 매매 실거래가 상세 (서울 25개 구 × 월). 구·월 단위 JSON 캐시, 중단 후 재실행하면 이어받음.

사용: python molit_fetch.py [시작YYYYMM] [끝YYYYMM]   (최근 달부터 거꾸로 받음, 끝을 안 주면 지난달)
일일 호출 한도에 걸리면 (resultCode 22) 멈추고 다음 날 다시 실행.
"""
import datetime as dt
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "raw" / "molit" / "apt"
OUT.mkdir(parents=True, exist_ok=True)


def _key():
    """키는 부를 때 읽는다 (단지 검색 등 키 없이 도는 화면 배포가 이 모듈을 거쳐 불러도 멈추지 않게)."""
    return dict(l.split("=", 1) for l in (ROOT / ".env").read_text().split() if "=" in l)["DATA_GO_KR_KEY"]


URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
SEOUL = {"11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구",
         "11230": "동대문구", "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구",
         "11350": "노원구", "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
         "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
         "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구"}
KEEP = ["aptSeq", "aptNm", "umdNm", "jibun", "excluUseAr", "floor", "buildYear", "dealYear", "dealMonth",
        "dealDay", "dealAmount", "cdealType", "cdealDay", "dealingGbn", "buyerGbn", "slerGbn", "rgstDate",
        "umdCd", "bonbun", "bubun"]  # 법정동 코드·본번·부번: 건축물대장(세대수·용적률) 조회용


class QuotaExceeded(Exception):
    pass


def fetch(lawd, ym):
    KEY = _key()
    items, page = [], 1
    while True:
        url = f"{URL}?serviceKey={KEY}&LAWD_CD={lawd}&DEAL_YMD={ym}&numOfRows=1000&pageNo={page}"
        snippet = ""
        for attempt in range(6):
            out = subprocess.run(["curl", "-sS", "--http1.1", "-m", "60", url], capture_output=True, text=True)
            try:
                root = ET.fromstring(out.stdout)
                break
            except ET.ParseError:
                snippet = (out.stdout or out.stderr).replace(KEY, "***")[:160].replace("\n", " ")
                time.sleep(min(60, 3 * 2 ** attempt))  # 3, 6, 12, 24, 48, 60초
        else:
            raise RuntimeError(f"{lawd} {ym}: 응답 해석 실패 · {snippet}")
        code = (root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or "").strip()
        if code in ("22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"):
            raise QuotaExceeded
        if code not in ("000", "00"):
            raise RuntimeError(f"{lawd} {ym}: code {code} {(root.findtext('.//resultMsg') or root.findtext('.//errMsg'))}".replace(KEY, "***"))
        for it in root.iter("item"):
            items.append({k: (it.findtext(k) or "").strip() for k in KEEP})
        total = (root.findtext(".//totalCount") or "").strip()
        if not total.isdigit():  # 본문 없이 머리만 온 응답 (거래가 없는 달도 totalCount 0은 온다)
            raise RuntimeError(f"{lawd} {ym}: totalCount 없는 응답 ({page}쪽)")
        if page * 1000 >= int(total):
            if len(items) != int(total):  # 덜 온 응답을 그 달 전부로 쓰면 저장소의 그 달 거래가 줄어든다
                raise RuntimeError(f"{lawd} {ym}: {len(items)}/{total}건만 받음")
            return items
        page += 1


def save_json(path, rows):
    """임시 파일에 다 쓴 뒤 바꿔 쓴다 (중간에 끊겨도 반쯤 쓴 파일이 남지 않게)."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False))
    tmp.replace(path)


def cached(path):
    """받아 둔 파일이 온전한지. 예전에 쓰다 끊겨 깨진 파일은 False (다시 받는다)."""
    try:
        json.loads(path.read_text())
        return True
    except (OSError, ValueError):
        return False


def months(start, end):
    y, m = int(end[:4]), int(end[4:])
    while f"{y}{m:02d}" >= start:
        yield f"{y}{m:02d}"
        m -= 1
        if m == 0:
            y, m = y - 1, 12


if __name__ == "__main__":
    start = sys.argv[1] if len(sys.argv) > 1 else "200601"
    end = sys.argv[2] if len(sys.argv) > 2 else f"{dt.date.today().replace(day=1) - dt.timedelta(days=1):%Y%m}"  # 지난달
    done = calls = 0
    t0 = time.time()
    try:
        for ym in months(start, end):
            for lawd in SEOUL:
                path = OUT / f"{lawd}_{ym}.json"
                if cached(path):
                    continue
                save_json(path, fetch(lawd, ym))
                calls += 1
                time.sleep(0.15)
            done += 1
            print(f"{ym} 완료 · 이번 실행 호출 {calls} · {time.time() - t0:.0f}s", flush=True)
    except QuotaExceeded:
        print(f"일일 호출 한도 도달 — 호출 {calls}회 후 중단. 내일 같은 명령으로 이어받기.", flush=True)
        sys.exit(2)
    print("전체 완료", flush=True)

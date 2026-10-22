"""수도권·광역시 아파트 매매 실거래 (국토부, 시군구 × 월) → data/raw/molit/apt_kr/{코드}_{YYYYMM}.json

지역 하나를 2006년 1월부터 끝까지 다 받은 뒤 다음 지역으로 간다 (하루 호출 한도에 걸려 멈춰도 끝난 지역은 바로 쓸 수 있게).
받은 파일은 건너뛰므로(쓰다 끊겨 깨진 파일은 다시 받음) 다음 날 같은 명령으로 이어받는다.

사용: python region_fetch.py [끝YYYYMM] [지역id ...]   (지역을 안 주면 regions.REGIONS 순서대로 전부)
"""
import sys
import time
from pathlib import Path

import molit_fetch as M
from regions import REGIONS

OUT = Path(__file__).parent / "data" / "raw" / "molit" / "apt_kr"
OUT.mkdir(parents=True, exist_ok=True)


def fetch_region(rid, start, end, budget=None):
    """한 지역의 빈 (코드, 월)을 받는다. 반환: 이번에 호출한 수. 한도에 걸리면 M.QuotaExceeded."""
    calls = 0
    for ym in M.months(start, end):
        for lawd in REGIONS[rid]["lawd"]:
            path = OUT / f"{lawd}_{ym}.json"
            if M.cached(path):
                continue
            if budget is not None and calls >= budget:
                return calls
            for attempt in range(4):  # 네트워크가 잠깐 끊긴 경우 (DNS 실패 등): 기다렸다 다시. 그래도 안 되면 건너뛰고 다음 실행에 받음
                try:
                    M.save_json(path, M.fetch(lawd, ym))
                    break
                except RuntimeError as e:
                    print(f"  재시도 {attempt + 1}: {str(e)[:120]}", flush=True)
                    time.sleep(60 * (attempt + 1))
            calls += 1
            time.sleep(0.15)
    return calls


def missing(rid, start, end):
    return sum(not M.cached(OUT / f"{lawd}_{ym}.json") for ym in M.months(start, end) for lawd in REGIONS[rid]["lawd"])


if __name__ == "__main__":
    import datetime as dt
    end = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().strftime("%Y%m")
    rids = sys.argv[2:] or list(REGIONS)
    t0, total = time.time(), 0
    try:
        for rid in rids:
            n = fetch_region(rid, "200601", end)
            total += n
            print(f"{REGIONS[rid]['name']} 완료 · 이번 호출 {n} · 누적 {total} · {time.time() - t0:.0f}s", flush=True)
    except M.QuotaExceeded:
        left = {REGIONS[r]["name"]: missing(r, "200601", end) for r in rids}
        print(f"일일 호출 한도 도달 — 끝난 지역까지 호출 {total}회. 남은 (코드, 월): {left}. 내일 같은 명령으로 이어받기.", flush=True)
        sys.exit(2)
    print("전체 완료", flush=True)

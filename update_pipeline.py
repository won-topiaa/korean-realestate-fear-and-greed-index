"""서울 공포탐욕지수 월간 자동 갱신 (엔진 버전은 v3.VERSION).

순서: 원자료 갱신 → 지표·지수 재계산 → 실시간 기록 → 지도·보고서·사이트 → 점검 → (선택) 아티팩트 게시.
한 단계가 실패해도 이전 데이터로 계속 진행하고, 지수 계산이나 점검이 실패하면 게시하지 않는다.
자료처마다 시간 한도(FETCH_BUDGET)가 있어, 한 곳 서버가 멈춰도 전체 실행 시간(Actions 150분)을 넘기지 않는다.
원자료는 네 갈래(FETCH_GROUPS)로 나눠 동시에 받는다 (갈래마다 `--fetch-group` 프로세스).

사용:
  .venv/bin/python update_pipeline.py              # 전체 갱신 + 게시
  .venv/bin/python update_pipeline.py --no-publish # 게시 없이 갱신만
  .venv/bin/python update_pipeline.py --skip-fetch # 받은 자료로 재계산만
"""
import argparse
import multiprocessing as mp
import os
import datetime as dt
import json
import queue
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).parent
PY = str(ROOT / ".venv" / "bin" / "python") if (ROOT / ".venv" / "bin" / "python").exists() else sys.executable
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)
FETCHED = True  # 이번 실행에서 원자료를 받았는지 (--skip-fetch면 False)
STAMP = os.environ.get("FGI_STAMP") or dt.datetime.now().strftime("%Y%m%d_%H%M")  # 동시에 받는 갈래들은 부모의 STAMP를 이어받음
LOG = LOGS / f"update_{STAMP}.log"
PREFIX = ""  # 갈래 프로세스의 실행 기록 앞에 붙는 이름
MAP_URL = "https://claude.ai/artifact/Ri1jEadgtHmcBGcAC4pd9L"
REPORT_URL = "https://claude.ai/artifact/AvrgVB6y2Ah4WSkZEAuKGh"
CLAUDE = str(Path.home() / ".local" / "bin" / "claude")


def log(msg):
    line = _scrub(f"[{dt.datetime.now():%H:%M:%S}] {PREFIX}{msg}")
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


STATUS = []  # 단계별 성공·실패 (공개 파일 results_zone/update_status.json 로 남김)


def _scrub(msg):
    """API 키가 섞이지 않게 지운다 (실행 기록·공개 상태 파일 모두, 자르기 전에)."""
    msg = str(msg)
    env = ROOT / ".env"
    if env.exists():
        import urllib.parse
        for line in env.read_text().split():
            v = line.split("=", 1)[-1]
            for k in (v, urllib.parse.unquote(v)):
                if k:
                    msg = msg.replace(k, "***")
    return msg


def _clean(msg):
    """공개 기록용: 키를 지운 뒤 300자로."""
    return _scrub(msg)[:300]


FETCH_BUDGET = {"KB부동산": 15, "한국은행 금리·가계신용·CSI": 8, "네이버 금융 주가": 5, "구글 트렌드": 15,
                "한국부동산원 R-ONE": 40, "국토부 실거래": 25, "청약홈": 12, "건축물대장": 20,
                "수도권·광역시 부동산원": 45, "수도권·광역시 KB 시군구": 5, "수도권·광역시 원자료": 10,
                "수도권·광역시 실거래": 30}  # 분. 평소: R-ONE 11분, 나머지 1~4분


def _child(fn, q):
    try:
        q.put(("ok", str(fn() or "")))
    except Exception as e:  # noqa: BLE001
        q.put(("err", repr(e)))


def with_budget(fn, minutes):
    """fn을 자식 프로세스로 돌려 minutes 안에 안 끝나면 끊는다."""
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    p = ctx.Process(target=_child, args=(fn, q))
    p.start()
    p.join(minutes * 60)
    if p.is_alive():
        p.terminate()
        p.join(10)
        raise TimeoutError(f"{minutes}분 한도를 넘겨 중단 (지난 자료 유지)")
    try:
        kind, val = q.get(timeout=10)
    except queue.Empty:
        kind, val = "err", f"결과 없이 종료 (종료코드 {p.exitcode})"
    if kind == "err":
        raise RuntimeError(val)
    return val


def step(name, fn, critical=False):
    t0 = time.time()
    try:
        out = with_budget(fn, FETCH_BUDGET[name]) if name in FETCH_BUDGET else fn()
        log(f"OK   {name} ({time.time() - t0:.0f}s){' · ' + str(out) if out else ''}")
        STATUS.append({"step": name, "ok": True, "sec": round(time.time() - t0), "detail": _clean(str(out or ""))})
        return True
    except Exception as e:  # noqa: BLE001
        log(f"FAIL {name}: {e!r}")
        STATUS.append({"step": name, "ok": False, "sec": round(time.time() - t0), "detail": _clean(repr(e))})
        with LOG.open("a") as f:
            f.write(_scrub(traceback.format_exc()) + "\n")
        if critical:
            raise
        return False


# ---------------- 원자료 갱신 ----------------
def refresh_kb():
    import kb_fetch as K
    jobs = dict(K.JOBS)
    gu = {"아파트매매지수_월간_서울구": ("priceIndex", {"월간주간구분코드": "01", "매물종별구분": "01", "매매전세코드": "01", "기간": "99", "지역코드": "1100000000"}),
          "아파트전세지수_월간_서울구": ("priceIndex", {"월간주간구분코드": "01", "매물종별구분": "01", "매매전세코드": "02", "기간": "99", "지역코드": "1100000000"}),
          "전세가율_아파트_서울구": ("dealCntstTnantRato", {"매물종별구분": "01", "지역코드": "1100000000"})}
    jobs.update(gu)
    failed = []
    for name, (ep, p) in jobs.items():
        try:
            K.fetch(ep, p, name, refresh=True)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{name}: {_scrub(e)[:80]}")
    if len(failed) == len(jobs):
        raise RuntimeError(f"KB 전부 실패 · 예: {failed[0]}")
    d = json.loads((ROOT / "data/raw/kb/아파트매매지수_월간.json").read_text())
    return f"KB 최신 {d['날짜리스트'][-1]}" + (f" · {len(failed)}개 실패로 지난 파일 유지: {'; '.join(failed[:3])}" if failed else "")


def refresh_ecos():
    import ecos_fetch
    if not ecos_fetch.KEY:
        raise RuntimeError(".env에 ECOS_KEY 없음 (저장소에 있는 지난 자료로 계속)")
    done = ecos_fetch.refresh()
    return "한국은행 " + ", ".join(f"{k} {v}" for k, v in done.items())


def refresh_stocks():
    r = subprocess.run([PY, str(ROOT / "fetch_stocks.py")], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"fetch_stocks 실패: {(r.stderr or r.stdout).strip().splitlines()[-1:]}")
    return "건설주·KOSPI"


def refresh_trends():
    from pytrends.request import TrendReq
    import fetch_trends as T
    py = TrendReq(hl="ko-KR", tz=-540, timeout=(10, 60))
    end = dt.date.today().isoformat()
    ok = 0
    for kw in T.KEYWORDS:
        for attempt in range(4):
            try:
                py.build_payload([kw], timeframe=f"2004-01-01 {end}", geo="KR")
                df = py.interest_over_time()
                if len(df) > 200:
                    tmp = T.OUT / f"{kw}.csv.tmp"
                    df[[kw]].to_csv(tmp)
                    tmp.replace(T.OUT / f"{kw}.csv")
                    ok += 1
                break
            except Exception:  # noqa: BLE001  (429가 잦음 → 기다렸다가 재시도, 끝내 실패하면 기존 파일 유지)
                time.sleep(20 * (attempt + 1))
        time.sleep(8)
    if ok == 0:
        raise RuntimeError(f"검색어 0/{len(T.KEYWORDS)}개 갱신 (모두 지난 자료 유지)")
    return f"검색어 {ok}/{len(T.KEYWORDS)}개 갱신 (실패분은 지난달 자료 유지)"


SEOUL_REB = {  # extra_indicators.py가 읽는 부동산원 서울 시계열
    "reb_거래량_서울": ("A_2024_00554", dict(CLS_ID=500002, ITM_ID=100001)),
    "reb_매입자거주지_서울": ("A_2024_00609", dict(GRP_ID=900002, ITM_ID=100001)),
    "reb_매입자연령_서울": ("A_2024_00610", dict(GRP_ID=900002, ITM_ID=100001)),
    "reb_거래주체_서울": ("A_2024_00611", dict(GRP_ID=900002, ITM_ID=100001)),
    "reb_미분양_서울": ("T237973129847263", dict(fullnm="서울>계", ITM_ID=10001)),
    "reb_부동산심리_서울": ("T235013129634707", dict(fullnm="수도권>서울", ITM_ID=10001)),
    "reb_주택심리_서울": ("T232543129897499", dict(fullnm="수도권>서울", ITM_ID=10001)),
    "reb_매매수급_서울": ("A_2024_00076", dict(CLS_ID=500008, ITM_ID=100001)),
    "reb_전세수급_서울": ("A_2024_00077", dict(fullnm="서울", ITM_ID=100001)),
    "reb_매매지수_서울": ("A_2024_00045", dict(CLS_ID=500008, ITM_ID=100001)),
}


def refresh_reb(workers=4):
    import reb_fetch as R
    import zone_fetch as Z
    from concurrent.futures import ThreadPoolExecutor
    jobs = []  # (통계표, 저장 이름, 필터)
    for name, (sid, f) in SEOUL_REB.items():
        f = dict(f)
        if "fullnm" in f:
            full = f.pop("fullnm")
            f["CLS_ID"] = next(x["ITM_ID"] for x in R.items(sid) if x["ITM_TAG"] == "분류" and x["ITM_FULLNM"] == full)
        jobs.append((sid, name, f))
    for sid, nm in [("A_2024_00076", "매매수급"), ("A_2024_00077", "전세수급")]:
        for z, cid in Z.ids(sid, "분류", "서울>").items():
            if z in Z.ZONES:
                jobs.append((sid, f"zone_{nm}_{z}", dict(CLS_ID=cid, ITM_ID=100001)))
    for g, cid in Z.ids("A_2024_00554", "분류", "서울>").items():
        jobs.append(("A_2024_00554", f"gu_거래량_{g}", dict(CLS_ID=cid, ITM_ID=100001)))
    for sid, nm in [("A_2024_00609", "매입자거주지"), ("A_2024_00610", "매입자연령"), ("A_2024_00611", "거래주체")]:
        for g, gid in Z.ids(sid, "그룹", "서울>").items():
            jobs.append((sid, f"gu_{nm}_{g}", dict(GRP_ID=gid, ITM_ID=100001)))
    for g, cid in Z.ids("T237973129847263", "분류", "서울>").items():
        jobs.append(("T237973129847263", f"gu_미분양_{g}", dict(CLS_ID=cid, ITM_ID=10001)))
    errors = []

    def one(job):
        sid, name, f = job
        try:
            R.data(sid, "MM", name=name, refresh=True, **f)
        except Exception as e:  # noqa: BLE001  (실패한 시계열은 지난 파일 유지)
            errors.append(f"{name}: {_scrub(e)[:160]}")

    with ThreadPoolExecutor(max_workers=workers) as ex:  # 해외에서 응답이 느려 동시에 몇 개씩
        list(ex.map(one, jobs))
    if len(errors) == len(jobs):
        raise RuntimeError(f"부동산원 전부 실패 · 예: {errors[0]}")
    last = max(x["WRTTIME_IDTFR_ID"] for x in json.loads((ROOT / "data/raw/reb/reb_거래량_서울.json").read_text()))
    return f"부동산원 {len(jobs) - len(errors)}/{len(jobs)}개 시계열 갱신 · 거래량 최신 {last}" + (f" · 실패 예: {errors[0]}" if errors else "")


def refresh_molit(back=4):
    """최근 몇 달은 늦은 신고·해제가 반영되므로 다시 받는다."""
    import molit_fetch as M
    today = dt.date.today()
    y, m = today.year, today.month
    for _ in range(back):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    start, end = f"{y}{m:02d}", f"{today.year}{today.month:02d}"
    import molit_store
    n, new, failed = 0, {}, {}
    for ym in M.months(start, end):
        for lawd in M.SEOUL:
            try:
                rows = M.fetch(lawd, ym)
            except M.QuotaExceeded:
                failed.setdefault(ym, []).append(f"{lawd} 호출 한도")
                continue
            except Exception as e:  # noqa: BLE001  (한 구·월이 실패해도 나머지는 계속)
                failed.setdefault(ym, []).append(str(e)[:200])
                continue
            M.save_json(M.OUT / f"{lawd}_{ym}.json", rows)  # 끊겨도 반쯤 쓴 파일이 남지 않게
            new.setdefault(ym, []).append((lawd, rows))
            n += 1
            time.sleep(0.15)
    complete = {ym: v for ym, v in new.items() if ym not in failed and len(v) == len(M.SEOUL)}
    if not complete:
        raise RuntimeError(f"실거래 갱신 실패 (모든 달) · 예: {next(iter(failed.values()))[0] if failed else '응답 없음'}")
    total = molit_store.replace_months(complete)
    msg = f"실거래 {start}~{end}: {len(complete)}개월 갱신 ({n}회 호출) · 저장소 {total:,}건"
    if failed:
        msg += f" · 일부 실패로 지난 자료 유지: {', '.join(sorted(failed))} (예: {next(iter(failed.values()))[0]})"
    return msg


def refresh_region_src(refresh=True, reb=True, kb=True):
    """수도권·광역시: 부동산원 시도·시군구 거래 통계·수급·미분양, KB 시군구 가격지수 (region_src_fetch.py).
    refresh=False면 없는 파일만 받는다 (--skip-fetch 실행에서 Actions 캐시에 없는 KB 시군구 파일 등)."""
    import region_src_fetch
    msg, missing = region_src_fetch.refresh(refresh=refresh, reb=reb, kb=kb)
    return msg + (f" · 부동산원에 없는 이름 {len(missing)}개는 시도 값으로" if missing else "")


def refresh_molit_regions(back=4):
    """수도권·광역시 실거래: 저장소에 있는 지역만 최근 몇 달을 다시 받는다 (처음 채우기는 region_fetch.py로 따로)."""
    import molit_fetch as M
    import region_store
    from regions import REGIONS
    rids = region_store.regions_in_store()
    if not rids:
        return "지역 저장소 없음 (건너뜀)"
    today = dt.date.today()
    y, m = today.year, today.month
    for _ in range(back):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    start, end = f"{y}{m:02d}", f"{today.year}{today.month:02d}"
    codes = [c for r in rids for c in REGIONS[r]["lawd"]]
    new, failed, n = {}, {}, 0
    for ym in M.months(start, end):
        for lawd in codes:
            try:
                rows = M.fetch(lawd, ym)
            except M.QuotaExceeded:
                failed.setdefault(ym, []).append(f"{lawd} 호출 한도")
                continue
            except Exception as e:  # noqa: BLE001  (한 곳·한 달이 실패해도 나머지는 계속)
                failed.setdefault(ym, []).append(str(e)[:200])
                continue
            new.setdefault(ym, []).append((lawd, rows))
            n += 1
            time.sleep(0.15)
    complete = {ym: v for ym, v in new.items() if ym not in failed and len(v) == len(codes)}
    if not complete:
        raise RuntimeError(f"지역 실거래 갱신 실패 (모든 달) · 예: {next(iter(failed.values()))[0] if failed else '응답 없음'}")
    total = region_store.replace_months(complete)
    msg = f"지역 실거래 {start}~{end}: {len(complete)}개월 갱신 ({n}회 호출, {len(rids)}개 지역) · 저장소 {total:,}건"
    if failed:
        msg += f" · 일부 실패로 지난 자료 유지: {', '.join(sorted(failed))}"
    return msg


def refresh_bldg():
    """단지 기본정보(세대수·용적률 등). 새 단지만 지번으로 받고, 못 찾은 단지는 이름으로 다시 찾는다. 서울 다음에 수도권·광역시 새 단지도
    (처음 채우기는 region-backfill.yml이 매일). 받은 만큼 바로 저장하므로 시간 한도 전에 스스로 멈춘다
    (data/molit/buildings.csv, data/molit_kr/buildings.csv)."""
    import time
    import bldg_fetch
    t0 = time.time()
    left = lambda end: max(30, end * 60 - (time.time() - t0))  # 전체 한도(20분) 안에서 단계별 마감(분)
    out = []
    for name, fn in [("새 단지", lambda: bldg_fetch.run(budget_s=left(6))),
                     ("지역 새 단지", lambda: bldg_fetch.run(budget_s=left(11), region=True)),
                     ("다시 찾기", lambda: bldg_fetch.fill(budget_s=left(14))),
                     ("지역 다시 찾기", lambda: bldg_fetch.fill(budget_s=left(16), region=True)),
                     ("용적률", lambda: bldg_fetch.fill_land(budget_s=left(18.5)))]:  # 토지대장 면적으로 채운 단지의 용적률·건폐율
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001  (한 단계가 실패해도 받은 만큼은 저장돼 있고, 다음 단계는 돈다)
            r = f"{name} 실패: {e!r}"
        out.append(r)
        if "활용신청" in r or "서버 오류" in r:  # 서버가 답하지 않으면 나머지 단계도 같은 서버라 건너뛴다
            break
    return " / ".join(out)


def refresh_applyhome():
    import applyhome_fetch as A
    for name in A.APIS:
        A.fetch_all(name, refresh=True)  # 다 받은 뒤에만 바꿔 씀 (실패하면 지난 파일 유지)
    return "청약홈 (보조 지표)"


# ---------------- 재계산 ----------------
COMPUTE = ["molit_indicators.py", "rs_vintage.py", "extra_indicators.py", "build_indicators.py", "v3.py",
           "zone_index.py", "zone_v3.py", "export_zone.py", "map/build.py"]
AFTER_CHECK = ["export_report_v3.py", "report/build.py"]  # 실시간 기록은 점검을 통과한 뒤에
OPTIONAL = ["apt_score.py", "highs_build.py", "sim_build.py"]  # 단지 검색·신고가·모의 투자 (서울·지역): 실패해도 지도·보고서는 게시 (알림만)
REGION = ["region_index.py", "region_engine_study.py", "region_v3.py", "export_region.py"]  # 수도권·광역시: 실패하면 지난 결과로 첫 화면·지역 페이지
# (region_engine_study.py는 7개 지역이 처음 다 모인 실행에서만 엔진을 고정하고, 그 뒤로는 비교 결과만 다시 쓴다)
FINAL = ["home_build.py", "site_build.py"]


def run_script(rel):
    rel, *args = rel.split()  # "live_track.py --regions"처럼 인자를 붙일 수 있음
    r = subprocess.run([PY, "-W", "ignore", str(ROOT / rel), *args], cwd=ROOT / Path(rel).parent, capture_output=True, text=True)
    with LOG.open("a") as f:
        f.write(f"--- {rel} stdout ---\n{r.stdout[-3000:]}\n")
        if r.stderr:
            f.write(f"--- {rel} stderr ---\n{r.stderr[-3000:]}\n")
    if r.returncode != 0:
        last = (r.stderr or r.stdout).strip().splitlines()[-1:] or [""]
        raise RuntimeError(f"{rel} 종료코드 {r.returncode}: {_scrub(last[0])[:200]}")  # 원인을 공개 상태 파일에서도 보이게
    return " / ".join(r.stdout.strip().splitlines()[-9:])[:290] if rel in OPTIONAL else ""  # 지역마다 한 줄


# ---------------- 점검 ----------------
def check_and_summarize():
    import pandas as pd
    d = json.loads((ROOT / "results_zone/map_data.json").read_text())
    regs = d["regions"]
    latest = d["dates"][-1]
    now = {r: regs[r]["score"][-1] for r in regs}
    bad = [r for r, v in now.items() if regs[r].get("level") != "gu" and (v is None or not (0 <= v <= 100))]
    if bad:
        raise RuntimeError(f"최신 점수 이상: {bad}")
    gbad = [r for r, v in now.items() if regs[r].get("level") == "gu" and (v is None or not (0 <= v <= 100))]
    if gbad:  # 구는 거래가 적어 빠질 수 있음 — 게시는 계속하고 알림만
        log(f"알림: 최신 점수가 없거나 이상한 구 {gbad}")
        now = {r: v for r, v in now.items() if r not in gbad}
    r = pd.read_pickle(ROOT / "results_v2/v3_seoul.pkl")
    nv = r["n_votes_available"]
    missing = list(r["votes"].columns[r["votes"].iloc[-1].isna()])
    if missing:
        log(f"알림: 최신 달에 비어 있는 표 {missing} (과거 최대 {int(nv.max())}표 중 {int(nv.iloc[-1])}표로 계산) — 자료 공급을 확인해 보세요.")
    # 자료가 다 들어왔는지: 기준월이 나와야 할 달까지 왔고, 표에 쓰는 자료처가 다 받혔고, 지난 값을 이어 쓴 표가 없을 때만 '완료'.
    # 완료가 아니면 점수는 그대로 게시하되 예비 실행·감시가 다시 받는다 (monthly_due.sh). 예전엔 받기가 실패해도 '완료'로 넘어갔음
    import timing
    expected = f"{timing.expected_label(dt.date.today()):%Y-%m}"
    fp = ROOT / "data/freshness.json"
    fr = json.loads(fp.read_text())["cols"] if fp.exists() else {}
    stale_cols = {c for c, v in fr.items() if v["stale"]}
    vm = r["vote_meta"]
    stale = [v for v, comp in zip(vm.index, vm["구성"]) if any(c in stale_cols for c in comp.split(", "))]
    if stale:
        log(f"알림: 최신 자료가 아직 안 들어와 지난 값을 이어 쓴 표 {stale} (" + ", ".join(f"{c} {fr[c]['last']}<{fr[c]['need']}" for c in sorted(stale_cols)) + ")")
    failed = [s["step"] for s in STATUS if s["step"] in VOTE_SOURCES and not s["ok"]]
    if latest < expected:
        log(f"알림: 기준월 {latest}이 나와야 할 달({expected})보다 이르러요. KB 월간 자료가 아직 안 들어왔을 수 있어요.")
    hist_path = ROOT / "results_zone/update_history.csv"
    row = {"run": STAMP, "latest_month": latest, **{r: round(v, 1) for r, v in now.items()}}
    hist = pd.read_csv(hist_path) if hist_path.exists() else pd.DataFrame()
    if len(hist):
        prev = hist.iloc[-1]
        if prev["latest_month"] == latest:
            log(f"알림: 최신 월이 지난 실행과 같아요 ({latest}). 아직 새 월간 자료가 안 나왔을 수 있어요.")
        jumps = {r: round(now[r] - prev[r], 1) for r in now if r in prev and abs(now[r] - prev[r]) > 20}
        if jumps:
            log(f"알림: 지난 실행보다 20점 넘게 바뀐 곳 {jumps} — 자료를 확인해 보세요.")
    pd.concat([hist, pd.DataFrame([row])], ignore_index=True).to_csv(hist_path, index=False)
    sp = ROOT / "results_zone/update_summary.json"
    prev = json.loads(sp.read_text()) if sp.exists() else {}
    # fetched=false: 자료 받기 없이 재계산만 한 실행. 월간 갱신 확인(monthly_due.sh)은 last_fetched(마지막으로 자료를 받은 실행)로 본다
    # 재계산만 한 실행은 자료를 받은 실행의 '완료' 판단을 그대로 이어받는다
    complete = (latest >= expected and not stale and not failed) if FETCHED else prev.get("complete", True)
    summary = {"run": STAMP, "fetched": FETCHED, "last_fetched": STAMP if FETCHED else prev.get("last_fetched", prev.get("run")),
               "latest_month": latest, "expected_month": expected, "complete": complete,
               "stale_votes": stale if FETCHED else prev.get("stale_votes", []), "failed_sources": failed if FETCHED else prev.get("failed_sources", []),
               "scores": now, "log": str(LOG.relative_to(ROOT))}
    sp.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    zs = [r for r in now if regs[r].get("level") == "zone"]
    gs = {r: v for r, v in now.items() if regs[r].get("level") == "gu"}
    gtxt = f" · 구 {len(gs)}개 {min(gs.values()):.1f}~{max(gs.values()):.1f}" if gs else ""
    return (f"기준월 {latest} · 서울 {now['서울']} · " + ", ".join(f"{r} {now[r]}" for r in zs) + gtxt
            + ("" if complete else f" · 미완료 (다시 받을 예정: 표 {len(stale)}개 지난 값, 실패 {failed or '-'})"))


# ---------------- 게시 ----------------
def publish():
    month = json.loads((ROOT / "results_zone/update_summary.json").read_text())["latest_month"]
    prompt = (
        "서울 공포탐욕지수 월간 자동 갱신의 게시 단계야. 아래 두 로컬 HTML 파일을 각각 이미 있는 Claude 아티팩트에 덮어써서 게시해줘.\n"
        f"1) {ROOT / 'map/index.html'} → {MAP_URL}\n"
        f"2) {ROOT / 'report/index.html'} → {REPORT_URL}\n"
        "각각 먼저 Artifact 도구 action \"read\"로 해당 url을 읽고, 파일을 Read로 끝까지 확인한 뒤, "
        f"Artifact publish에 file_path와 url, label \"월간 자동 갱신 {month}\"을 넣어 게시해. icon은 넣지 마. "
        "다른 파일은 만들거나 고치지 마. 끝나면 아티팩트마다 한 줄로 성공 또는 오류를 적어줘."
    )
    r = subprocess.run([CLAUDE, "-p", prompt, "--allowedTools", "Artifact,Read", "--add-dir", str(ROOT)],
                       cwd=ROOT, capture_output=True, text=True, timeout=1800)
    with LOG.open("a") as f:
        f.write(f"--- publish ---\n{r.stdout[-4000:]}\n{r.stderr[-2000:]}\n")
    if r.returncode != 0:
        raise RuntimeError(f"claude 종료코드 {r.returncode}")
    return r.stdout.strip().splitlines()[-2:] if r.stdout.strip() else "출력 없음"


# 원자료는 자료처별 네 갈래로 나눠 동시에 받는다 (갈래마다 따로 프로세스, 갈래 안에서는 차례로, 단계마다 시간 한도).
# 건축물대장은 이번 달 새 단지를 서울 실거래에서 알아내므로 '국토부 실거래'가 끝난 뒤 시작한다. 결과 기록은 이 순서로 합친다.
FETCH_GROUPS = {
    "실거래": [("국토부 실거래", refresh_molit), ("수도권·광역시 실거래", refresh_molit_regions)],
    "부동산원": [("한국부동산원 R-ONE", refresh_reb), ("수도권·광역시 부동산원", lambda: refresh_region_src(kb=False))],
    "KB·시장": [("KB부동산", refresh_kb), ("수도권·광역시 KB 시군구", lambda: refresh_region_src(reb=False)),
               ("한국은행 금리·가계신용·CSI", refresh_ecos), ("네이버 금융 주가", refresh_stocks), ("구글 트렌드", refresh_trends),
               ("청약홈", refresh_applyhome)],
    "건축물대장": [("건축물대장", refresh_bldg)],
}
SEOUL_MOLIT_DONE = LOGS / f".seoul_molit_{STAMP}"
# 점수의 표에 들어가는 자료처 (실패하면 이번 달 갱신을 '완료'로 치지 않음). 청약홈(보조 지표)·건축물대장(단지 화면)은 빼고
VOTE_SOURCES = {n for g in FETCH_GROUPS.values() for n, _ in g} - {"청약홈", "건축물대장"}


def run_group(g):
    """갈래 하나 (update_pipeline.py --fetch-group 이름): 단계를 차례로 돌리고 결과를 logs/status_{STAMP}_{갈래}.json에 남긴다."""
    global LOG, PREFIX
    LOG, PREFIX = LOGS / f"update_{STAMP}_{g}.log", f"[{g}] "
    for name, fn in FETCH_GROUPS[g]:
        if name == "건축물대장":
            t0 = time.time()
            while not SEOUL_MOLIT_DONE.exists() and time.time() - t0 < (FETCH_BUDGET["국토부 실거래"] + 5) * 60:
                time.sleep(5)
        if os.environ.get("FGI_FAKE_FETCH"):  # 갈래 동시 실행 시험용: 실제로 받지 않고 잠깐 기다리기만
            fn = lambda: (time.sleep(3), "시험 실행")[1]  # noqa: E731
        step(name, fn)
        if name == "국토부 실거래":
            SEOUL_MOLIT_DONE.touch()
    (LOGS / f"status_{STAMP}_{g}.json").write_text(json.dumps(STATUS, ensure_ascii=False))


def fetch_all():
    """네 갈래를 동시에 띄우고, 다 끝나면 실행 기록과 단계별 결과를 합친다."""
    t0 = time.time()
    env = {**os.environ, "FGI_STAMP": STAMP}
    procs = {g: subprocess.Popen([PY, "-W", "ignore", str(ROOT / "update_pipeline.py"), "--fetch-group", g], cwd=ROOT, env=env)
             for g in FETCH_GROUPS}
    for p in procs.values():
        p.wait()
    for g, p in procs.items():
        gl, gs = LOGS / f"update_{STAMP}_{g}.log", LOGS / f"status_{STAMP}_{g}.json"
        if gl.exists():
            with LOG.open("a") as f:
                f.write(gl.read_text())
            gl.unlink()
        if gs.exists():
            STATUS.extend(json.loads(gs.read_text()))
            gs.unlink()
        else:
            STATUS.append({"step": f"{g} 갈래", "ok": False, "sec": 0, "detail": f"갈래 프로세스가 결과 없이 끝남 (종료코드 {p.returncode})"})
    SEOUL_MOLIT_DONE.unlink(missing_ok=True)
    log(f"원자료 네 갈래 동시 받기 끝 ({time.time() - t0:.0f}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--record", action="store_true", help="로컬 실행에서도 실시간 기록에 남김")
    ap.add_argument("--fetch-group", help="원자료 갈래 하나만 받기 (fetch_all이 띄우는 프로세스)")
    a = ap.parse_args()
    if a.fetch_group:
        sys.path.insert(0, str(ROOT))
        run_group(a.fetch_group)
        return 0
    sys.path.insert(0, str(ROOT))
    global FETCHED
    FETCHED = not a.skip_fetch
    log(f"=== 갱신 시작 {STAMP} ===")
    if not a.skip_fetch:
        fetch_all()
    else:
        step("수도권·광역시 원자료", lambda: refresh_region_src(refresh=False))
    for rel in COMPUTE:
        if not step(f"계산 {rel}", lambda rel=rel: run_script(rel)):
            log("=== 계산 실패로 중단 (게시 안 함) ===")
            write_status()
            return 1
    if not step("점검", check_and_summarize):
        log("=== 점검 실패로 중단 (게시 안 함) ===")
        write_status()
        return 1
    # 실시간 기록(지우지 않는 기록)은 발표한 값만: 점검을 통과한 공식 실행(GitHub Actions)이 이번 달 자료를 받았고, 갱신일 이후이고,
    # 자료가 다 들어왔거나 마지막 시도일이 됐을 때. 한 달에 처음 남긴 값이 굳으므로 그 전의 수동 실행·재계산 값이 남지 않게
    # (2026-09 서울 기록은 10-15 수동 실행 값이 남아 10-20 발표값과 달라요 — 지우지 않는 기록이라 그대로 둠)
    s = json.loads((ROOT / "results_zone/update_summary.json").read_text())
    today = dt.date.today()
    official = (bool(os.environ.get("CI") or a.record) and FETCHED and today.day >= timing_day("UPDATE_DAY")
                and s["latest_month"] >= s["expected_month"] and (s["complete"] or today.day >= timing_day("LAST_TRY_DAY")))
    if official:
        step("실시간 기록", lambda: run_script("live_track.py"))
    else:
        log("실시간 기록: 건너뜀 (" + ("로컬 실행 — 기록하려면 --record" if not (os.environ.get("CI") or a.record) else
                                     "자료를 받지 않은 재계산" if not FETCHED else "갱신일 전이거나 자료가 다 안 들어옴 — 다음 시도에서") + ")")
    for rel in AFTER_CHECK:
        if not step(f"계산 {rel}", lambda rel=rel: run_script(rel)):
            log("=== 계산 실패로 중단 (게시 안 함) ===")
            write_status()
            return 1
    region_ok = True
    eng = ROOT / "data/region_engine.json"
    fixed = eng.exists() and not json.loads(eng.read_text()).get("provisional", True)
    for rel in REGION:
        ok = step(f"계산 {rel}", lambda rel=rel: run_script(rel))
        if not ok and rel == "region_engine_study.py" and fixed:  # 엔진이 이미 고정됐으면 비교표만 못 쓴 것 — 지역 계산은 계속
            log("알림: region_engine_study.py 실패 — 고정 엔진으로 지역 계산은 계속 (비교 결과만 지난 것)")
            continue
        if not ok:
            log(f"알림: {rel} 실패 — 수도권·광역시는 지난 결과로 게시")
            region_ok = False
            why = f"- 실패한 단계: `{rel}`\n- 내용: {STATUS[-1]['detail']}\n- 실행 기록: `{LOG.relative_to(ROOT)}` (Actions 실행의 update-log)\n"
            (ROOT / "results_region/region_failed.md").write_text(why)  # 월간 갱신 워크플로가 이슈로 알림
            note = ROOT / "results_region/engine_new.md"
            if note.exists():  # 엔진은 고정했지만 그 뒤 단계가 실패: 알림에 같이 적는다
                note.write_text(note.read_text() + f"\n**다만 그 뒤 `{rel}` 단계가 실패해 지역 페이지에는 아직 반영하지 못했어요.** "
                                "다음 월간 갱신에서 고정한 엔진으로 다시 계산해요.\n")
            break
    if region_ok and official:
        step("실시간 기록 (지역)", lambda: run_script("live_track.py --regions"))
    # 단지 검색·신고가·모의 투자는 지역 결과(점수·공개 여부)를 읽으므로 지역 계산 뒤에 (예전엔 앞에 돌아 지난 결과를 썼음)
    # 새로 들어온 지역의 단지 점수 고정값(층 효과·면적 탄력성)을 먼저 한 번 고른다 (셋이 같은 값을 쓰게)
    step("계산 apt_region_study.py --missing", lambda: run_script("apt_region_study.py --missing"))
    # 셋은 서로 기다릴 필요가 없어 동시에 (서울과 지역마다 돌아 차례로 하면 몇 분 더 걸림)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(len(OPTIONAL)) as ex:
        done = list(ex.map(lambda rel: (rel, step(f"계산 {rel}", lambda: run_script(rel))), OPTIONAL))
    for rel, ok in done:
        if not ok:
            log(f"알림: {rel} 실패 — 지도·보고서는 그대로 게시 (서울 자료가 빠지면 그 화면은 점검 중 안내로)")
    step("README 갱신", lambda: run_script("readme_build.py"))  # 현재 점수·지역 결과 칸 (실패해도 게시는 계속)
    for rel in FINAL:
        if not step(f"계산 {rel}", lambda rel=rel: run_script(rel)):
            log("=== 계산 실패로 중단 (게시 안 함) ===")
            write_status()
            return 1
    if not a.no_publish and not os.environ.get("CI"):
        step("아티팩트 게시", publish)
    log("=== 완료 ===")
    write_status()
    return 0


def write_status():
    """단계별 결과. 재계산만 한 실행은 지금 자료를 받은 실행의 자료처별 결과(fetch)를 그대로 남긴다 (덮어써 사라지지 않게)."""
    p = ROOT / "results_zone/update_status.json"
    names = {n for g in FETCH_GROUPS.values() for n, _ in g}
    fetch_run, fetch = STAMP, [s for s in STATUS if s["step"] in names]
    if not FETCHED and p.exists():
        prev = json.loads(p.read_text())
        fetch_run = prev.get("fetch_run", prev.get("run"))
        fetch = prev.get("fetch", [s for s in prev.get("steps", []) if s["step"] in names])
    p.write_text(json.dumps({"run": STAMP, "steps": STATUS, "fetch_run": fetch_run, "fetch": fetch}, ensure_ascii=False, indent=1))


def timing_day(name):
    import timing
    return getattr(timing, name)


if __name__ == "__main__":
    sys.exit(main())

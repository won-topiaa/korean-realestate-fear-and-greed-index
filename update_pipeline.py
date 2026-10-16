"""서울 공포탐욕지수 월간 자동 갱신 (엔진 버전은 v3.VERSION).

순서: 원자료 갱신 → 지표·지수 재계산 → 실시간 기록 → 지도·보고서·사이트 → 점검 → (선택) 아티팩트 게시.
한 단계가 실패해도 이전 데이터로 계속 진행하고, 지수 계산이나 점검이 실패하면 게시하지 않는다.
자료처마다 시간 한도(FETCH_BUDGET)가 있어, 한 곳 서버가 멈춰도 전체 실행 시간(Actions 150분)을 넘기지 않는다.

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
STAMP = dt.datetime.now().strftime("%Y%m%d_%H%M")
LOG = LOGS / f"update_{STAMP}.log"
MAP_URL = "https://claude.ai/artifact/Ri1jEadgtHmcBGcAC4pd9L"
REPORT_URL = "https://claude.ai/artifact/AvrgVB6y2Ah4WSkZEAuKGh"
CLAUDE = str(Path.home() / ".local" / "bin" / "claude")


def log(msg):
    line = _scrub(f"[{dt.datetime.now():%H:%M:%S}] {msg}")
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
                "한국부동산원 R-ONE": 40, "국토부 실거래": 25, "청약홈": 12, "건축물대장": 15}  # 분. 평소: R-ONE 11분, 나머지 1~4분


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
            M.OUT.joinpath(f"{lawd}_{ym}.json").write_text(json.dumps(rows, ensure_ascii=False))
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


def refresh_bldg():
    """단지 기본정보(세대수·용적률 등). 새 단지만 지번으로 받고, 못 찾은 단지는 이름으로 다시 찾는다.
    받은 만큼 바로 저장하므로 시간 한도 전에 스스로 멈춘다 (데이터는 data/molit/buildings.csv에 쌓인다)."""
    import time
    import bldg_fetch
    t0 = time.time()
    a = bldg_fetch.run(budget_s=9 * 60)
    if "활용신청" in a:
        return a
    b = bldg_fetch.fill(budget_s=max(60, 12 * 60 - (time.time() - t0)))
    return " / ".join([a, b, bldg_fetch.fill_land()])  # 토지대장 면적으로 채운 단지의 용적률·건폐율


def refresh_applyhome():
    import applyhome_fetch as A
    for name in A.APIS:
        A.fetch_all(name, refresh=True)  # 다 받은 뒤에만 바꿔 씀 (실패하면 지난 파일 유지)
    return "청약홈 (보조 지표)"


# ---------------- 재계산 ----------------
COMPUTE = ["molit_indicators.py", "rs_vintage.py", "extra_indicators.py", "build_indicators.py", "v3.py",
           "zone_index.py", "zone_v3.py", "export_zone.py", "map/build.py"]
AFTER_CHECK = ["export_report_v3.py", "report/build.py"]  # 실시간 기록은 점검을 통과한 뒤에
OPTIONAL = ["apt_score.py"]  # 단지 검색: 실패해도 지도·보고서는 게시 (알림만)
FINAL = ["site_build.py"]


def run_script(rel):
    r = subprocess.run([PY, "-W", "ignore", str(ROOT / rel)], cwd=ROOT / Path(rel).parent, capture_output=True, text=True)
    with LOG.open("a") as f:
        f.write(f"--- {rel} stdout ---\n{r.stdout[-3000:]}\n")
        if r.stderr:
            f.write(f"--- {rel} stderr ---\n{r.stderr[-3000:]}\n")
    if r.returncode != 0:
        last = (r.stderr or r.stdout).strip().splitlines()[-1:] or [""]
        raise RuntimeError(f"{rel} 종료코드 {r.returncode}: {_scrub(last[0])[:200]}")  # 원인을 공개 상태 파일에서도 보이게
    return (r.stdout.strip().splitlines() or [""])[-1][:200] if rel in OPTIONAL else ""


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
    summary = {"run": STAMP, "latest_month": latest, "scores": now, "log": str(LOG.relative_to(ROOT))}
    (ROOT / "results_zone/update_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    zs = [r for r in now if regs[r].get("level") == "zone"]
    gs = {r: v for r, v in now.items() if regs[r].get("level") == "gu"}
    gtxt = f" · 구 {len(gs)}개 {min(gs.values()):.1f}~{max(gs.values()):.1f}" if gs else ""
    return f"기준월 {latest} · 서울 {now['서울']} · " + ", ".join(f"{r} {now[r]}" for r in zs) + gtxt


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--record", action="store_true", help="로컬 실행에서도 실시간 기록에 남김")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    log(f"=== 갱신 시작 {STAMP} ===")
    if not a.skip_fetch:
        step("KB부동산", refresh_kb)
        step("한국은행 금리·가계신용·CSI", refresh_ecos)
        step("네이버 금융 주가", refresh_stocks)
        step("구글 트렌드", refresh_trends)
        step("한국부동산원 R-ONE", refresh_reb)
        step("국토부 실거래", refresh_molit)
        step("청약홈", refresh_applyhome)
        step("건축물대장", refresh_bldg)
    for rel in COMPUTE:
        if not step(f"계산 {rel}", lambda rel=rel: run_script(rel)):
            log("=== 계산 실패로 중단 (게시 안 함) ===")
            write_status()
            return 1
    if not step("점검", check_and_summarize):
        log("=== 점검 실패로 중단 (게시 안 함) ===")
        write_status()
        return 1
    # 실시간 기록(지우지 않는 기록)은 점검을 통과한 공식 실행(GitHub Actions)에서만. 로컬 시험 실행이 값을 굳히지 않게
    if os.environ.get("CI") or a.record:
        step("실시간 기록", lambda: run_script("live_track.py"))
    else:
        log("실시간 기록: 로컬 실행이라 건너뜀 (기록하려면 --record)")
    for rel in AFTER_CHECK:
        if not step(f"계산 {rel}", lambda rel=rel: run_script(rel)):
            log("=== 계산 실패로 중단 (게시 안 함) ===")
            write_status()
            return 1
    for rel in OPTIONAL:
        if not step(f"계산 {rel}", lambda rel=rel: run_script(rel)):
            log(f"알림: {rel} 실패 — 지도·보고서는 그대로 게시")
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
    (ROOT / "results_zone/update_status.json").write_text(json.dumps(
        {"run": STAMP, "steps": STATUS}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())

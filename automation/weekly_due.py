"""주간 갱신(weekly-update.yml)의 할 일 확인과 배포 확인. 패키지 없이 돈다 (설치 전에 먼저 보고 할 일이 없으면 바로 끝내게).

  python automation/weekly_due.py           # GitHub Actions 출력 형식: trades= / news= (due·done), deploy= (need·ok)
  python automation/weekly_due.py verify N  # 사이트의 status.json이 저장소 자료와 같아질 때까지 N분 기다림 (안 되면 종료 코드 1)

trades: 이번 주 실거래를 아직 안 받았거나 일부만 받음 (weekly_trades.py, data/weekly_state.json)
news:   이번 주 소식 호를 만들 차례 (news_build.plan)
deploy: 사이트(status.json)가 저장소의 주간 소식 호·실거래 기록과 다름 → 화면 배포를 다시 부름 (지난 배포가 실패했거나 빠졌을 때)
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import news_build  # noqa: E402
import weekly_trades  # noqa: E402

LIVE = "https://aptfeargreed.com/status.json"
KEYS = ("news_issue", "trades_week", "trades_result", "trades_at")


def expected():
    issues = sorted(news_build.DIR.glob("*.json"))
    t = weekly_trades.load().get("trades") or {}
    return {"news_issue": issues[-1].stem if issues else None,
            "trades_week": t.get("week"), "trades_result": t.get("result"), "trades_at": t.get("at")}


def live():
    try:
        r = subprocess.run(["curl", "-sS", "-f", "-m", "20", "--retry", "2", f"{LIVE}?t={int(time.time())}"], capture_output=True, check=True)
        return json.loads(r.stdout)
    except (subprocess.CalledProcessError, ValueError):
        return None


def stale():
    """사이트가 저장소와 다른 칸 (못 읽으면 전부)."""
    want, have = expected(), live()
    return [k for k in KEYS if have is None or have.get(k) != want[k]]


def main(argv):
    if argv[:1] == ["verify"]:
        until = time.time() + float(argv[1] if len(argv) > 1 else 45) * 60
        while True:
            diff = stale()
            if not diff:
                print("사이트에 이번 자료가 올라갔어요:", expected())
                return 0
            if time.time() > until:
                print("사이트가 아직 저장소와 달라요:", diff, "· 저장소:", expected(), "· 사이트:", live())
                return 1
            time.sleep(60)
    out = {"trades": "due" if weekly_trades.due() else "done",
           "news": "due" if news_build.plan() else "done",
           "deploy": "need" if stale() else "ok"}
    print("\n".join(f"{k}={v}" for k, v in out.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

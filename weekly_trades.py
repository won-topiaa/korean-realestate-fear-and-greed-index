"""매주 실거래 넣기 (weekly-update.yml): 최근 3개 계약월(이번 달과 지난 두 달)의 서울·수도권·광역시 실거래를 다시 받아 저장소에 넣는다.

실거래는 계약 후 30일 안에 신고되고 해제도 늦게 들어오므로, 단지 검색·신고가·모의 투자가 한 달을 기다리지 않게 매주 받는다
(받은 뒤 '화면만 다시 배포'가 저장소 자료로 세 화면을 다시 계산한다). 지수는 그대로 매달 20일에만 계산한다:
월간 갱신이 최근 4개월을 다시 받아 통째로 바꾸므로, 지수에 쓰는 자료는 주간 갱신이 있든 없든 같다.
월간 갱신 무렵(KST 18~22일, 아직 안 끝났을 때)은 쉰다 (그날 호출 한도를 월간 갱신이 쓰게, 저장소 파일이 겹치지 않게).

결과는 data/weekly_state.json에 남긴다 (그 주 월요일, 결과, 시도 횟수). 예비 실행(월·화요일)은 이 기록을 보고
이번 주에 다 받았으면 건너뛰고, 일부 달만 받았으면 TRIES번까지 다시 받는다. 사이트의 status.json과 감시(register/worker.js)도 이 기록을 본다.

사용: python weekly_trades.py           (.env에 DATA_GO_KR_KEY)
      python weekly_trades.py --check   # 이번 주에 받을 차례면 due, 아니면 done (호출 없음, 패키지 없이 돎)
종료 코드: 0 받음(일부 달 실패 포함)·이미 받음 · 2 월간 갱신 무렵이라 건너뜀 · 1 서울·지역 모두 못 받음
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "weekly_state.json"
KST = dt.timezone(dt.timedelta(hours=9))
BACK = 2   # 이번 달 + 지난 두 달 (월간 갱신은 4)
TRIES = 3  # 일부 달만 받은 주에 다시 받아 보는 횟수 (예비 실행마다 한 번)


def monday(now=None):
    d = (now or dt.datetime.now(KST)).date()
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def load():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def due(state=None, now=None):
    t = (state if state is not None else load()).get("trades") or {}
    if t.get("week") != monday(now):
        return True
    return t.get("result") in ("partial", "failed") and t.get("tries", 0) < TRIES


def save(result, note, now=None):
    now = now or dt.datetime.now(KST)
    s = load()
    t = s.get("trades") or {}
    tries = t.get("tries", 0) + 1 if t.get("week") == monday(now) else 1
    s["trades"] = {"week": monday(now), "result": result, "at": now.isoformat(timespec="minutes"), "tries": tries, "note": note[:300]}
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1) + "\n")


def main():
    import update_pipeline as P
    from automation.backfill_left import monthly_busy

    if monthly_busy():
        print("월간 갱신 무렵이라 건너뜀 (월간 갱신이 최근 4개월을 받음)")
        save("skipped", "월간 갱신 무렵이라 월간 갱신이 받음")
        return 2
    ok, partial, notes = 0, False, []
    for name, fn in [("서울", P.refresh_molit), ("수도권·광역시", P.refresh_molit_regions)]:
        try:
            msg = fn(back=BACK)
            ok += 1
            partial |= "일부 실패" in msg
        except RuntimeError as e:  # 모든 달이 실패한 경우만 아무것도 저장하지 않음 (지수에 쓰는 달 실패 알림은 주간엔 상관없음)
            msg = P._scrub(str(e))
            got = "모든 달" not in msg
            ok += got
            partial = True
        except Exception as e:  # noqa: BLE001  (한쪽이 예상 못 한 오류로 멈춰도 다른 쪽은 받는다)
            msg = P._scrub(f"{type(e).__name__}: {e}")
            partial = True
        print(f"{name}: {msg}")
        notes.append(f"{name}: {msg}")
    save("failed" if not ok else "partial" if partial else "full", " / ".join(notes))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--check" in sys.argv:
        print("due" if due() else "done")
        sys.exit(0)
    sys.exit(main())

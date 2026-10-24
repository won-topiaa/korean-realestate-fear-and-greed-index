"""매주 실거래 넣기 (weekly-update.yml): 최근 3개 계약월(이번 달과 지난 두 달)의 서울·수도권·광역시 실거래를 다시 받아 저장소에 넣는다.

실거래는 계약 후 30일 안에 신고되고 해제도 늦게 들어오므로, 단지 검색·신고가·모의 투자가 한 달을 기다리지 않게 매주 받는다
(받은 뒤 '화면만 다시 배포'가 저장소 자료로 세 화면을 다시 계산한다). 지수는 그대로 매달 20일에만 계산한다:
월간 갱신이 최근 4개월을 다시 받아 통째로 바꾸므로, 지수에 쓰는 자료는 주간 갱신이 있든 없든 같다.
월간 갱신 무렵(KST 18~22일, 아직 안 끝났을 때)은 쉰다 (그날 호출 한도를 월간 갱신이 쓰게, 저장소 파일이 겹치지 않게).

사용: python weekly_trades.py    (.env에 DATA_GO_KR_KEY)
종료 코드: 0 받음(일부 달 실패 포함) · 2 월간 갱신 무렵이라 건너뜀 · 1 서울·지역 모두 못 받음
"""
import sys

import update_pipeline as P
from automation.backfill_left import monthly_busy

BACK = 2  # 이번 달 + 지난 두 달 (월간 갱신은 4)


def main():
    if monthly_busy():
        print("월간 갱신 무렵이라 건너뜀 (월간 갱신이 최근 4개월을 받음)")
        return 2
    ok = 0
    for name, fn in [("서울", P.refresh_molit), ("수도권·광역시", P.refresh_molit_regions)]:
        try:
            print(f"{name}: {fn(back=BACK)}")
            ok += 1
        except RuntimeError as e:  # 모든 달이 실패한 경우만 아무것도 저장하지 않음 (지수에 쓰는 달 실패 알림은 주간엔 상관없음)
            msg = P._scrub(str(e))
            print(f"{name}: {msg}")
            ok += "모든 달" not in msg
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

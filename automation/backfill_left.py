"""지역 자료 채우기(region-backfill.yml)에 남은 일을 GitHub Actions 출력 형식으로 알려 준다.

  left=  아직 지역 저장소에 없는 지역 id (쉼표로)
  names= 지역 저장소에 있는데 단지 표에 이름이 없는 단지 수 (다시 받아 볼 달이 남은 것만)
  bldg=  건축물대장을 아직 조회하지 않은 지역 단지 수
  fix=   true면 최종 지역 엔진이 아직 없음 (임시 엔진이거나 없음)
  busy=  true면 월간 갱신을 앞뒀거나 아직 못 끝낸 때 (KST 18~22일): 채우기를 쉬어 그날 호출 한도를 월간 갱신이 다 쓰게 한다

사용: python automation/backfill_left.py >> "$GITHUB_OUTPUT"
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bldg_fetch  # noqa: E402
import region_backfill  # noqa: E402
import region_store  # noqa: E402
from regions import REGIONS  # noqa: E402


def monthly_busy(today=None):
    """KST 18~22일이고 이번 달 월간 갱신(자료를 받은 실행)이 아직이면 True."""
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    if not 18 <= today.day <= 22:
        return False
    p = ROOT / "results_zone" / "update_summary.json"
    s = json.loads(p.read_text()) if p.exists() else {}
    last = s.get("run", "") if s.get("fetched", True) else s.get("last_fetched", "")
    return last[:8] < f"{today:%Y%m}20" or s.get("complete") is False  # 자료가 덜 들어온 실행은 다시 받으므로 아직 바쁨


def main():
    have = set(region_store.regions_in_store())
    eng = ROOT / "data" / "region_engine.json"
    fix = json.loads(eng.read_text()).get("provisional", True) if eng.exists() else True
    out = {"left": ",".join(r for r in REGIONS if r not in have), "names": len(region_backfill.names_todo()[1]),
           "bldg": bldg_fetch.left(True), "fix": "true" if fix else "false", "busy": "true" if monthly_busy() else "false"}
    print("\n".join(f"{k}={v}" for k, v in out.items()))


if __name__ == "__main__":
    main()

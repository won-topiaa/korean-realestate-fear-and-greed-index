#!/usr/bin/env bash
# 이번 달 월간 갱신이 아직 필요한지 한 단어로 알려 준다 (GitHub Actions에서 씀).
#   early: 아직 20일 전 / done: 20일(한국 시간) 이후 갱신 완료 / busy: 먼저 시작한 갱신이 돌고 있음 / due: 지금 돌려야 함
# '완료'는 저장소 main의 results_zone/update_summary.json(점검을 통과해야 커밋됨) 실행 시각으로 판단한다.
# '돌고 있음'은 이 실행보다 먼저 만들어진 월간 갱신만 센다 (예약이 늦게 몰려 동시에 떠도 하나는 진행하게).
# 필요한 환경 변수: GH_TOKEN, GITHUB_REPOSITORY, GITHUB_RUN_ID
set -euo pipefail
repo=$GITHUB_REPOSITORY
day=$(TZ=Asia/Seoul date +%d)
since=$(TZ=Asia/Seoul date +%Y%m)20

if (( 10#$day < 20 )); then echo early; exit 0; fi

# 자료 받기 없이 재계산만 한 실행(지역 엔진 고정용 skip_fetch, fetched=false)은 이번 달 갱신으로 치지 않는다
last=$(gh api "repos/$repo/contents/results_zone/update_summary.json?ref=main" -H "Accept: application/vnd.github.raw" \
  | jq -r 'if .fetched == false then (.last_fetched // "") else .run end')
if [[ ! "${last:0:8}" < "$since" ]]; then echo done; exit 0; fi

busy=$(gh api "repos/$repo/actions/workflows/monthly-update.yml/runs?per_page=30" \
  --jq "[.workflow_runs[] | select(.id < $GITHUB_RUN_ID and .status != \"completed\")] | length")
if (( busy > 0 )); then echo busy; exit 0; fi

echo due

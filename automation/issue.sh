#!/usr/bin/env bash
# 알림 이슈 열기·닫기 (GitHub Actions에서 씀, GH_TOKEN·GITHUB_REPOSITORY 필요, 작업에 issues: write).
# 같은 제목의 열린 이슈가 있으면 새로 만들지 않고 댓글만 단다. 봇이 부른 실행(배포·주간 갱신 예비 실행)이 실패해도
# 저장소 주인에게 알림이 가게 (GitHub는 실행을 부른 계정에게만 실패 메일을 보내는데, 봇이 부르면 아무도 못 받음).
#   bash automation/issue.sh open  "제목" "내용"
#   bash automation/issue.sh close "제목" "닫으며 남길 말"   # 열린 이슈가 있을 때만
set -uo pipefail
mode=$1 title=$2 body=${3:-}
repo=$GITHUB_REPOSITORY
# 검색(--search)은 새 이슈가 늦게 잡히므로 열린 이슈 목록에서 제목으로 찾는다
num=$(gh issue list -R "$repo" --state open --limit 200 --json number,title \
  --jq "map(select(.title == \"$title\")) | .[0].number // empty") || { echo "이슈 목록을 못 읽음"; exit 1; }
if [ "$mode" = open ]; then
  if [ -n "$num" ]; then gh issue comment "$num" -R "$repo" --body "$body"
  else gh issue create -R "$repo" --title "$title" --body "@${GITHUB_REPOSITORY_OWNER:-${repo%%/*}} $body"; fi
elif [ -n "$num" ]; then
  gh issue close "$num" -R "$repo" --comment "$body"
fi

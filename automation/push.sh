#!/usr/bin/env bash
# 이번 실행의 커밋을 main 위에 얹고 올린다 (GitHub Actions에서 씀). 다른 작업이 먼저 올렸어도 그 줄을 지우지 않는다:
#  - 덧붙이기만 하는 기록(live_log.csv, update_history.csv)은 .gitattributes의 merge=union으로 양쪽 줄을 다 남기고
#  - 단지 표(complexes.csv, buildings.csv)는 단지 번호로 합친다 (automation/merge_tables.py, 원본과 비교해 바뀐 쪽을 고름)
#  - 다시 만드는 화면(지도·보고서·첫 화면 index.html, README.md, 미리보기 이미지 assets/og)은 main 쪽을 받는다. 부른 쪽이 얹은 뒤 다시 빌드한다
#    (월간 갱신: map·report·home_build·readme_build). 다시 빌드하지 않는 올리기에서는 main 쪽 화면이 그대로 남고, 사이트는 화면 배포가 새로 만든다
#  - 그 밖의 파일이 겹치면 얹기를 취소하고 실패로 끝낸다 (예전 -X theirs처럼 한쪽을 조용히 덮어쓰지 않게)
# 사용: bash automation/push.sh        # 얹고 올리기 (밀리면 최대 4번 다시)
#       bash automation/push.sh sync   # 얹기만 (올리기 전에 다시 빌드할 때)
set -uo pipefail
mode=${1:-push}

rebasing() { [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; }

sync() {
  git pull --rebase origin main && return 0
  # 받기 자체가 실패(네트워크, 고치다 만 파일 등)해 얹기가 시작되지 않았으면 실패로 (예전엔 성공으로 넘어갔음)
  rebasing || { echo "main을 받지 못했어요 (얹기 전에 실패)"; return 1; }
  while rebasing; do
    for f in $(git diff --name-only --diff-filter=U); do
      case "$f" in
        data/molit/complexes.csv|data/molit/buildings.csv|data/molit_kr/complexes.csv|data/molit_kr/buildings.csv)
          python automation/merge_tables.py "$f" || { git rebase --abort; return 1; } ;;
        map/index.html|report/index.html|home/index.html|README.md|assets/og/*.jpg)
          # 얹는 중에는 --ours가 main 쪽 (이번 실행의 커밋이 그 위에 다시 얹히는 중)
          git checkout --ours -- "$f" && echo "다시 만드는 화면이라 main 쪽을 받음: $f" || { git rebase --abort; return 1; } ;;
        *)
          echo "겹친 파일을 자동으로 합칠 수 없어 멈춰요: $f"; git rebase --abort; return 1 ;;
      esac
      git add "$f"
    done
    GIT_EDITOR=true git rebase --continue >/dev/null || { [ -n "$(git diff --name-only --diff-filter=U)" ] || { git rebase --abort; return 1; }; }
  done
}

if [ "$mode" = sync ]; then sync; exit $?; fi
for i in 1 2 3 4; do
  sync || exit 1
  git push origin HEAD:main && exit 0
  sleep $((i * 15))  # 그사이 다른 작업이 올렸으면 다시 얹는다
done
exit 1

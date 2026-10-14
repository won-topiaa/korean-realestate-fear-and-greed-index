#!/bin/zsh
# 서울 공포탐욕지수 월간 자동 갱신 (launchd가 매달 실행). 직접 실행해도 됨: ./update.sh [--no-publish]
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
exec ./.venv/bin/python update_pipeline.py "$@"

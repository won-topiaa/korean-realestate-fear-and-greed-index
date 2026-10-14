#!/bin/zsh
# 월간 자동 갱신 등록. 프로젝트 폴더 위치를 넣어 ~/Library/LaunchAgents 에 설치한다.
set -e
PROJECT="$(cd "$(dirname "$0")/.." && pwd -P)"
DEST="$HOME/Library/LaunchAgents/com.wontopia.seoulfgi.monthly.plist"
sed "s#__PROJECT__#$PROJECT#g" "$PROJECT/automation/com.wontopia.seoulfgi.monthly.plist" > "$DEST"
launchctl bootout "gui/$(id -u)/com.wontopia.seoulfgi.monthly" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"
echo "등록 완료: 매달 20일 09:17 → $PROJECT/update.sh"

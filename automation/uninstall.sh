#!/bin/zsh
# 월간 자동 갱신 해제
launchctl bootout "gui/$(id -u)/com.wontopia.seoulfgi.monthly" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.wontopia.seoulfgi.monthly.plist"
echo "해제 완료"

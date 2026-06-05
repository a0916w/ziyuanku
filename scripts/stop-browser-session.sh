#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
DISPLAY_NUM="${DISPLAY_NUM:-1}"
PROFILE_DIR="${PROFILE_DIR:-$PROJECT_DIR/data/browser-profiles/missav}"
LOG_DIR="$PROJECT_DIR/data/logs/browser-session"

pkill -f "chrome.*--user-data-dir=${PROFILE_DIR}" 2>/dev/null || true
pkill -f "chromium.*--user-data-dir=${PROFILE_DIR}" 2>/dev/null || true

if [[ -f "$LOG_DIR/novnc.pid" ]]; then
  kill "$(cat "$LOG_DIR/novnc.pid")" 2>/dev/null || true
fi

if command -v vncserver >/dev/null 2>&1; then
  vncserver -kill ":${DISPLAY_NUM}" >"$LOG_DIR/vnc-stop.log" 2>&1 || true
fi

echo "Browser verification session stopped."

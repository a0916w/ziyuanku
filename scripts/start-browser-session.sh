#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
DISPLAY_NUM="${DISPLAY_NUM:-1}"
VNC_GEOMETRY="${VNC_GEOMETRY:-1440x1000}"
VNC_DEPTH="${VNC_DEPTH:-24}"
NOVNC_HOST="${NOVNC_HOST:-127.0.0.1}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
CDP_HOST="${CDP_HOST:-127.0.0.1}"
CDP_PORT="${CDP_PORT:-9222}"
TARGET_URL="${TARGET_URL:-https://missav.ai/dm31/en/twav}"
PROFILE_DIR="${PROFILE_DIR:-$PROJECT_DIR/data/browser-profiles/missav}"
VNC_PASSWORD_FILE="${VNC_PASSWORD_FILE:-$PROJECT_DIR/data/browser-profiles/.vnc-password.txt}"
VNC_AUTH_FILE="${VNC_AUTH_FILE:-$HOME/.vnc/passwd}"
LOG_DIR="$PROJECT_DIR/data/logs/browser-session"
CHROME_BIN="${CHROME_BIN:-}"
VNC_PORT="$((5900 + DISPLAY_NUM))"

port_open() {
  python3 - "$1" "$2" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
with socket.socket() as sock:
    sock.settimeout(1)
    sys.exit(0 if sock.connect_ex((host, port)) == 0 else 1)
PY
}

mkdir -p "$LOG_DIR" "$PROFILE_DIR"
rm -f "$PROFILE_DIR"/SingletonLock "$PROFILE_DIR"/SingletonSocket "$PROFILE_DIR"/SingletonCookie

CHROME_RUNNING=0
if curl -fsS --max-time 2 "http://${CDP_HOST}:${CDP_PORT}/json/version" >/dev/null 2>&1; then
  CHROME_RUNNING=1
fi

if [[ -z "$CHROME_BIN" && -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
  CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
fi

if [[ -z "$CHROME_BIN" ]]; then
  CHROME_BIN=$(find "$HOME/.cache/ms-playwright" /root/.cache/ms-playwright -path '*/chrome-linux*/chrome' -type f 2>/dev/null | sort | tail -1 || true)
fi

if [[ "$CHROME_RUNNING" != "1" && ( -z "$CHROME_BIN" || ! -x "$CHROME_BIN" ) ]]; then
  echo "Cannot find Chrome/Chromium. Install Playwright Chromium or set CHROME_BIN." >&2
  exit 1
fi

for required_cmd in vncserver websockify vncpasswd; do
  if ! command -v "$required_cmd" >/dev/null 2>&1; then
    echo "Cannot find ${required_cmd}. Install TigerVNC, noVNC and websockify before using browser verification." >&2
    exit 1
  fi
done

if [[ ! -d /usr/share/novnc && -z "${NOVNC_WEB:-}" ]]; then
  echo "Cannot find noVNC web files at /usr/share/novnc. Set NOVNC_WEB or install novnc." >&2
  exit 1
fi
NOVNC_WEB="${NOVNC_WEB:-/usr/share/novnc}"

mkdir -p "$(dirname "$VNC_PASSWORD_FILE")" "$(dirname "$VNC_AUTH_FILE")"
if [[ -z "${VNC_PASSWORD:-}" ]]; then
  if [[ -s "$VNC_PASSWORD_FILE" ]]; then
    VNC_PASSWORD="$(head -n 1 "$VNC_PASSWORD_FILE")"
  else
    VNC_PASSWORD="$(python3 -c 'import secrets,string; chars=string.ascii_letters+string.digits; print("".join(secrets.choice(chars) for _ in range(10)))')"
    printf '%s\n' "$VNC_PASSWORD" > "$VNC_PASSWORD_FILE"
    chmod 600 "$VNC_PASSWORD_FILE"
  fi
else
  printf '%s\n' "$VNC_PASSWORD" > "$VNC_PASSWORD_FILE"
  chmod 600 "$VNC_PASSWORD_FILE"
fi
printf '%s\n' "$VNC_PASSWORD" | vncpasswd -f > "$VNC_AUTH_FILE"
chmod 600 "$VNC_AUTH_FILE"

if ! port_open 127.0.0.1 "$VNC_PORT"; then
  vncserver ":${DISPLAY_NUM}" -localhost yes -geometry "$VNC_GEOMETRY" -depth "$VNC_DEPTH" >"$LOG_DIR/vnc-start.log" 2>&1
fi
if ! port_open 127.0.0.1 "$VNC_PORT"; then
  echo "VNC server did not start on 127.0.0.1:${VNC_PORT}. Check $LOG_DIR/vnc-start.log" >&2
  exit 1
fi

if ! port_open "$NOVNC_HOST" "$NOVNC_PORT"; then
  nohup websockify --web="$NOVNC_WEB" "${NOVNC_HOST}:${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" >"$LOG_DIR/novnc.log" 2>&1 &
  echo $! > "$LOG_DIR/novnc.pid"
  sleep 1
fi
if ! port_open "$NOVNC_HOST" "$NOVNC_PORT"; then
  echo "noVNC websockify did not start on ${NOVNC_HOST}:${NOVNC_PORT}. Check $LOG_DIR/novnc.log" >&2
  exit 1
fi

if [[ -n "${DISPLAY:-}" ]]; then
  CHROME_DISPLAY="$DISPLAY"
else
  CHROME_DISPLAY=":${DISPLAY_NUM}"
fi

if [[ "$CHROME_RUNNING" == "1" ]]; then
  echo "Chrome CDP is already listening on ${CDP_HOST}:${CDP_PORT}"
else
  DISPLAY="$CHROME_DISPLAY" nohup "$CHROME_BIN" \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --no-first-run \
    --no-default-browser-check \
    --remote-debugging-address="$CDP_HOST" \
    --remote-debugging-port="$CDP_PORT" \
    --user-data-dir="$PROFILE_DIR" \
    "$TARGET_URL" >"$LOG_DIR/chrome.log" 2>&1 &
fi

echo "Chrome CDP: http://${CDP_HOST}:${CDP_PORT}"
echo "noVNC: http://${NOVNC_HOST}:${NOVNC_PORT}/vnc.html"
echo "VNC password file: $VNC_PASSWORD_FILE"
echo "Profile: $PROFILE_DIR"

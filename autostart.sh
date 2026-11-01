#!/usr/bin/env bash
# Run fn-dictate in the background at every login (macOS LaunchAgent).
#   ./autostart.sh on       install and start now
#   ./autostart.sh off      stop and remove
#   ./autostart.sh status   is it running?
#   ./autostart.sh logs     follow the log
set -euo pipefail
cd "$(dirname "$0")"

LABEL="com.github.fn-dictate"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/fn-dictate.log"
DIR="$(pwd)"
PY="$DIR/.venv/bin/python"
DOMAIN="gui/$(id -u)"

python_app() {
  # The process macOS asks permissions for (Homebrew Python re-launches itself as Python.app).
  local real
  real="$("$PY" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
  local app="${real%/bin/*}/Resources/Python.app"
  [[ -d "$app" ]] && echo "$app" || echo "$real"
}

case "${1:-}" in
  on)
    [[ -x "$PY" ]] || { echo "Run ./install.sh first." >&2; exit 1; }
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$DIR/fn_dictate.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>EnvironmentVariables</key>
  <dict><key>PYTHONUNBUFFERED</key><string>1</string></dict>
</dict>
</plist>
EOF
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "fn-dictate will now start automatically at login. It is starting now."
    echo
    echo "macOS needs to allow these for the background process, in"
    echo "System Settings > Privacy & Security:"
    echo "  - Microphone, Input Monitoring, Accessibility"
    echo "If 'Python' is not listed under Input Monitoring or Accessibility, click +"
    echo "and add this app (press Cmd+Shift+G in the file picker and paste the path):"
    echo "  $(python_app)"
    echo
    echo "After changing permissions run:  ./autostart.sh restart"
    echo "Check it with:                   ./autostart.sh logs"
    ;;
  off)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Autostart removed and fn-dictate stopped."
    ;;
  restart)
    launchctl kickstart -k "$DOMAIN/$LABEL"
    echo "Restarted."
    ;;
  status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      launchctl print "$DOMAIN/$LABEL" | grep -E '^\s*(state|pid|last exit code)' || true
    else
      echo "Autostart is off."
    fi
    ;;
  logs)
    touch "$LOG"
    tail -n 30 -f "$LOG"
    ;;
  *)
    echo "Usage: ./autostart.sh on | off | restart | status | logs" >&2
    exit 1
    ;;
esac

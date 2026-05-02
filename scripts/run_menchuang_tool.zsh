#!/bin/zsh
set -e

PROJECT_DIR="/Users/cc/Documents/New project 2/customer_context_assistant"
LOG_FILE="$PROJECT_DIR/logs/desktop_app.log"
LOCK_DIR="/tmp/menchuang-tool.lock"
PID_FILE="$LOCK_DIR/pid"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.9/bin/python3"

mkdir -p "$PROJECT_DIR/logs"

is_live_pid() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  existing_pid=""
  if [[ -f "$PID_FILE" ]]; then
    existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  fi
  if ! is_live_pid "$existing_pid"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 清理失效启动锁，重新启动门窗工具。" >> "$LOG_FILE"
    rm -f "$PID_FILE" 2>/dev/null || true
    rmdir "$LOCK_DIR" 2>/dev/null || true
    mkdir "$LOCK_DIR"
  else
  echo "$(date '+%Y-%m-%d %H:%M:%S') 门窗工具已经在运行，正在尝试唤起已有窗口。" >> "$LOG_FILE"
  osascript <<'APPLESCRIPT' 2>/dev/null || true
tell application "System Events"
  set candidateNames to {"门窗工具", "Python"}
  repeat with candidateName in candidateNames
    set matchingProcesses to every process whose name contains candidateName
    repeat with p in matchingProcesses
      set frontmost of p to true
      return
    end repeat
  end repeat
end tell
APPLESCRIPT
  exit 0
  fi
fi

cleanup() {
  if [[ -f "$PID_FILE" ]]; then
    current_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ "$current_pid" == "$$" ]]; then
      rm -f "$PID_FILE" 2>/dev/null || true
    fi
  fi
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR/src"
echo "$(date '+%Y-%m-%d %H:%M:%S') 启动门窗工具" >> "$LOG_FILE"
echo "$$" > "$PID_FILE"
"$PYTHON_BIN" "$PROJECT_DIR/floating_region_assistant.py" >> "$LOG_FILE" 2>&1

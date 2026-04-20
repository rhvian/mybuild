#!/usr/bin/env bash
# 安全停止后台采集
#
# 流程：SIGINT（Ctrl+C 等效）→ 等 graceful 最多 30s → 仍在则 SIGKILL
# 流式 pipeline 捕获 KeyboardInterrupt，已采数据已落库。
#
# 用法：
#   bash scripts/collect-stop.sh           # 默认 30s graceful
#   bash scripts/collect-stop.sh -t 60     # 等 60s

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

PID_FILE="collector/data/collect.pid"
GRACE_SEC=30

while [ $# -gt 0 ]; do
  case "$1" in
    -t) GRACE_SEC="$2"; shift 2 ;;
    *)  shift ;;
  esac
done

if [ -t 1 ]; then
  C_RESET='\033[0m'; C_BOLD='\033[1m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_CYAN='\033[36m'; C_RED='\033[31m'
else
  C_RESET=''; C_BOLD=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''; C_RED=''
fi
log()  { printf '%b[collect-stop]%b %s\n'     "$C_BOLD$C_CYAN"   "$C_RESET" "$*"; }
warn() { printf '%b[collect-stop:WARN]%b %s\n' "$C_BOLD$C_YELLOW" "$C_RESET" "$*" >&2; }
err()  { printf '%b[collect-stop:ERR]%b %s\n'  "$C_BOLD$C_RED"    "$C_RESET" "$*" >&2; }
ok()   { printf '%b[collect-stop]%b %s\n'      "$C_BOLD$C_GREEN"  "$C_RESET" "$*"; }

if [ ! -f "$PID_FILE" ]; then
  warn "no pid file found at $PID_FILE — nothing to stop"
  exit 0
fi

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [ -z "${PID:-}" ]; then
  warn "empty pid file, removing"
  rm -f "$PID_FILE"
  exit 0
fi

if ! kill -0 "$PID" 2>/dev/null; then
  warn "pid=$PID not alive, removing stale pid file"
  rm -f "$PID_FILE"
  exit 0
fi

# 找到整个进程组（setsid 启动时 pgid = pid），一起发信号
PGID="$(ps -o pgid= -p "$PID" 2>/dev/null | tr -d ' ')"
log "stopping pid=$PID pgid=${PGID:-$PID} (sending SIGINT)"
if [ -n "${PGID:-}" ] && [ "$PGID" != "$PID" ]; then
  kill -INT -"$PGID" 2>/dev/null || true
else
  kill -INT "$PID" 2>/dev/null || true
fi

# 等 graceful
for i in $(seq 1 "$GRACE_SEC"); do
  if ! kill -0 "$PID" 2>/dev/null; then
    ok "stopped gracefully after ${i}s"
    rm -f "$PID_FILE"
    exit 0
  fi
  sleep 1
done

err "still alive after ${GRACE_SEC}s — sending SIGKILL"
if [ -n "${PGID:-}" ] && [ "$PGID" != "$PID" ]; then
  kill -KILL -"$PGID" 2>/dev/null || true
else
  kill -KILL "$PID" 2>/dev/null || true
fi
sleep 1
rm -f "$PID_FILE"

# 兜底：清残留 playwright/chromium
pkill -9 -f "collector\.cli" 2>/dev/null || true
pkill -9 -f "chrome-headless" 2>/dev/null || true
pkill -9 -f "playwright" 2>/dev/null || true

ok "force-killed"

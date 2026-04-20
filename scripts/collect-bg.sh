#!/usr/bin/env bash
# 后台启动 scripts/collect.sh — nohup + PID + 日志文件
#
# 用法：
#   bash scripts/collect-bg.sh              # 后台跑全量（含 init-db）
#   bash scripts/collect-bg.sh --no-init    # 跳过 init-db
#   bash scripts/collect-bg.sh --only enterprise   # 分类启动（需 C2 已上）
#
# 启动后：
#   scripts/collect-status.sh   查看进程 + 日志尾部
#   scripts/collect-stop.sh     安全停止（发 SIGINT，等 graceful，超时再 SIGKILL）
#
# 文件位置：
#   PID   collector/data/collect.pid
#   日志   collector/logs/collect-YYYYMMDD-HHMMSS.log
#   软链   collector/logs/collect-latest.log -> 最新日志

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

PID_FILE="collector/data/collect.pid"
LOG_DIR="collector/logs"
mkdir -p "$LOG_DIR" collector/data

# 颜色
if [ -t 1 ]; then
  C_RESET='\033[0m'; C_BOLD='\033[1m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_CYAN='\033[36m'; C_RED='\033[31m'
else
  C_RESET=''; C_BOLD=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''; C_RED=''
fi
log()  { printf '%b[collect-bg]%b %s\n'     "$C_BOLD$C_CYAN"   "$C_RESET" "$*"; }
warn() { printf '%b[collect-bg:WARN]%b %s\n' "$C_BOLD$C_YELLOW" "$C_RESET" "$*" >&2; }
err()  { printf '%b[collect-bg:ERR]%b %s\n'  "$C_BOLD$C_RED"    "$C_RESET" "$*" >&2; }

# 检查是否已有运行中的实例
if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    err "already running: pid=$PID (use scripts/collect-stop.sh to stop)"
    exit 1
  fi
  warn "stale pid file found (pid=$PID not alive), removing"
  rm -f "$PID_FILE"
fi

TS="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/collect-$TS.log"

log "starting collect.sh in background..."
log "log: $LOG_FILE"
log "pid file: $PID_FILE"

# setsid 让子进程脱离 tty，避免 SSH 断开触发 SIGHUP；nohup 作兜底
if command -v setsid >/dev/null 2>&1; then
  setsid nohup bash scripts/collect.sh "$@" >"$LOG_FILE" 2>&1 &
else
  nohup bash scripts/collect.sh "$@" >"$LOG_FILE" 2>&1 &
fi
BG_PID=$!
echo "$BG_PID" > "$PID_FILE"

# 刷新 latest 软链
ln -sfn "$(basename "$LOG_FILE")" "$LOG_DIR/collect-latest.log"

sleep 0.5
if ! kill -0 "$BG_PID" 2>/dev/null; then
  err "process died immediately — see $LOG_FILE"
  exit 1
fi

log "started pid=$BG_PID"
printf '%b[collect-bg]%b follow log: %btail -f %s%b\n' \
  "$C_BOLD$C_GREEN" "$C_RESET" \
  "$C_BOLD" "$LOG_FILE" "$C_RESET"

#!/usr/bin/env bash
# 一键启动整站：控制服务器同时服务静态前端 + 采集控制 API
#
# 用法：
#   bash scripts/start-server.sh              # 默认 127.0.0.1:8787
#   HOST=0.0.0.0 PORT=8080 bash scripts/start-server.sh
#   bash scripts/start-server.sh --bg         # 后台运行（PID 写 collector/data/server.pid）
#
# 访问：
#   前端   http://<HOST>:<PORT>/
#   登录   http://<HOST>:<PORT>/pages/login.html  (默认 admin / build2026)
#   采集控制台在 admin 后台侧栏第二项

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

PYTHON="${PYTHON:-python3}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8787}"
BG_MODE=0

for arg in "$@"; do
  case "$arg" in
    --bg) BG_MODE=1 ;;
    --host=*) HOST="${arg#--host=}" ;;
    --port=*) PORT="${arg#--port=}" ;;
    *)
      echo "[start-server] unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

if [ -t 1 ]; then
  C_RESET='\033[0m'; C_BOLD='\033[1m'; C_GREEN='\033[32m'; C_CYAN='\033[36m'; C_YELLOW='\033[33m'
else
  C_RESET=''; C_BOLD=''; C_GREEN=''; C_CYAN=''; C_YELLOW=''
fi

# init-db 没跑过时友好提示
if [ ! -f collector/data/collector.db ]; then
  printf '%b[start-server]%b DB 不存在，先跑一次 init-db...\n' "$C_BOLD$C_YELLOW" "$C_RESET"
  $PYTHON -m collector.cli init-db || true
fi

export HOST PORT

if [ "$BG_MODE" -eq 1 ]; then
  mkdir -p collector/data collector/logs
  PID_FILE="collector/data/server.pid"
  if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "${OLD_PID:-}" ] && kill -0 "$OLD_PID" 2>/dev/null; then
      echo "[start-server:ERR] already running pid=$OLD_PID" >&2
      exit 1
    fi
    rm -f "$PID_FILE"
  fi
  LOG="collector/logs/server-$(date +%Y%m%d-%H%M%S).log"
  nohup $PYTHON -u -m collector.control_server > "$LOG" 2>&1 &
  echo $! > "$PID_FILE"
  ln -sfn "$(basename "$LOG")" collector/logs/server-latest.log
  printf '%b[start-server]%b started pid=%s\n' "$C_BOLD$C_GREEN" "$C_RESET" "$(cat "$PID_FILE")"
  printf '  %blog%b  %s\n'  "$C_BOLD$C_CYAN" "$C_RESET" "$LOG"
  printf '  %burl%b  http://%s:%s/\n' "$C_BOLD$C_CYAN" "$C_RESET" "$HOST" "$PORT"
  printf '  %bstop%b kill %s\n' "$C_BOLD$C_CYAN" "$C_RESET" "$(cat "$PID_FILE")"
  exit 0
fi

printf '%b[start-server]%b foreground mode — Ctrl+C 停止\n' "$C_BOLD$C_CYAN" "$C_RESET"
exec $PYTHON -u -m collector.control_server

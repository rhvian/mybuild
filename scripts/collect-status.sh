#!/usr/bin/env bash
# 查看后台采集状态
#
# 用法：
#   bash scripts/collect-status.sh           # 打印进程 + 日志尾 30 行 + DB 快照
#   bash scripts/collect-status.sh -n 100    # 日志尾 100 行
#   bash scripts/collect-status.sh -f        # 实时跟随日志（等同 tail -f）

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

PID_FILE="collector/data/collect.pid"
LOG_DIR="collector/logs"
LATEST_LOG="$LOG_DIR/collect-latest.log"

TAIL_LINES=30
FOLLOW=0
while [ $# -gt 0 ]; do
  case "$1" in
    -n) TAIL_LINES="$2"; shift 2 ;;
    -f) FOLLOW=1; shift ;;
    *)  shift ;;
  esac
done

if [ -t 1 ]; then
  C_RESET='\033[0m'; C_BOLD='\033[1m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_CYAN='\033[36m'; C_RED='\033[31m'; C_DIM='\033[2m'
else
  C_RESET=''; C_BOLD=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''; C_RED=''; C_DIM=''
fi

head() { printf '%b== %s ==%b\n' "$C_BOLD$C_CYAN" "$*" "$C_RESET"; }

# 1. 进程
head "process"
if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    STARTED="$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/^ *//')"
    CPUTIME="$(ps -o etime= -p "$PID" 2>/dev/null | sed 's/^ *//')"
    printf '  %bstatus%b    running\n'   "$C_GREEN" "$C_RESET"
    printf '  pid       %s\n'            "$PID"
    printf '  started   %s\n'            "$STARTED"
    printf '  elapsed   %s\n'            "$CPUTIME"
  else
    printf '  %bstatus%b    stopped (stale pid file: %s)\n' "$C_YELLOW" "$C_RESET" "$PID"
  fi
else
  printf '  %bstatus%b    not running (no pid file)\n' "$C_YELLOW" "$C_RESET"
fi

# 2. 日志
echo
head "log (tail -n $TAIL_LINES)"
if [ ! -e "$LATEST_LOG" ]; then
  # 尝试找最新 log
  LATEST_LOG="$(ls -1t "$LOG_DIR"/collect-*.log 2>/dev/null | grep -v latest | head -n1)"
fi
if [ -n "${LATEST_LOG:-}" ] && [ -e "$LATEST_LOG" ]; then
  printf '  %bfile%b  %s\n' "$C_DIM" "$C_RESET" "$(readlink -f "$LATEST_LOG" 2>/dev/null || echo "$LATEST_LOG")"
  echo
  tail -n "$TAIL_LINES" "$LATEST_LOG"
else
  printf '  %bno logs yet%b\n' "$C_YELLOW" "$C_RESET"
fi

# 3. DB 快照
echo
head "db snapshot"
python3 - <<'PY' || true
import sqlite3, sys
try:
    c = sqlite3.connect('collector/data/collector.db')
    r = c.execute('SELECT run_id, started_at, ended_at, raw_count, normalized_count, issue_count, failed_source_count FROM ingestion_run ORDER BY rowid DESC LIMIT 1').fetchone()
    if r:
        print(f"  latest_run     {r[0]}")
        print(f"  started        {r[1]}")
        print(f"  ended          {r[2] or '-'}")
        print(f"  raw / norm     {r[3]} / {r[4]}   (issues={r[5]}, failed_sources={r[6]})")
    else:
        print("  no runs yet")
    print()
    print("  cumulative by entity_type:")
    for row in c.execute('SELECT entity_type, COUNT(*) FROM normalized_entity GROUP BY entity_type ORDER BY 2 DESC LIMIT 8'):
        print(f"    {row[0]:20s} {row[1]}")
    c.close()
except Exception as e:
    print(f"  db read failed: {e}", file=sys.stderr)
PY

# 4. follow
if [ "$FOLLOW" -eq 1 ] && [ -n "${LATEST_LOG:-}" ] && [ -e "$LATEST_LOG" ]; then
  echo
  head "following log (Ctrl+C to exit)"
  tail -f "$LATEST_LOG"
fi

#!/usr/bin/env bash
# 采集健康检查
#
# 退出码：0 正常 / 1 警告 / 2 严重
# 适合 cron + 告警脚本组合（示例）：
#   bash scripts/check-health.sh --quiet || bash scripts/alert-mail.sh "采集异常"
#
# 检查项：
#   1. DB 文件存在且可读
#   2. runner_lock 是否 stale（已过期但未清理）
#   3. 最近 ingestion_run ended_at 距今 > 36h（且没有正在跑的 lock）-> CRITICAL
#   4. 最近 run failed_source_count > 0 -> WARN
#   5. 最近 run issue_count > 100 -> WARN
#
# 用法：
#   bash scripts/check-health.sh                 # 打印人类可读摘要
#   bash scripts/check-health.sh --quiet         # 仅异常时输出（cron 友好）
#   bash scripts/check-health.sh --max-age 24    # 覆盖 36h 阈值

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

DB="collector/data/collector.db"
MAX_AGE_HOURS=36
MAX_ISSUES=100
QUIET=0

while [ $# -gt 0 ]; do
  case "$1" in
    --quiet)      QUIET=1; shift ;;
    --max-age)    MAX_AGE_HOURS="$2"; shift 2 ;;
    --max-issues) MAX_ISSUES="$2"; shift 2 ;;
    --db)         DB="$2"; shift 2 ;;
    *)            shift ;;
  esac
done

if [ -t 1 ]; then
  C_RESET='\033[0m'; C_BOLD='\033[1m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_RED='\033[31m'; C_DIM='\033[2m'
else
  C_RESET=''; C_BOLD=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_DIM=''
fi

RESULT_FILE="$(mktemp)"
trap 'rm -f "$RESULT_FILE"' EXIT

python3 - "$DB" "$MAX_AGE_HOURS" "$MAX_ISSUES" >"$RESULT_FILE" <<'PY'
import sqlite3, sys, datetime, os
db_path, max_age_h, max_issues = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])

lines = []
status = 0

def bump(level):
    global status
    if level > status:
        status = level

if not os.path.exists(db_path):
    print(2)
    print(f"CRITICAL\tDB not found: {db_path}")
    sys.exit(0)

try:
    c = sqlite3.connect(db_path)
except Exception as e:
    print(2)
    print(f"CRITICAL\tDB open failed: {e}")
    sys.exit(0)

now = datetime.datetime.now(datetime.timezone.utc)

lock_row = None
try:
    lock_row = c.execute('SELECT lock_name, owner_id, acquired_at, expires_at FROM runner_lock').fetchone()
except Exception:
    lines.append(("WARN", "runner_lock table missing — run `init-db` first"))
    bump(1)

lock_held = False
if lock_row:
    try:
        exp = datetime.datetime.fromisoformat(lock_row[3].replace("Z", "+00:00"))
        if exp > now:
            lock_held = True
            lines.append(("OK", f"runner_lock held (owner={lock_row[1]}, expires={lock_row[3]})"))
        else:
            age_min = int((now - exp).total_seconds() / 60)
            lines.append(("WARN", f"stale runner_lock: expired {age_min}m ago (owner={lock_row[1]})"))
            bump(1)
    except Exception as e:
        lines.append(("WARN", f"runner_lock parse failed: {e}"))
        bump(1)

r = c.execute('SELECT run_id, started_at, ended_at, raw_count, normalized_count, issue_count, failed_source_count FROM ingestion_run ORDER BY rowid DESC LIMIT 1').fetchone()
if not r:
    lines.append(("CRITICAL", "no ingestion_run records — collector has never run"))
    bump(2)
else:
    run_id, started_at, ended_at, raw, norm, issues, failed = r
    lines.append(("INFO", f"latest_run={run_id} raw={raw} norm={norm} issues={issues} failed_sources={failed}"))
    if ended_at and not lock_held:
        try:
            end_dt = datetime.datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            age_h = (now - end_dt).total_seconds() / 3600
            if age_h > max_age_h:
                lines.append(("CRITICAL", f"latest run ended {age_h:.1f}h ago (> {max_age_h}h threshold)"))
                bump(2)
            else:
                lines.append(("OK", f"latest run ended {age_h:.1f}h ago"))
        except Exception as e:
            lines.append(("WARN", f"ended_at parse failed: {e}"))
            bump(1)
    if failed and failed > 0:
        lines.append(("WARN", f"latest run had {failed} failed sources"))
        bump(1)
    if issues and issues > max_issues:
        lines.append(("WARN", f"latest run had {issues} quality issues (> {max_issues} threshold)"))
        bump(1)

try:
    rows = c.execute('SELECT entity_type, COUNT(*) FROM normalized_entity GROUP BY entity_type ORDER BY 2 DESC').fetchall()
    summary = ", ".join(f"{t}={n}" for t, n in rows[:6])
    lines.append(("INFO", f"cumulative: {summary}"))
except Exception as e:
    lines.append(("WARN", f"cumulative read failed: {e}"))

c.close()

print(status)
for lvl, msg in lines:
    print(f"{lvl}\t{msg}")
PY

STATUS="$(sed -n '1p' "$RESULT_FILE")"
STATUS="${STATUS:-2}"

color_for_level() {
  case "$1" in
    CRITICAL) printf "%s" "$C_BOLD$C_RED" ;;
    WARN)     printf "%s" "$C_BOLD$C_YELLOW" ;;
    OK)       printf "%s" "$C_BOLD$C_GREEN" ;;
    INFO)     printf "%s" "$C_DIM" ;;
    *)        printf "" ;;
  esac
}

print_summary() {
  case "$STATUS" in
    0) printf '%b[health]%b STATUS=OK\n'       "$C_BOLD$C_GREEN"  "$C_RESET" ;;
    1) printf '%b[health]%b STATUS=WARN\n'     "$C_BOLD$C_YELLOW" "$C_RESET" ;;
    *) printf '%b[health]%b STATUS=CRITICAL\n' "$C_BOLD$C_RED"    "$C_RESET" ;;
  esac
  tail -n +2 "$RESULT_FILE" | while IFS=$'\t' read -r LVL MSG; do
    [ -z "${LVL:-}" ] && continue
    COLOR="$(color_for_level "$LVL")"
    printf '  %b%-8s%b %s\n' "$COLOR" "$LVL" "$C_RESET" "$MSG"
  done
}

if [ "$QUIET" -eq 1 ] && [ "$STATUS" -eq 0 ]; then
  exit 0
fi
print_summary
exit "$STATUS"

#!/usr/bin/env bash
# 全量采集启动脚本 — 流式模式，per-batch 提交，支持 Ctrl+C 安全中断
#
# 用法（在项目根目录下）：
#   bash scripts/collect.sh                     # 执行全量采集（流式）
#   bash scripts/collect.sh --no-init           # 跳过 init-db 直接采集
#   bash scripts/collect.sh --skip-export
#   bash scripts/collect.sh --only enterprise   # 只跑企业源
#   bash scripts/collect.sh --only staff        # 只跑人员反查
#   bash scripts/collect.sh --only project      # 只跑项目反查
#   bash scripts/collect.sh --only all          # 等同不加 --only
#   bash scripts/collect.sh --source-id jzsc_company_live,jzsc_staff_by_company_live
#   PYTHON=python3.11 bash scripts/collect.sh
#
# 中断保护：
#   Ctrl+C 会安全停止 — 已完成的每个 region/source 数据已落库。
#   下次运行会从头再跑一遍（数据幂等，不会重复）。

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

PYTHON="${PYTHON:-python3}"
DO_INIT=1
EXTRA_ARGS=()

# --only enterprise|staff|project|all 映射到 source_id
map_only_to_source_id() {
  case "$1" in
    enterprise) echo "jzsc_company_live" ;;
    staff)      echo "jzsc_staff_by_company_live" ;;
    project)    echo "jzsc_project_by_company_live" ;;
    all|"")     echo "" ;;
    *)          echo "__invalid__" ;;
  esac
}

while [ $# -gt 0 ]; do
  case "$1" in
    --no-init)     DO_INIT=0; shift ;;
    --skip-export) EXTRA_ARGS+=("--skip-export"); shift ;;
    --only)
      if [ $# -lt 2 ]; then
        echo "[collect:ERR] --only requires an argument (enterprise|staff|project|all)" >&2
        exit 2
      fi
      MAPPED="$(map_only_to_source_id "$2")"
      if [ "$MAPPED" = "__invalid__" ]; then
        echo "[collect:ERR] --only: unknown category '$2' (expected enterprise|staff|project|all)" >&2
        exit 2
      fi
      if [ -n "$MAPPED" ]; then
        EXTRA_ARGS+=("--source-id" "$MAPPED")
      fi
      shift 2
      ;;
    --only=*)
      VAL="${1#--only=}"
      MAPPED="$(map_only_to_source_id "$VAL")"
      if [ "$MAPPED" = "__invalid__" ]; then
        echo "[collect:ERR] --only: unknown category '$VAL' (expected enterprise|staff|project|all)" >&2
        exit 2
      fi
      if [ -n "$MAPPED" ]; then
        EXTRA_ARGS+=("--source-id" "$MAPPED")
      fi
      shift
      ;;
    *)             EXTRA_ARGS+=("$1"); shift ;;
  esac
done

# ANSI 颜色
if [ -t 1 ]; then
  C_RESET='\033[0m'; C_BOLD='\033[1m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_CYAN='\033[36m'; C_RED='\033[31m'
else
  C_RESET=''; C_BOLD=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''; C_RED=''
fi

log() { printf '%b[collect]%b %s\n' "$C_BOLD$C_CYAN" "$C_RESET" "$*"; }
err() { printf '%b[collect:ERR]%b %s\n' "$C_BOLD$C_RED" "$C_RESET" "$*" >&2; }

# 1. 检查是否有遗留的 runner_lock
log "checking runner_lock..."
LOCK_INFO="$(
  $PYTHON - <<'PY'
import sqlite3
try:
    c = sqlite3.connect('collector/data/collector.db')
    r = c.execute('SELECT lock_name, owner_id, acquired_at, expires_at FROM runner_lock').fetchone()
    print('' if not r else '|'.join(str(x) for x in r))
    c.close()
except Exception:
    print('')
PY
)"
if [ -n "$LOCK_INFO" ]; then
  printf '%b[collect:WARN]%b stale runner_lock detected: %s\n' "$C_BOLD$C_YELLOW" "$C_RESET" "$LOCK_INFO"
  EXTRA_ARGS=("--force-unlock" "${EXTRA_ARGS[@]}")
fi

# 2. init-db
if [ "$DO_INIT" -eq 1 ]; then
  log "init-db (loading sources.json into source_registry)..."
  $PYTHON -m collector.cli init-db
fi

# 3. 启动采集
log "starting streaming pipeline..."
log "press Ctrl+C at any time — partial data already committed"
log "----------------------------------------"
# -u: 强制 stdout 不缓冲，进度实时打印
set +e
$PYTHON -u -m collector.cli run-stream "${EXTRA_ARGS[@]}"
EXIT_CODE=$?
set -e
log "----------------------------------------"

# 4. 报告结果
log "summary:"
$PYTHON - <<'PY'
import sqlite3
c = sqlite3.connect('collector/data/collector.db')
r = c.execute('SELECT run_id, started_at, ended_at, raw_count, normalized_count, issue_count, failed_source_count FROM ingestion_run ORDER BY rowid DESC LIMIT 1').fetchone()
if r:
    print(f"  latest_run: {r[0]}")
    print(f"  started: {r[1]}")
    print(f"  ended:   {r[2]}")
    print(f"  raw_count: {r[3]}  normalized: {r[4]}  issues: {r[5]}  failed_sources: {r[6]}")
print()
print("  cumulative by entity_type:")
for row in c.execute('SELECT entity_type, COUNT(*) FROM normalized_entity GROUP BY entity_type ORDER BY 2 DESC'):
    print(f"    {row[0]:20s} {row[1]}")
c.close()
PY

if [ $EXIT_CODE -eq 0 ]; then
  printf '%b[collect]%b done.\n' "$C_BOLD$C_GREEN" "$C_RESET"
else
  err "pipeline exited with code $EXIT_CODE (partial data still committed)"
fi
exit $EXIT_CODE

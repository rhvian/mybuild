#!/usr/bin/env bash
# SQLite 数据库每日备份（gzip + 30 天滚动）。
#
# 用法：
#   bash scripts/backup-db.sh                                  # 默认备份 collector.db + operation.db
#   BACKUP_DIR=/var/backups/mybuild bash scripts/backup-db.sh  # 自定义目的地
#   KEEP_DAYS=14 bash scripts/backup-db.sh                     # 保留天数
#
# 建议 cron：
#   0 3 * * * /opt/mybuild/scripts/backup-db.sh

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

BACKUP_DIR="${BACKUP_DIR:-/var/backups/mybuild}"
KEEP_DAYS="${KEEP_DAYS:-30}"
DATE="$(date +%Y%m%d-%H%M%S)"

if [ -t 1 ]; then
  C_RESET='\033[0m'; C_BOLD='\033[1m'; C_GREEN='\033[32m'; C_RED='\033[31m'; C_CYAN='\033[36m'
else
  C_RESET=''; C_BOLD=''; C_GREEN=''; C_RED=''; C_CYAN=''
fi
log() { printf '%b[backup]%b %s\n' "$C_BOLD$C_CYAN" "$C_RESET" "$*"; }
err() { printf '%b[backup:ERR]%b %s\n' "$C_BOLD$C_RED" "$C_RESET" "$*" >&2; }

if ! mkdir -p "$BACKUP_DIR"; then
  err "cannot create $BACKUP_DIR"
  exit 1
fi

backup_one() {
  local src="$1" label="$2"
  if [ ! -f "$src" ]; then
    log "skip $label: $src not found"
    return 0
  fi
  local dst="$BACKUP_DIR/${label}-${DATE}.db"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$src" ".backup '$dst'"
  else
    cp "$src" "$dst"
  fi
  gzip -f "$dst"
  local size
  size="$(du -h "$dst.gz" | cut -f1)"
  log "backed up $label -> $dst.gz ($size)"
}

backup_one "collector/data/collector.db" "collector"
backup_one "backend/data/operation.db"   "operation"

# 清理超期
find "$BACKUP_DIR" -name "*.db.gz" -mtime +"$KEEP_DAYS" -print -delete | while read -r f; do
  log "cleaned $f"
done

printf '%b[backup]%b done. retained files:\n' "$C_BOLD$C_GREEN" "$C_RESET"
ls -lh "$BACKUP_DIR"/*.db.gz 2>/dev/null | tail -10

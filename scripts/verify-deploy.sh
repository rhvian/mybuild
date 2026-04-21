#!/usr/bin/env bash
# 部署后验证脚本 — 一键体检 L1 控制 + L2 后端 + 采集定时 + 告警 健康度。
#
# 退出码：
#   0  全绿
#   1  警告（某些可选组件未启用或告警）
#   2  严重（无法对外服务）
#
# 用法：
#   bash scripts/verify-deploy.sh                   # 全量检查，人类可读输出
#   bash scripts/verify-deploy.sh --quiet           # 只有异常输出（cron 友好）
#   bash scripts/verify-deploy.sh --api-host 127.0.0.1:8000     # 指定 backend 端口
#   bash scripts/verify-deploy.sh --control-host 127.0.0.1:8787 # 指定 control_server 端口
#
# 检查项：
#   1. systemd unit 状态：mybuild-server / mybuild-backend / mybuild-collect.timer / mybuild-health.timer
#   2. 端口监听：控制服务、backend
#   3. HTTP 可达：/ping、/system/health、/api/ping
#   4. 关键文件：collector.db、operation.db、jwt_secret.key
#   5. 备份目录可写
#   6. nginx 配置语法 + reload 状态（如装了 nginx）
#   7. 最近一次采集是否超过 36h（调用 check-health.sh）
#
# 不动任何状态（read-only）。

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 2

API_HOST="${MYBUILD_BACKEND_HOST:-127.0.0.1:8000}"
CONTROL_HOST="${MYBUILD_CONTROL_HOST:-127.0.0.1:8787}"
BACKUP_DIR="${MYBUILD_BACKUP_DIR:-/var/backups/mybuild}"
QUIET=0

while [ $# -gt 0 ]; do
  case "$1" in
    --quiet)        QUIET=1; shift ;;
    --api-host)     API_HOST="$2"; shift 2 ;;
    --control-host) CONTROL_HOST="$2"; shift 2 ;;
    --backup-dir)   BACKUP_DIR="$2"; shift 2 ;;
    *)              shift ;;
  esac
done

if [ -t 1 ]; then
  C_RESET='\033[0m'; C_BOLD='\033[1m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_RED='\033[31m'; C_DIM='\033[2m'
else
  C_RESET=''; C_BOLD=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_DIM=''
fi

STATUS=0   # 0 OK / 1 WARN / 2 CRITICAL
declare -a LINES

bump() {
  if [ "$1" -gt "$STATUS" ]; then STATUS="$1"; fi
}

record() {
  local lvl="$1"; shift
  local msg="$*"
  LINES+=("${lvl}|${msg}")
  case "$lvl" in
    CRIT) bump 2 ;;
    WARN) bump 1 ;;
  esac
}

has() { command -v "$1" >/dev/null 2>&1; }

# ------------------------------------------------------------------
# 1. systemd unit 状态
# ------------------------------------------------------------------
if has systemctl; then
  for unit in mybuild-server mybuild-backend; do
    st="$(systemctl is-active "$unit" 2>/dev/null || true)"
    case "$st" in
      active)   record OK   "unit $unit: active" ;;
      inactive|failed) record CRIT "unit $unit: $st（没跑起来，外部访问会 502）" ;;
      *)        record WARN "unit $unit: $st（可能未安装；执行 sudo bash deploy/install.sh）" ;;
    esac
  done
  for unit in mybuild-collect.timer mybuild-health.timer; do
    st="$(systemctl is-active "$unit" 2>/dev/null || true)"
    if [ "$st" = "active" ]; then
      record OK "timer $unit: active"
    else
      record WARN "timer $unit: $st（采集 / 健康检查不会自动跑）"
    fi
  done
else
  record WARN "systemctl 不可用（非 Linux / 无 systemd），跳过 unit 检查"
fi

# ------------------------------------------------------------------
# 2. 端口监听（ss / netstat / 直接 TCP 探）
# ------------------------------------------------------------------
probe_port() {
  local host_port="$1"
  local host="${host_port%:*}"
  local port="${host_port##*:}"
  python3 - <<PY 2>/dev/null
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
try:
    s.connect(("$host", $port))
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
}

if probe_port "$CONTROL_HOST"; then
  record OK "control_server 监听 $CONTROL_HOST"
else
  record CRIT "control_server 不监听 $CONTROL_HOST（采集控制台 / 管理页无法访问）"
fi

if probe_port "$API_HOST"; then
  record OK "backend 监听 $API_HOST"
else
  record CRIT "backend 不监听 $API_HOST（/auth /users /alerts /appeals /projects 全部不可达）"
fi

# ------------------------------------------------------------------
# 3. HTTP 可达（curl）
# ------------------------------------------------------------------
if has curl; then
  for ep in "http://$CONTROL_HOST/api/ping" "http://$API_HOST/system/health"; do
    code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$ep" 2>/dev/null || echo "000")"
    case "$code" in
      200)     record OK   "HTTP 200  $ep" ;;
      000)     record CRIT "HTTP 不可达  $ep（连接失败）" ;;
      *)       record WARN "HTTP $code  $ep" ;;
    esac
  done
else
  record WARN "curl 不可用，跳过 HTTP 可达性检查"
fi

# ------------------------------------------------------------------
# 4. 关键文件
# ------------------------------------------------------------------
check_file() {
  local path="$1"
  local label="$2"
  local severity="${3:-WARN}"
  if [ -f "$path" ]; then
    local size
    size="$(stat -c %s "$path" 2>/dev/null || stat -f %z "$path" 2>/dev/null || echo 0)"
    record OK "file $label 存在（$size bytes）"
  else
    record "$severity" "file $label 不存在（$path）"
  fi
}

check_file "collector/data/collector.db" "collector.db" CRIT
check_file "backend/data/operation.db"   "operation.db" WARN
check_file "backend/data/jwt_secret.key" "jwt_secret.key" CRIT

# ------------------------------------------------------------------
# 5. 备份目录可写
# ------------------------------------------------------------------
if [ -d "$BACKUP_DIR" ]; then
  if [ -w "$BACKUP_DIR" ]; then
    record OK "备份目录可写 $BACKUP_DIR"
  else
    record WARN "备份目录 $BACKUP_DIR 存在但无写权限"
  fi
else
  record WARN "备份目录 $BACKUP_DIR 不存在（未部署 / 权限）"
fi

# ------------------------------------------------------------------
# 6. nginx（可选）
# ------------------------------------------------------------------
if has nginx; then
  if nginx -t >/dev/null 2>&1; then
    record OK "nginx 配置语法 OK"
  else
    record CRIT "nginx 配置语法失败（运行 sudo nginx -t 看详情）"
  fi
fi

# ------------------------------------------------------------------
# 7. 最近采集健康度（复用 check-health.sh）
# ------------------------------------------------------------------
if [ -x scripts/check-health.sh ]; then
  # --quiet 模式只输出异常行；这里拿退出码即可
  if bash scripts/check-health.sh --quiet >/dev/null 2>&1; then
    record OK "采集健康检查：通过"
  else
    rc=$?
    case "$rc" in
      1) record WARN "采集健康检查：WARN（运行 bash scripts/check-health.sh 看详情）" ;;
      *) record CRIT "采集健康检查：CRITICAL（最近 run 超期 / DB 不可读）" ;;
    esac
  fi
fi

# ------------------------------------------------------------------
# 汇总输出
# ------------------------------------------------------------------
color_for() {
  case "$1" in
    OK)   printf "%s" "$C_BOLD$C_GREEN" ;;
    WARN) printf "%s" "$C_BOLD$C_YELLOW" ;;
    CRIT) printf "%s" "$C_BOLD$C_RED" ;;
    *)    printf "%s" "$C_DIM" ;;
  esac
}

print_summary() {
  case "$STATUS" in
    0) printf '%b[verify]%b STATUS=OK（全部绿）\n'         "$C_BOLD$C_GREEN"  "$C_RESET" ;;
    1) printf '%b[verify]%b STATUS=WARN（可选项未就绪）\n' "$C_BOLD$C_YELLOW" "$C_RESET" ;;
    *) printf '%b[verify]%b STATUS=CRITICAL（需处理）\n'   "$C_BOLD$C_RED"    "$C_RESET" ;;
  esac
  for entry in "${LINES[@]}"; do
    lvl="${entry%%|*}"
    msg="${entry#*|}"
    COLOR="$(color_for "$lvl")"
    printf '  %b%-4s%b  %s\n' "$COLOR" "$lvl" "$C_RESET" "$msg"
  done
}

if [ "$QUIET" -eq 1 ] && [ "$STATUS" -eq 0 ]; then
  exit 0
fi

print_summary
exit "$STATUS"

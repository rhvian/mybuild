"""
collector.control_server — L1 级控制后端 + 静态站托管

职责：
  1. 同端口服务静态前端（index.html / pages / scripts / styles）
  2. 暴露 /api/* JSON 接口：认证 / 采集启停 / 状态 / 日志 / 健康
  3. Bearer Token 鉴权（token = sha256("user:pass")，白名单存配置文件）

设计取舍：
  - 零外部依赖：仅用 Python stdlib（http.server + threading + subprocess + sqlite3）
  - 不是 FastAPI，不做 ORM / Swagger / JWT；这些都是 L2 后端的任务
  - 绑定 127.0.0.1，不对外暴露；如需对外请前置 nginx + auth

启动：
  python3 -m collector.control_server              # 127.0.0.1:8787
  HOST=0.0.0.0 PORT=8080 python3 -m collector.control_server

默认凭据：admin / build2026
修改方式：编辑 scripts/auth.js 的 ALLOWED_CREDS，同时在此脚本内也会自动读 allowed hash。
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import signal
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "collector" / "data" / "collector.db"
PID_FILE = PROJECT_ROOT / "collector" / "data" / "collect.pid"
LOG_DIR = PROJECT_ROOT / "collector" / "logs"
LATEST_LOG_LINK = LOG_DIR / "collect-latest.log"

# 与 scripts/auth.js ALLOWED_CREDS 同源的默认凭据
# sha256("admin:build2026")
DEFAULT_ALLOWED = {"56cae9c8e0450378092d0e86824f175e91c11acc79cfc4d4f986e5cb4719192f"}
ALLOWED_HASHES_FILE = PROJECT_ROOT / "collector" / "data" / "control_allowed_hashes.txt"

ONLY_MAP = {
    "enterprise": "jzsc_company_live",
    "staff": "jzsc_staff_by_company_live",
    "project": "jzsc_project_by_company_live",
    "all": "",
}


def load_allowed_hashes() -> set[str]:
    """优先读外部文件；文件不存在/空则用默认 DEFAULT_ALLOWED。"""
    if ALLOWED_HASHES_FILE.exists():
        try:
            text = ALLOWED_HASHES_FILE.read_text(encoding="utf-8")
            entries = {
                line.strip().lower()
                for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            }
            if entries:
                return entries
        except Exception as e:
            print(f"[control] load allowed hashes failed: {e}", file=sys.stderr)
    return set(DEFAULT_ALLOWED)


ALLOWED_HASHES = load_allowed_hashes()


# ===== JWT 兼容层（与 backend FastAPI 共用 secret，纯 stdlib 验证 HS256）=====

BACKEND_JWT_SECRET_FILE = PROJECT_ROOT / "backend" / "data" / "jwt_secret.key"


def _load_jwt_secret() -> Optional[str]:
    """读 backend/data/jwt_secret.key；不存在则返回 None（禁用 JWT 路径）。"""
    if not BACKEND_JWT_SECRET_FILE.exists():
        return None
    try:
        s = BACKEND_JWT_SECRET_FILE.read_text(encoding="utf-8").strip()
        return s or None
    except Exception:
        return None


def _b64url_decode(data: str) -> bytes:
    import base64
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _verify_hs256_jwt(token: str, secret: str) -> Optional[Dict[str, Any]]:
    """仅支持 HS256，返回 payload dict 或 None。"""
    import hashlib
    import hmac
    import time

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts
        # 校验 header alg=HS256
        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != "HS256":
            return None
        # 验证签名
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        # 过期检查
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        # 类型检查（只接受 access token，不接受 refresh）
        if payload.get("type") not in (None, "access"):
            return None
        return payload
    except Exception:
        return None


# ===== 认证失败限流（内存；进程重启清零）=====
# key: client IP；value: (locked_until_epoch_or_0, fail_count, window_start_epoch)
_AUTH_FAIL_STATE: Dict[str, Tuple[float, int, float]] = {}


# ===== 省份代码 → 中文名（与 export_live_data 保持一致） =====
_PROVINCE_NAMES: Dict[str, str] = {
    "110000": "北京", "120000": "天津", "130000": "河北", "140000": "山西",
    "150000": "内蒙古", "210000": "辽宁", "220000": "吉林", "230000": "黑龙江",
    "310000": "上海", "320000": "江苏", "330000": "浙江", "340000": "安徽",
    "350000": "福建", "360000": "江西", "370000": "山东", "410000": "河南",
    "420000": "湖北", "430000": "湖南", "440000": "广东", "450000": "广西",
    "460000": "海南", "500000": "重庆", "510000": "四川", "520000": "贵州",
    "530000": "云南", "540000": "西藏", "610000": "陕西", "620000": "甘肃",
    "630000": "青海", "640000": "宁夏", "650000": "新疆",
    "000000": "全国",
}


def _province_name(code: Optional[str]) -> str:
    if not code:
        return "未知"
    return _PROVINCE_NAMES.get(str(code), str(code))


# ===== 工具函数 =====

def _epoch_now() -> float:
    import time
    return time.time()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_path_in(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _read_pid() -> Optional[int]:
    try:
        if not PID_FILE.exists():
            return None
        raw = PID_FILE.read_text().strip()
        return int(raw) if raw else None
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_log_tail(lines: int = 100) -> Tuple[Optional[str], list[str]]:
    """返回 (log_file_path_str, 最后 N 行)。"""
    log_file = None
    if LATEST_LOG_LINK.exists():
        log_file = LATEST_LOG_LINK.resolve()
    else:
        candidates = sorted(LOG_DIR.glob("collect-*.log"), reverse=True)
        candidates = [c for c in candidates if "latest" not in c.name]
        if candidates:
            log_file = candidates[0]
    if not log_file or not log_file.exists():
        return None, []
    try:
        with log_file.open("r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return str(log_file), [line.rstrip("\n") for line in all_lines[-max(1, int(lines)) :]]
    except Exception as e:
        return str(log_file), [f"[control] read log failed: {e}"]


def _collect_db_snapshot() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "latest_run": None,
        "cumulative": [],
        "runner_lock": None,
    }
    if not DB_PATH.exists():
        out["error"] = "db_not_found"
        return out
    try:
        c = sqlite3.connect(str(DB_PATH))
        try:
            r = c.execute(
                "SELECT run_id, started_at, ended_at, raw_count, normalized_count, issue_count, failed_source_count "
                "FROM ingestion_run ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if r:
                out["latest_run"] = {
                    "run_id": r[0],
                    "started_at": r[1],
                    "ended_at": r[2],
                    "raw_count": r[3],
                    "normalized_count": r[4],
                    "issue_count": r[5],
                    "failed_source_count": r[6],
                }
            rows = c.execute(
                "SELECT entity_type, COUNT(*) FROM normalized_entity GROUP BY entity_type ORDER BY 2 DESC"
            ).fetchall()
            out["cumulative"] = [{"entity_type": t, "count": n} for t, n in rows]
            try:
                lock = c.execute(
                    "SELECT lock_name, owner_id, acquired_at, expires_at FROM runner_lock"
                ).fetchone()
                if lock:
                    out["runner_lock"] = {
                        "lock_name": lock[0],
                        "owner_id": lock[1],
                        "acquired_at": lock[2],
                        "expires_at": lock[3],
                    }
            except sqlite3.OperationalError:
                # runner_lock 表不存在（init-db 未执行）
                pass
            try:
                recent = c.execute(
                    "SELECT run_id, started_at, ended_at, raw_count, normalized_count, issue_count, failed_source_count "
                    "FROM ingestion_run ORDER BY rowid DESC LIMIT 8"
                ).fetchall()
                out["recent_runs"] = [
                    {
                        "run_id": x[0],
                        "started_at": x[1],
                        "ended_at": x[2],
                        "raw_count": x[3],
                        "normalized_count": x[4],
                        "issue_count": x[5],
                        "failed_source_count": x[6],
                    }
                    for x in recent
                ]
            except Exception:
                out["recent_runs"] = []
        finally:
            c.close()
    except Exception as e:
        out["error"] = f"db_read_failed: {e}"
    return out


def _process_status() -> Dict[str, Any]:
    pid = _read_pid()
    if not pid:
        return {"running": False, "pid": None, "elapsed_sec": None}
    if not _pid_alive(pid):
        return {"running": False, "pid": pid, "stale": True, "elapsed_sec": None}
    # elapsed
    elapsed_sec = None
    try:
        # /proc/<pid>/stat 22 项 starttime (clock ticks since boot)
        # fields[1] 可能含空格（proc name 有括号），用 rfind(')') 跳过 comm 字段。
        stat_line = open(f"/proc/{pid}/stat").read()
        rparen = stat_line.rfind(")")
        tail = stat_line[rparen + 2 :].split()
        starttime_ticks = int(tail[19])  # starttime (22nd field overall, tail index 19)
        clk_tck = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        with open("/proc/uptime", "r") as f:
            uptime_sec = float(f.read().split()[0])
        start_since_boot_sec = starttime_ticks / clk_tck
        elapsed_sec = max(0, int(uptime_sec - start_since_boot_sec))
    except Exception:
        elapsed_sec = None
    return {"running": True, "pid": pid, "elapsed_sec": elapsed_sec}


def _run_subprocess(cmd: list[str], timeout: int = 15) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", f"{type(e).__name__}: {e}"


# ===== 请求处理 =====

class ControlHandler(BaseHTTPRequestHandler):
    server_version = "mybuild-control/0.3"

    def log_message(self, format: str, *args: Any) -> None:
        # 简化日志
        sys.stderr.write(
            f"[{datetime.now().strftime('%H:%M:%S')}] {self.address_string()} {format % args}\n"
        )

    # ===== 公共返回工具 =====

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_text(404, "not found")
            return
        ctype, _ = mimetypes.guess_type(str(path))
        ctype = ctype or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if path.name.endswith(".json"):
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ===== 认证 =====

    def _check_auth(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        token = header[7:].strip()
        # 1) 试作 JWT（兼容 backend FastAPI 登录）
        if token.count(".") == 2:
            secret = _load_jwt_secret()
            if secret:
                payload = _verify_hs256_jwt(token, secret)
                if payload is not None:
                    return True
        # 2) 退回 SHA-256 静态白名单（旧 L1 auth.js 用的路径）
        return token.lower() in ALLOWED_HASHES

    # ===== 路由分发 =====

    def do_OPTIONS(self) -> None:  # CORS preflight
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def _allow_cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path.startswith("/api/"):
            self._route_api("GET", path, qs, body=None)
        else:
            self._route_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        body: Any = None
        ctype = self.headers.get("Content-Type", "")
        if raw:
            if "application/json" in ctype:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except Exception:
                    body = None
            else:
                body = raw
        if path.startswith("/api/"):
            self._route_api("POST", path, qs, body=body)
        else:
            self._send_text(405, "method not allowed")

    # ===== 静态文件 =====

    def _route_static(self, path: str) -> None:
        if path in ("", "/"):
            target = PROJECT_ROOT / "index.html"
        else:
            rel = path.lstrip("/")
            target = PROJECT_ROOT / rel
        if not _safe_path_in(PROJECT_ROOT, target):
            self._send_text(403, "forbidden")
            return
        if target.is_dir():
            target = target / "index.html"
        self._send_file(target)

    # ===== API =====

    def _route_api(self, method: str, path: str, qs: Dict[str, list[str]], body: Any) -> None:
        # 先 CORS 头（send_response 之后无法再 send_header，在各 _send_* 之前先写好）
        # _send_json 里没有 CORS 头，这里不再重复；控制台与 API 同源时不需要

        # 无需鉴权的路径（公共查询 + 登录登出 + ping）
        if path == "/api/auth/verify" and method == "POST":
            return self._api_auth_verify(body or {})
        if path == "/api/ping" and method == "GET":
            return self._send_json(200, {"ok": True, "ts": _utc_now_iso()})
        if path == "/api/auth/logout" and method == "POST":
            return self._send_json(200, {"ok": True, "note": "client should discard token"})

        # 业务查询（只读 SQL）公开，便于公众搜索 / 详情页无需登录
        if path == "/api/stats" and method == "GET":
            return self._api_stats()
        for etype in ("enterprise", "staff", "tender"):
            base = f"/api/{etype}"
            if method == "GET":
                if path == base:
                    return self._api_list_entities(etype, qs)
                if path.startswith(base + "/") and "/" not in path[len(base) + 1:]:
                    return self._api_get_entity(etype, path[len(base) + 1:])

        # 之后的端点全部要鉴权（采集控制 / 运行历史 / 健康）
        if not self._check_auth():
            return self._send_json(401, {"ok": False, "error": "unauthorized"})

        if path == "/api/collect/status" and method == "GET":
            return self._api_collect_status()
        if path == "/api/collect/start" and method == "POST":
            return self._api_collect_start(body or {})
        if path == "/api/collect/stop" and method == "POST":
            return self._api_collect_stop()
        if path == "/api/collect/logs" and method == "GET":
            return self._api_collect_logs(qs)
        if path == "/api/health" and method == "GET":
            return self._api_health()
        if path == "/api/runs" and method == "GET":
            return self._api_runs(qs)

        self._send_json(404, {"ok": False, "error": "not_found", "path": path})

    # ===== API 实现 =====

    def _api_auth_verify(self, body: Dict[str, Any]) -> None:
        ip = self.client_address[0]
        now = _epoch_now()
        # 失败限流：同 IP 10 分钟窗口 5 次失败则锁 15 分钟
        state = _AUTH_FAIL_STATE.get(ip)
        if state:
            locked_until, count, window_start = state
            if locked_until and locked_until > now:
                wait = int(locked_until - now)
                return self._send_json(
                    429,
                    {"ok": False, "error": "rate_limited", "retry_after_sec": wait},
                )
        user = str(body.get("user", "")).strip()
        pwd = str(body.get("password", ""))
        if not user or not pwd:
            return self._send_json(400, {"ok": False, "error": "missing_user_or_password"})
        token = _sha256(f"{user}:{pwd}")
        if token in ALLOWED_HASHES:
            _AUTH_FAIL_STATE.pop(ip, None)  # 成功即清零
            return self._send_json(200, {"ok": True, "token": token, "user": user})

        # 登录失败：计数
        prev = _AUTH_FAIL_STATE.get(ip)
        if not prev or now - prev[2] > 600:
            _AUTH_FAIL_STATE[ip] = (0.0, 1, now)
        else:
            new_count = prev[1] + 1
            locked_until = 0.0
            if new_count >= 5:
                locked_until = now + 900
                _AUTH_FAIL_STATE[ip] = (locked_until, new_count, prev[2])
            else:
                _AUTH_FAIL_STATE[ip] = (0.0, new_count, prev[2])
        return self._send_json(401, {"ok": False, "error": "invalid_credentials"})

    def _api_collect_status(self) -> None:
        proc = _process_status()
        log_file, tail = _read_log_tail(40)
        db = _collect_db_snapshot()
        payload = {
            "ok": True,
            "ts": _utc_now_iso(),
            "process": proc,
            "log_file": log_file,
            "log_tail": tail,
            **db,
        }
        self._send_json(200, payload)

    def _api_collect_start(self, body: Dict[str, Any]) -> None:
        proc = _process_status()
        if proc.get("running"):
            return self._send_json(
                409,
                {"ok": False, "error": "already_running", "pid": proc.get("pid")},
            )
        only = str(body.get("only", "all")).strip().lower()
        if only not in ONLY_MAP:
            return self._send_json(
                400,
                {"ok": False, "error": "invalid_only", "accepted": list(ONLY_MAP.keys())},
            )
        cmd = ["bash", "scripts/collect-bg.sh"]
        if ONLY_MAP[only]:
            cmd.extend(["--only", only])
        rc, out, err = _run_subprocess(cmd, timeout=30)
        ok = rc == 0
        status = 200 if ok else 500
        return self._send_json(
            status,
            {
                "ok": ok,
                "rc": rc,
                "cmd": " ".join(cmd),
                "stdout": out.splitlines()[-20:],
                "stderr": err.splitlines()[-20:],
            },
        )

    def _api_collect_stop(self) -> None:
        rc, out, err = _run_subprocess(["bash", "scripts/collect-stop.sh"], timeout=60)
        ok = rc == 0
        status = 200 if ok else 500
        return self._send_json(
            status,
            {
                "ok": ok,
                "rc": rc,
                "stdout": out.splitlines()[-20:],
                "stderr": err.splitlines()[-20:],
            },
        )

    def _api_collect_logs(self, qs: Dict[str, list[str]]) -> None:
        try:
            lines = int((qs.get("lines") or ["200"])[0])
        except Exception:
            lines = 200
        lines = max(10, min(5000, lines))
        log_file, tail = _read_log_tail(lines)
        return self._send_json(200, {"ok": True, "log_file": log_file, "lines": tail})

    def _api_health(self) -> None:
        rc, out, err = _run_subprocess(
            ["bash", "scripts/check-health.sh", "--quiet"], timeout=20
        )
        # --quiet 下正常时无输出；异常时有输出
        level_map = {0: "OK", 1: "WARN", 2: "CRITICAL"}
        return self._send_json(
            200,
            {
                "ok": True,
                "status_code": rc,
                "status": level_map.get(rc, f"UNKNOWN({rc})"),
                "detail": out.splitlines()[-50:],
                "stderr": err.splitlines()[-10:],
            },
        )

    # ===== 业务查询（只读 SQL） =====

    def _open_db(self) -> Optional[sqlite3.Connection]:
        if not DB_PATH.exists():
            return None
        try:
            c = sqlite3.connect(str(DB_PATH))
            c.row_factory = sqlite3.Row
            return c
        except Exception as e:
            self._send_json(500, {"ok": False, "error": f"db_open_failed: {e}"})
            return None

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        raw = d.pop("raw_payload_json", None)
        payload: Any = None
        if raw:
            try:
                payload = json.loads(raw)
            except Exception:
                payload = None
        d["payload"] = payload
        return d

    @staticmethod
    def _parse_paging(qs: Dict[str, list[str]]) -> Tuple[int, int]:
        try:
            page = max(1, int((qs.get("page") or ["1"])[0]))
        except Exception:
            page = 1
        try:
            size = int((qs.get("size") or ["20"])[0])
        except Exception:
            size = 20
        size = max(1, min(200, size))
        return page, size

    def _api_list_entities(self, entity_type: str, qs: Dict[str, list[str]]) -> None:
        page, size = self._parse_paging(qs)
        q = (qs.get("q") or [""])[0].strip()
        province = (qs.get("province") or [""])[0].strip()

        where = ["entity_type = ?"]
        args: list[Any] = [entity_type]
        if q:
            where.append("(name LIKE ? OR uscc LIKE ? OR project_code LIKE ?)")
            kw = f"%{q}%"
            args.extend([kw, kw, kw])
        if province:
            # 支持 6 位代码或中文名（city_name 含"市"字符，province_code 6 位）
            where.append("(province_code = ? OR city_name LIKE ?)")
            args.extend([province, f"%{province}%"])
        where_clause = " AND ".join(where)

        c = self._open_db()
        if not c:
            return
        try:
            total_row = c.execute(
                f"SELECT COUNT(*) FROM normalized_entity WHERE {where_clause}", args
            ).fetchone()
            total = int(total_row[0]) if total_row else 0
            offset = (page - 1) * size
            rows = c.execute(
                f"SELECT * FROM normalized_entity WHERE {where_clause} "
                f"ORDER BY id DESC LIMIT ? OFFSET ?",
                args + [size, offset],
            ).fetchall()
            items = [self._row_to_entity(r) for r in rows]
            return self._send_json(
                200,
                {
                    "ok": True,
                    "entity_type": entity_type,
                    "total": total,
                    "page": page,
                    "size": size,
                    "pages": (total + size - 1) // size if size else 1,
                    "items": items,
                },
            )
        finally:
            c.close()

    def _api_get_entity(self, entity_type: str, raw_id: str) -> None:
        try:
            eid = int(raw_id)
        except Exception:
            return self._send_json(400, {"ok": False, "error": "invalid_id"})
        c = self._open_db()
        if not c:
            return
        try:
            r = c.execute(
                "SELECT * FROM normalized_entity WHERE id = ? AND entity_type = ?",
                (eid, entity_type),
            ).fetchone()
            if not r:
                return self._send_json(404, {"ok": False, "error": "not_found", "id": eid})
            return self._send_json(200, {"ok": True, "item": self._row_to_entity(r)})
        finally:
            c.close()

    def _api_runs(self, qs: Dict[str, list[str]]) -> None:
        page, size = self._parse_paging(qs)
        c = self._open_db()
        if not c:
            return
        try:
            total_row = c.execute("SELECT COUNT(*) FROM ingestion_run").fetchone()
            total = int(total_row[0]) if total_row else 0
            rows = c.execute(
                "SELECT run_id, started_at, ended_at, raw_count, normalized_count, "
                "issue_count, failed_source_count "
                "FROM ingestion_run ORDER BY rowid DESC LIMIT ? OFFSET ?",
                (size, (page - 1) * size),
            ).fetchall()
            items = [dict(r) for r in rows]
            return self._send_json(
                200,
                {
                    "ok": True,
                    "total": total,
                    "page": page,
                    "size": size,
                    "pages": (total + size - 1) // size if size else 1,
                    "items": items,
                },
            )
        finally:
            c.close()

    def _api_stats(self) -> None:
        c = self._open_db()
        if not c:
            return
        try:
            # 分类总数
            total_by_type = {
                row["entity_type"]: int(row["n"])
                for row in c.execute(
                    "SELECT entity_type, COUNT(*) AS n FROM normalized_entity GROUP BY entity_type"
                ).fetchall()
            }
            # 省份 × 企业
            province_enterprise = [
                {
                    "province_code": r["province_code"],
                    "province_name": _province_name(r["province_code"]),
                    "count": int(r["n"]),
                }
                for r in c.execute(
                    "SELECT province_code, COUNT(*) AS n FROM normalized_entity "
                    "WHERE entity_type = 'enterprise' "
                    "GROUP BY province_code ORDER BY n DESC LIMIT 40"
                ).fetchall()
            ]
            # 人员注册类别
            staff_rows = c.execute(
                "SELECT raw_payload_json FROM normalized_entity WHERE entity_type = 'staff'"
            ).fetchall()
            reg_counter: Dict[str, int] = {}
            for r in staff_rows:
                try:
                    p = json.loads(r["raw_payload_json"] or "{}")
                    t = p.get("register_type", "").strip()
                    if t:
                        reg_counter[t] = reg_counter.get(t, 0) + 1
                except Exception:
                    pass
            staff_register_type = sorted(
                [{"register_type": k, "count": v} for k, v in reg_counter.items()],
                key=lambda x: x["count"],
                reverse=True,
            )[:20]
            # 最近 runs
            recent_runs = [
                dict(r) for r in c.execute(
                    "SELECT run_id, started_at, ended_at, raw_count, normalized_count, "
                    "issue_count, failed_source_count "
                    "FROM ingestion_run ORDER BY rowid DESC LIMIT 10"
                ).fetchall()
            ]
            stats = {
                "total_by_type": total_by_type,
                "total_enterprise": total_by_type.get("enterprise", 0),
                "total_staff": total_by_type.get("staff", 0),
                "total_tender": total_by_type.get("tender", 0),
                "province_enterprise": province_enterprise,
                "staff_register_type": staff_register_type,
                "recent_runs": recent_runs,
            }
            return self._send_json(200, {"ok": True, "stats": stats, "ts": _utc_now_iso()})
        finally:
            c.close()


# ===== 服务启动 =====

def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8787"))

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "collector" / "data").mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((host, port), ControlHandler)
    server.daemon_threads = True

    def _graceful(_signum, _frame):
        print("\n[control] signal received, shutting down...", file=sys.stderr)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _graceful)
    signal.signal(signal.SIGTERM, _graceful)

    print("=" * 52)
    print(" 全国诚信市场建筑管理平台 · control server v0.3")
    print("=" * 52)
    print(f" listening   http://{host}:{port}/")
    print(f" allowed     {len(ALLOWED_HASHES)} credential hash(es)")
    print("             (default: admin / build2026)")
    print(f" log dir     {LOG_DIR}")
    print(f" db path     {DB_PATH}")
    print("=" * 52)
    print(" endpoints:")
    print("   GET  /                        静态前端")
    print("   POST /api/auth/verify         账号口令校验")
    print("   GET  /api/collect/status      采集状态 + 日志尾")
    print("   POST /api/collect/start       启动采集（body: {only:enterprise|staff|project|all}）")
    print("   POST /api/collect/stop        停止采集")
    print("   GET  /api/collect/logs        日志尾（?lines=N）")
    print("   GET  /api/health              健康检查结果")
    print("=" * 52)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        print("[control] server stopped.", file=sys.stderr)


if __name__ == "__main__":
    main()

# 使用手册

> 面向：产品经理 / 运营 / 运维 / 刚接手的开发。
> 定位：**看完这份就能把平台跑起来 + 采到数据 + 用起来**。
> 生产部署见 [DEPLOYMENT.md](DEPLOYMENT.md)，本文档只讲"怎么用"。

---

## 目录

1. [5 分钟跑起来](#1-5-分钟跑起来)
2. [怎么采集数据](#2-怎么采集数据)
3. [浏览器能看到什么](#3-浏览器能看到什么)
4. [管理后台 7 个 Tab 说明](#4-管理后台-7-个-tab-说明)
5. [API 直接调用](#5-api-直接调用)
6. [常见故障与处理](#6-常见故障与处理)
7. [备份与升级](#7-备份与升级)

---

## 1. 5 分钟跑起来

### 1.1 前置

- Python 3.11+
- Linux / macOS / WSL2（Windows 原生未测试）
- ~1.5 GB 磁盘（Playwright chromium）

### 1.2 安装依赖

```bash
cd /mnt/g/mycode/mybuild
pip install -r requirements.txt
python3 -m playwright install chromium     # 采集国家平台需要
```

### 1.3 首次初始化

```bash
python3 -m collector.cli init-db            # 建采集 DB 表，同步 sources.json
# 采集 DB 在 collector/data/collector.db
# 用户 DB backend/data/operation.db 在 backend 启动时自动创建
```

### 1.4 一条命令启动整站

```bash
bash scripts/start-server.sh                # 前台启动控制服务 :8787（Ctrl+C 停）
# 或后台：
bash scripts/start-server.sh --bg
```

这会同时启动：
- **控制服务**（:8787）：静态前端 + `/api/collect/*` + `/api/enterprise` 等公众查询 API
- **L2 后端**（:8000）：`/auth /users /alerts /appeals /projects` 等管理 API（需单独起）

启 L2 后端（新终端）：

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### 1.5 打开浏览器

| URL | 作用 |
|-----|------|
| http://127.0.0.1:8787/ | 公众首页（搜索 / 看板）|
| http://127.0.0.1:8787/pages/login.html | 管理登录（`admin@example.com / build2026`）|
| http://127.0.0.1:8000/docs | FastAPI 自动 API 文档（Swagger UI）|

---

## 2. 怎么采集数据

### 2.1 快速采集（最常用）

```bash
# 后台启动全部启用的 source（参见 sources.json 的 enabled=true）
bash scripts/collect-bg.sh

# 看进度（追踪日志）
bash scripts/collect-status.sh -f

# 停止（安全，已落库的不丢）
bash scripts/collect-stop.sh
```

日志：`collector/logs/collect-<YYYYMMDD>-<HHMMSS>.log`（软链 `collect-latest.log` 指向最新）。

### 2.2 分类采集（只跑一个 source）

```bash
bash scripts/collect-bg.sh --only enterprise    # 只采国家平台企业列表（~25 min）
bash scripts/collect-bg.sh --only staff         # 只采人员（按企业反查，~5 h）
bash scripts/collect-bg.sh --only project       # 只采项目（按企业反查，~5 h）
bash scripts/collect-bg.sh --only all           # 全部 enabled source（默认）
```

### 2.3 前台采集（会话关就停）

```bash
bash scripts/collect.sh                         # 前台流式采集
bash scripts/collect.sh --only enterprise       # 前台只跑某个分类
bash scripts/collect.sh --no-init               # 跳过 init-db（第 2 次以后）
```

### 2.4 增量采集（自动）

系统内置 cursor 增量。

- 首次跑 `jzsc_company_live` 耗时 ~25 min，采全量 ~14k 企业
- 第二次跑 `jzsc_staff_by_company_live` 时自动只反查"上次之后新增"的企业
- 无新增时秒级完成

手动查看 cursor：

```bash
sqlite3 collector/data/collector.db \
  "SELECT source_id, cursor_value, updated_at FROM source_cursor"
```

### 2.5 采集控制台（浏览器 UI 操作）

登录 `http://127.0.0.1:8787/pages/admin.html`，进入 **采集控制台** tab：

- 启动 / 停止按钮（对应 `collect-bg.sh --only X`）
- 实时日志（2.5 秒轮询拉取日志尾）
- 运行状态（PID / 运行时长 / 最近 run 记录）
- 健康检查（点"检查健康"按钮 → 调用 `check-health.sh --quiet`）

### 2.6 启停哪些 source

查看当前启用：

```bash
python3 -c "import json; [print(f'{s[\"source_id\"]:<32s} enabled={s[\"enabled\"]}') for s in json.load(open('collector/config/sources.json'))]"
```

修改 `collector/config/sources.json` 的 `enabled` 字段后，必须：

```bash
python3 -m collector.cli init-db            # 同步到 source_registry 表
```

### 2.7 采完看结果

```bash
# 累计条数（按实体类型）
sqlite3 collector/data/collector.db \
  "SELECT entity_type, COUNT(*) FROM normalized_entity GROUP BY entity_type ORDER BY 2 DESC"

# 最近 10 次 run
sqlite3 collector/data/collector.db \
  "SELECT run_id, started_at, raw_count, normalized_count, issue_count FROM ingestion_run ORDER BY rowid DESC LIMIT 10"

# 浙江的企业（只有浙江 source 跑过才有）
sqlite3 collector/data/collector.db \
  "SELECT COUNT(*) FROM normalized_entity WHERE source_id LIKE 'zj_%'"
```

采集同时会自动导出：
- `scripts/live-data.json`（公众前台读这个做首屏，~1.3 MB，500 条 / 实体）
- `scripts/source-routes.json`（详情页"源站入口"面板）

---

## 3. 浏览器能看到什么

### 3.1 公众页（无需登录）

| 路径 | 说明 |
|------|------|
| `/` | 首页：三实体统计卡 + 企业搜索框 + 地图 + 最近运行 |
| `/pages/dashboard.html` | 数据看板：省份柱图 + 注册类别饼图 + 时间趋势 |
| `/pages/enterprise.html?id=N` | 企业详情（基本信息 + 资质占位 + 注册人员 + 工程项目 + 信用占位）|
| `/pages/person.html?id=N` | 人员详情（基本信息 + 信用 / 执业 / 处罚占位）|
| `/pages/project.html?id=N` | 项目详情（基本信息 + 信用 / 参与主体 / 风险占位）|
| `/pages/policies.html` | 政策法规（8 条示例，附件为"建设中"占位）|

搜索 → 点企业 → 跳详情页，详情页展示关联人员和项目的真实数据（如果已采集）。

### 3.2 登录入口

`http://127.0.0.1:8787/pages/login.html`

- 左侧"用户登录"：**邮箱 + 密码**（不是用户名）
- 默认：`admin@example.com / build2026`
- 右侧"企业注册"：v0.4 暂未开放，仅占位

登录流程：
1. 浏览器提交到 `POST /auth/login`（走 L2 后端）
2. 拿到 `access_token`（JWT，30 min 有效）+ `refresh_token`（7 天）
3. `localStorage['cm_auth']` 存 token + 过期时间
4. 跳转 `admin.html`

**同一 JWT 可同时访问**：
- L2 后端 `/auth /users /alerts /appeals /projects`
- L1 控制服务 `/api/collect/* /api/health`（control_server.py 支持 HS256 JWT 验证）

---

## 4. 管理后台 7 个 Tab 说明

### 4.1 工作台（overview）

- 三实体累计卡片（enterprise / staff / tender）
- 最近 10 次采集 run 的表格
- 省份分布柱图（top 15）

数据源：`/api/stats`（L1 控制服务，只读 SQL）。

### 4.2 采集控制台（collect）

- 启停按钮 + 实时日志（2.5s 轮询）
- 运行状态卡（运行中 / 空闲 / 异常，含 PID 和运行时长）
- 健康检查按钮 + 徽章（OK / WARN / CRITICAL）
- 最近 8 次 run 的详细表

操作详见 [§2.5](#25-采集控制台浏览器-ui-操作)。

### 4.3 企业管理（enterprises）

- 企业分页列表，每页 20 条（上限 200）
- 搜索框（企业名 / 统一社会信用代码模糊）
- 省份下拉过滤
- 点"查看" → 跳企业详情页

数据源：`/api/enterprise?q=&province=&page=&size=`（公众可用的 SQL 查询 API）。

### 4.4 预警处置（warnings）

完整工单状态机：`open → ack → resolved/dismissed → (reopen)`。

- 顶部 counts_by_status 徽章（未处理 / 处理中 / 已解决 / 已驳回）
- 筛选：状态 / 严重度 / 类别 / 关键词
- 列表 → 点一行 → 右侧详情 + 时间线（所有动作历史）
- 动态按钮：根据当前状态显示可执行的动作
  - `open` → "受理" / "直接关闭" / "误报"
  - `ack` → "解决" / "误报"
  - `resolved` / `dismissed` → "重开"
- 任何状态都能"加备注"（不改状态）
- "新建预警"按钮 → 表单（来源 / 严重度 / 标题 / 实体 key）

数据源：`/alerts`（L2 后端，需 `alert:read` / `alert:write` 权限）。

### 4.5 申诉审核（惩戒）(penalties)

企业提交申诉 → 审核员审查。

- 状态机：`submitted → under_review → approved/rejected/need_more → (need_more 可补材料重提)`
- 筛选：状态 / 类别（信用 / 资质 / 惩戒）/ 关键词
- 审核员动作：`start_review` / `approve` / `reject` / `need_more`
- "代企业提交"按钮（测试用，要 `appeal:submit` 权限，默认 admin 没有；建 business 角色账号操作）

数据源：`/appeals`（L2 后端，需 `appeal:review` 权限看列表）。

### 4.6 项目监管（projects）

监管项目库 + 巡检记录。

- 字段：tender_key / 项目名 / 承建方 / 风险（low/medium/high/critical）/ 监管等级（normal/priority/special）/ 状态
- 顶部 counts_by_risk 徽章
- 筛选：风险 / 监管等级 / 状态 / 关键词
- 编辑：调整风险 / 监管等级 / 状态（PATCH 实时落）
- **登记巡检**：note 必填，后台 `inspection_count++`、`last_inspection_at` / `last_inspection_note` 更新
- 新建：tender_key 必填，重复返 409

数据源：`/projects`（L2 后端，需 `project:read` / `project:write` 权限）。

### 4.7 用户权限（users）

用户 CRUD + 角色分配。

- 列表：ID / 邮箱 / 姓名 / 角色标签 / 启用状态 / 最近登录 / 创建时间
- 高亮"当前账号"行
- 新建：邮箱 / 密码 / 姓名 / 角色（guest / business / gov / auditor / admin）
- 编辑：改邮箱 / 姓名 / 角色 / 启用状态；密码留空则不改，填了就改
- 删除：二次确认；**当前账号不可自删**

5 角色预设权限（`backend/bootstrap.py::DEFAULT_ROLES`）：

| 角色 | 权限数 | 主要能做 |
|------|--------|---------|
| admin | 12 | 全开 |
| auditor | 7 | 读用户 / 审核预警 / 审核申诉 / 管理项目 |
| gov | 3 | 审核申诉 / 管理项目 |
| business | 1 | 提交申诉 |
| guest | 0 | 只能登录 |

数据源：`/users`（L2 后端，需 `user:read` / `user:write` 权限）。

---

## 5. API 直接调用

### 5.1 公众查询（免登录）

```bash
# 企业分页搜索
curl "http://127.0.0.1:8787/api/enterprise?q=建筑&page=1&size=10"

# 企业详情
curl "http://127.0.0.1:8787/api/enterprise/59713"

# 人员列表
curl "http://127.0.0.1:8787/api/staff?q=张&size=5"

# 项目列表
curl "http://127.0.0.1:8787/api/tender?size=5"

# 全局统计（看板用）
curl "http://127.0.0.1:8787/api/stats"
```

### 5.2 管理 API（需 JWT）

```bash
# 登录拿 token
TOKEN=$(curl -s -X POST -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"build2026"}' \
  http://127.0.0.1:8000/auth/login | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 带 token 调其它接口
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/auth/me
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/users
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/alerts?status=open&size=5"

# 创建新用户
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"email":"bob@example.com","password":"bob12345","role_id":4}' \
  http://127.0.0.1:8000/users

# 受理预警
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"ack","note":"我来查"}' \
  http://127.0.0.1:8000/alerts/1/action
```

### 5.3 采集控制 API（需 JWT）

```bash
# 同一 JWT 给 L1 控制服务用
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/api/collect/status
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/api/health

# 触发采集
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"only":"enterprise"}' \
  http://127.0.0.1:8787/api/collect/start

# 停止
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8787/api/collect/stop
```

### 5.4 自动 API 文档

- L2 FastAPI：`http://127.0.0.1:8000/docs` — Swagger UI，可直接点击调用
- L2 FastAPI：`http://127.0.0.1:8000/redoc` — ReDoc 样式（更适合阅读）
- L1 控制服务：无 Swagger，接口见 `collector/control_server.py::_route_api`

---

## 6. 常见故障与处理

### 6.1 采集启动失败：`runner_lock` 残留

```
[control] stale runner_lock detected, adding --force-unlock
```

自动修复。`collect.sh` / `collect-bg.sh` 会检测过期 lock 并加 `--force-unlock`。手动处理：

```bash
python3 -c "import sqlite3; c=sqlite3.connect('collector/data/collector.db'); c.execute('DELETE FROM runner_lock'); c.commit()"
```

### 6.2 采集跑了但前端看不到新数据

前端读 `scripts/live-data.json` 和 `scripts/source-routes.json`，采集结束后会自动重新导出。如果没更新：

```bash
python3 -m collector.cli export-live         # 手动重导
python3 -m collector.cli export-routes
```

### 6.3 登录失败：`账号或密码错误`

1. 检查邮箱是不是 `admin@example.com`（不是 `admin`）
2. 检查密码 `build2026`（全小写 + 数字，无空格）
3. 连续错 5 次会触发限流（同 IP 锁 15 min），返 `429`；等过期或换 IP
4. 后端要起来（`:8000`），没起来会返 `网络异常：...（请确认 backend 已启动）`

### 6.4 浏览器无法访问 admin

- 先 `curl http://127.0.0.1:8787/` 看是不是 200（控制服务起来了吗）
- admin.html 加了 auth-guard：未登录会**直接跳回 login.html**，正常

### 6.5 Playwright 进程残留

采集异常 SIGKILL 后 chromium 可能残留：

```bash
pkill -9 -f "chrome-headless\|playwright\|collector.cli"
```

### 6.6 JWT secret 丢了 / 换机器

`backend/data/jwt_secret.key` 是 bcrypt 验证和 token 签名的密钥。丢了：
- 已签发的 token 全部失效（所有用户需重新登录）
- 启动 backend 会自动生成新 secret

### 6.7 省级平台接入？

参见 [HAR_CAPTURE.md](HAR_CAPTURE.md)。简言之：
- 浙江已接入（`zj_jzsc_*` 两个 source）
- 其它省需要你抓 HAR（参见文档 §3 步骤）
- 需要注册 / 企业实名认证的平台直接放弃（记录在 `HAR_CAPTURE.md` 放弃表）

---

## 7. 备份与升级

### 7.1 备份

```bash
bash scripts/backup-db.sh                   # 手动备份，默认 /var/backups/mybuild
BACKUP_DIR=/your/path bash scripts/backup-db.sh
```

生产应挂到 cron 或 systemd timer（模板见 [DEPLOYMENT.md](DEPLOYMENT.md)）。

### 7.2 升级

```bash
git pull
pip install -r requirements.txt --upgrade
bash scripts/verify-deploy.sh               # 确认服务健康
# 如果有 alembic 迁移：
alembic upgrade head
```

### 7.3 健康检查

```bash
bash scripts/check-health.sh                # 采集层健康
bash scripts/verify-deploy.sh               # 全栈部署健康（systemd + 端口 + 文件 + 备份）
```

两者区别：
- `check-health.sh` 面向**采集运营**（最近 run 的新鲜度 / 失败源 / 质量问题）
- `verify-deploy.sh` 面向**部署运维**（systemd unit / 端口监听 / 关键文件 / nginx 语法）

---

## 附：关键命令速查

```bash
# 启停整站
bash scripts/start-server.sh [--bg]
uvicorn backend.main:app --port 8000

# 采集
bash scripts/collect-bg.sh [--only enterprise|staff|project|all]
bash scripts/collect-status.sh [-f]
bash scripts/collect-stop.sh

# 查看
sqlite3 collector/data/collector.db "SELECT entity_type, COUNT(*) FROM normalized_entity GROUP BY 1"
bash scripts/check-health.sh
bash scripts/verify-deploy.sh

# 开发
pytest -q                                   # 52 个测试
ruff check backend/ collector/ tests/       # 零告警
python3 -m playwright install chromium     # 首次装浏览器

# 部署
sudo bash deploy/install.sh
sudo systemctl status mybuild-*
```

# 部署与运维指南

> 最后更新：2026-04-20
> 适用于 v0.3（流式 pipeline + 控制服务器 + admin 采集控制台）
> 一键部署：`bash deploy/install.sh`（先看清注释再跑，不要无脑执行）

---

## 一、架构概览

**三个协同进程：**

1. **control_server**（`python3 -m collector.control_server`）
   - 同端口同时服务：静态前端 + `/api/*` 采集控制 API
   - 默认 127.0.0.1:8787，由 `HOST` / `PORT` 环境变量覆盖
   - systemd unit: `deploy/mybuild-server.service`
2. **采集 pipeline**（`bash scripts/collect.sh` 或 control_server 触发）
   - 流式 per-batch 提交；Ctrl+C 安全中断；runner_lock 防并发
   - systemd unit + timer: `deploy/mybuild-collect.service/.timer`（每日 02:00）
3. **nginx**（可选，对外部署时必需）
   - 反代 control_server + HTTPS 终止 + 静态缓存 + gzip
   - 配置：`deploy/nginx-mybuild.conf`

**数据流：**

```
collector/config/sources.json
          │
          ▼
  collector.cli run-stream ─── Playwright + JZSC API
          │
          ▼
  collector/data/collector.db (SQLite)
          │
          ├──▶ scripts/live-data.json / source-routes.json（采集结束导出）
          │
          ▼
  collector.control_server
   ├─ GET  /                   静态前端（index.html / pages/ / scripts/ / styles/）
   ├─ GET  /api/collect/status 实时状态
   ├─ POST /api/collect/start  触发 scripts/collect-bg.sh
   ├─ POST /api/collect/stop   scripts/collect-stop.sh
   └─ GET  /api/health         scripts/check-health.sh 结果
          │
          ▼
  浏览器（默认 admin / build2026，登录后 admin 侧栏"采集控制台"）
```

---

## 二、上线前 checklist

- [ ] 域名 + HTTPS 证书（Let's Encrypt / Cloudflare 任选）
- [ ] Linux x86_64 服务器，≥ 4 GB 内存（Playwright chromium 占大头）
- [ ] Python 3.10+、nginx、mail 或 SMTP 凭据
- [ ] 代码放到 `/opt/mybuild/`
- [ ] 首次 `python3 -m collector.cli init-db` 已执行
- [ ] 改过 `scripts/auth.js::ALLOWED_CREDS` 和 `collector/data/control_allowed_hashes.txt`（二者同步）
- [ ] `/etc/mybuild/alert.env` 写入真实 SMTP + ALERT_EMAIL（参考 `deploy/alert.env.sample`）

---

## 三、前端部署（nginx + control_server）

**推荐配置：** nginx 做 HTTPS 终止 + 反代到 control_server；control_server 同时服务静态和 API。

配置模板在 `deploy/nginx-mybuild.conf`，已经预置：

- HTTP → HTTPS 301
- gzip（JSON 压缩，live-data.json 默认约 1MB 级）
- `/api/*` 禁缓存、超时 600s（启停采集可能阻塞）
- `live-data.json` / `source-routes.json` / `interface-catalog.json` 禁缓存
- 其它 JS/CSS/图片缓存 1h
- HSTS / X-Content-Type-Options / Referrer-Policy 安全头

部署：
```bash
sudo cp deploy/nginx-mybuild.conf /etc/nginx/sites-available/mybuild
sudo sed -i 's/your-domain.com/实际域名/g' /etc/nginx/sites-available/mybuild
sudo ln -sf /etc/nginx/sites-available/mybuild /etc/nginx/sites-enabled/mybuild
sudo nginx -t && sudo systemctl reload nginx
```

> 旧版把静态文件由 nginx 直接服务的做法已废弃 —— 控制台 API 与静态同源，统一交给 control_server 更简单。

### 历史：只用 nginx + 静态（无控制服务）

如果不需要 admin 控制台，只展示静态数据：

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    root /opt/mybuild;
    index index.html;

    # 主站
    location / {
        try_files $uri $uri/ /index.html;
    }

    # live-data.json 不缓存（内容会更新）
    location /scripts/live-data.json {
        add_header Cache-Control "no-store, no-cache, must-revalidate";
    }
    location /scripts/source-routes.json {
        add_header Cache-Control "no-store, no-cache, must-revalidate";
    }

    # 其他静态资源缓存 1 小时
    location ~* \.(js|css|png|jpg|svg)$ {
        expires 1h;
        add_header Cache-Control "public";
    }

    # 压缩 JSON（live-data.json 可能 10+ MB）
    gzip on;
    gzip_types application/json application/javascript text/css;
    gzip_min_length 1024;
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}
```

**注意：**
- `scripts/live-data.json` 默认仅导出近期样本（每类 500 条 + stats），通常约 1MB 级；可通过 `export_live_json(limit_each=...)` 调整。
- 如果 staff 采到 130k 条，需要拆分为独立 JSON 或改后端 API（见"后续优化"）。

---

## 四、采集调度（systemd）

所有 unit file 已在 `deploy/` 目录：

| 文件 | 作用 |
|------|------|
| `deploy/mybuild-server.service` | control_server 长驻（前端 + API） |
| `deploy/mybuild-collect.service` | 一次性采集任务（由 timer 触发） |
| `deploy/mybuild-collect.timer` | 每日 02:00 触发 collect.service |
| `deploy/mybuild-health.service` | 健康检查（失败走 alert-mail.sh） |
| `deploy/mybuild-health.timer` | 每小时触发 health.service |
| `deploy/alert.env.sample` | SMTP 告警配置模板 |

### 4.1 安装

```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo mkdir -p /etc/mybuild
sudo cp deploy/alert.env.sample /etc/mybuild/alert.env
sudo chmod 600 /etc/mybuild/alert.env
sudo chown root:mybuild /etc/mybuild/alert.env
# 编辑 /etc/mybuild/alert.env 填真实 SMTP_HOST / SMTP_USER / SMTP_PASS / ALERT_EMAIL
sudo systemctl daemon-reload
sudo systemctl enable --now mybuild-server.service
sudo systemctl enable --now mybuild-collect.timer
sudo systemctl enable --now mybuild-health.timer
```

### 4.2 运维

[Install]
WantedBy=timers.target
```

### 4.2 运维常用命令

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mybuild-collect.timer
sudo systemctl list-timers | grep mybuild
sudo journalctl -u mybuild-server.service -f   # control_server 日志
sudo journalctl -u mybuild-collect.service -f  # 采集日志
sudo systemctl start mybuild-collect.service   # 手动触发一次采集
sudo systemctl restart mybuild-server.service  # 改配置后重启
```

### 4.3 一键部署脚本

`deploy/install.sh` 整合上面所有步骤（创建用户 + Playwright + init-db + systemd + nginx），先看清注释再跑。

---

## 五、采集策略（重要）

当前 3 个可用 source：

| source_id | 用途 | 单次耗时 | 预期数据量 |
|-----------|------|---------|-----------|
| `jzsc_company_live` | 企业列表（按 31 省循环） | ~25 min | ~14,000 |
| `jzsc_staff_by_company_live` | 人员反查（按企业名循环） | ~3-6 h | ~130,000 |
| `jzsc_project_by_company_live` | 项目反查（按企业名循环） | ~3-6 h | ~2,800 |

**推荐上线轮换策略**（避免日常采集过长）：

**周一/四**：只启用 `jzsc_company_live`（25 min，更新企业数据）  
**周二/五**：只启用 `jzsc_staff_by_company_live`（~5 h，人员更新）  
**周三/六**：只启用 `jzsc_project_by_company_live`（~5 h，项目更新）

通过修改 `sources.json` 的 `enabled` 字段实现。或写个定时脚本自动切换。

---

## 六、监控与告警

### 6.1 采集成功度

运行后查看最新 run 的状态：

```bash
python3 -c "
import sqlite3
c = sqlite3.connect('/opt/mybuild/collector/data/collector.db')
r = c.execute('''SELECT run_id, started_at, ended_at, raw_count, normalized_count,
                        issue_count, failed_source_count
                 FROM ingestion_run ORDER BY rowid DESC LIMIT 1''').fetchone()
print(r)
"
```

正常结果：`raw_count` > 0、`failed_source_count=0`。

### 6.2 日志健康度

control_server + 采集走 systemd journald：

```bash
sudo journalctl -u mybuild-server.service -n 200 --no-pager
sudo journalctl -u mybuild-collect.service --since "1 hour ago"
sudo journalctl -u mybuild-health.service -n 50
```

收到告警邮件前先看 `mybuild-health.service` 的 journal 行。

### 6.3 告警脚本

`scripts/check-health.sh` 已实现，返回码 0/1/2；`scripts/alert-mail.sh` 通过 SMTP 或 mail(1) 发送。两者由 `deploy/mybuild-health.service` 串起来，每小时跑一次。

手动测试：

```bash
bash scripts/check-health.sh                              # 人读
bash scripts/check-health.sh --quiet; echo $?             # exit code 0/1/2
echo "test body" | ALERT_EMAIL=you@a.com bash scripts/alert-mail.sh "测试"
```

---

## 七、常见故障与处理

### 7.1 runner_lock 残留

现象：run-stream 报 `Pipeline already running: run lock not acquired`  
处理：`bash scripts/collect.sh` 会自动探测并 `--force-unlock`；手动可：

```bash
python3 -c "
import sqlite3
c = sqlite3.connect('collector/data/collector.db')
c.execute('DELETE FROM runner_lock')
c.commit()
"
```

### 7.2 Playwright 进程残留

```bash
pkill -9 -f "collector.cli"
pkill -9 -f "chrome-headless"
pkill -9 -f "playwright"
```

### 7.3 JZSC 反爬触发

现象：日志里连续 `rows=0 stopped@page=0`。session 轮换机制（`browser_refresh_every=8`）会自动换 cookie 继续。如果反复失败，延长批间等待：修改 `collector/connectors.py` 里 `page.wait_for_timeout(400)` → `800`。

### 7.4 live-data.json 太大

当 staff/tender 数据量破 5 万后 JSON 会 > 30 MB。解决方案：

**方案 A**：减少导出量（`collector/export_live_data.py` 里 `staff_limit=5000`）— 简单但损失数据  
**方案 B**：拆分多 JSON 文件（per-entity）— 中等改造  
**方案 C**：写 FastAPI 后端 API — 完全重构

当前 v0.3 用方案 A（staff/tender 各限 5000 条）。

---

## 八、备份

### 8.1 DB 备份（每日）

```bash
#!/bin/bash
# scripts/backup-db.sh
BACKUP_DIR=/var/backups/mybuild
mkdir -p $BACKUP_DIR
DATE=$(date +%Y%m%d)
sqlite3 /opt/mybuild/collector/data/collector.db ".backup $BACKUP_DIR/collector-$DATE.db"
gzip $BACKUP_DIR/collector-$DATE.db
# 保留 30 天
find $BACKUP_DIR -name "collector-*.db.gz" -mtime +30 -delete
```

放入 cron：
```
0 3 * * * /opt/mybuild/scripts/backup-db.sh
```

### 8.2 导出 JSON 同步（可选）

将最新 `live-data.json` 推到备用站点：

```bash
rsync -az scripts/*.json backup-server:/backup/mybuild/scripts/
```

---

## 九、后续优化路线

**短期（1-2 周）：**
- [ ] staff/project 导出改为分页 JSON（减小文件大小）
- [ ] 加企业详情 API（`/query/comp/compDetail`，当前 token失效问题待解）
- [ ] 加资质证书采集（`/query/comp/getQyAptCheckList`）

**中期（1-2 月）：**
- [ ] 省级平台接入（29 个可直通省份，见 PLATFORM_LIST.md）
- [ ] 增量采集（只采 event_date > cursor 的新记录）
- [ ] 企业详情页扩展：资质列表、在建项目列表、信用评分

**长期：**
- [ ] FastAPI 后端（支持全量查询、不再依赖 live-data.json）
- [ ] ElasticSearch/PostgreSQL（支持真正的全文检索和复杂查询）
- [ ] 用户体系 + 权限（登录、角色、企业认证申诉）

---

## 十、快速参考

```bash
# 0. 本机开发（最快）
bash scripts/start-server.sh                 # 前台跑 control_server + 静态
# 浏览器 → http://127.0.0.1:8787/pages/login.html  (默认 admin / build2026)

# 1. 首次初始化
python3 -m collector.cli init-db

# 2. 采集（命令行）
bash scripts/collect-bg.sh --only enterprise # 后台跑，只企业
bash scripts/collect-status.sh -f            # 实时跟随日志
bash scripts/collect-stop.sh                 # 安全停止
bash scripts/check-health.sh                 # 健康检查 exit 0/1/2

# 3. 采集（admin 后台一键）
# 登录 admin → 侧栏"采集控制台" → 选「启动·全部 / 仅企业 / 仅人员反查 / 仅项目反查」

# 4. 查看累计
python3 -c "import sqlite3;c=sqlite3.connect('collector/data/collector.db');print(list(c.execute('SELECT entity_type,COUNT(*) FROM normalized_entity GROUP BY entity_type ORDER BY 2 DESC')))"

# 5. 线上重启
sudo systemctl restart mybuild-server.service
sudo systemctl start mybuild-collect.service

# 6. 杀所有相关进程
pkill -9 -f "collector\|chrome-headless\|playwright"
```

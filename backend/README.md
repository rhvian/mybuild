# backend/ — L2 FastAPI 后端

L2 阶段的用户 / 角色 / 权限系统 + JWT 认证，与 L1 `control_server.py` 并行运行。
L1 继续管采集控制台 + 静态前端；L2 管真用户体系 + 业务数据 API。

## 架构

```
    浏览器 (前端)
      │
      ▼
    nginx (HTTPS)
      │
      ├──> control_server :8787     L1 采集控制 + 静态前端 + 公众业务查询 API
      │
      └──> backend :8000            L2 用户/角色/JWT + 业务流（本目录）
                                    - /auth/login, /auth/me, /auth/refresh
                                    - /users (CRUD + RBAC)
                                    - /roles
                                    - /system/health
```

两者共存的理由：L1 零依赖、稳定；L2 需要 FastAPI + bcrypt + JWT 等外部依赖。强行合并反而把 L1 的可部署性降到 L2。

## 默认凭据

- 邮箱：`admin@example.com`
- 口令：`build2026`
- 角色：`admin`（12 个权限全开）
- **上线前必改**：环境变量 `MYBUILD_BOOTSTRAP_ADMIN_EMAIL` / `MYBUILD_BOOTSTRAP_ADMIN_PASSWORD`

## 角色预设（bootstrap）

| Role | 权限数 | 典型权限 |
|------|-------|---------|
| admin | 12 | 全部 |
| auditor | 7 | user:read, alert:*, ticket:*, audit:read, collect:read |
| gov | 3 | alert:read, ticket:read, collect:read |
| business | 1 | user:read |
| guest | 0 | 无（登录后无操作权）|

## 本机启动

```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
# Swagger UI: http://127.0.0.1:8000/docs
```

## 生产部署

```bash
sudo cp deploy/mybuild-backend.service /etc/systemd/system/
sudo cp deploy/backend.env.sample /etc/mybuild/backend.env
sudo vim /etc/mybuild/backend.env  # 填真实 JWT_SECRET + 改 ADMIN 凭据
sudo systemctl daemon-reload
sudo systemctl enable --now mybuild-backend.service
```

nginx 反代片段（追加到 `deploy/nginx-mybuild.conf` 现有 server block 内）：

```nginx
location /auth/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
location /users/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
location /roles/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
location /system/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
```

## 数据库

- 默认：`backend/data/operation.db`（SQLite）
- 阶段 4：迁 PostgreSQL，用 alembic 做 DDL 管理
- `Base.metadata.create_all` 在启动时自动建表 + bootstrap 默认数据

## 测试

```bash
pytest -q        # 15 个测试，覆盖登录 / 刷新 / CRUD / RBAC / 健康
```

## 鉴权机制

- 登录成功返 `{access_token, refresh_token, expires_in}`
- 客户端把 `access_token` 放 `Authorization: Bearer <token>`
- 失效后用 `refresh_token` 调 `/auth/refresh` 换新
- 服务端无 session，JWT 无状态；登出只是客户端丢 token（审计会留痕）
- 登录失败同 IP 10min 内 5 次触发限流，锁 15min

## 下一步规划

- 阶段 3 剩余：[B5b] 预警处置业务流（alerts / tickets 表 + 派单 / 审批 / 关闭）
- 阶段 3 剩余：[B2] SQLite → PostgreSQL + alembic 初始 migration
- 阶段 3 剩余：[B4] 前端全面改调 `/auth` + `/users` 等

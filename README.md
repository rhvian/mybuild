# 全国诚信市场建筑管理平台

建筑市场公开数据采集 + 审查处置一体化平台。

```
采集中台（collector）   →   SQLite / REST API   →   公众前台 + 管理后台
 国家平台 + 省级平台         按实体归一化               检索 / 看板 / 预警 / 申诉
```

## 快速试用（本地 1 条命令）

```bash
bash scripts/start-server.sh
# 浏览器打开 http://127.0.0.1:8787
# 管理后台入口 http://127.0.0.1:8787/pages/login.html
# 默认凭据：admin@example.com / build2026
```

完整使用说明见 [USAGE.md](USAGE.md)。

## 能力全景

| 层 | 模块 | 状态 |
|----|------|------|
| 采集 | 国家平台 jzsc.mohurd（企业 / 人员 / 项目）| ✅ 14k + 38k + 500 条 |
| 采集 | 浙江省住建（企业 / 人员，免登明文）| ✅ connector 就绪 |
| 采集 | 省级平台批量接入 | ⏸ 按需（见 [HAR_CAPTURE.md](HAR_CAPTURE.md)，需抓 HAR）|
| 运行 | 流式落库 + 增量 cursor + 安全中断 | ✅ |
| 运行 | 采集控制台（启停 / 日志 / 健康）| ✅ |
| 后台 | FastAPI + JWT + RBAC（5 角色 / 12 权限）| ✅ |
| 业务 | 预警处置 / 申诉审核 / 项目监管 | ✅ 完整状态机 |
| 前台 | 公众检索 / 详情页 / 看板 | ✅ |
| 运维 | systemd timer + nginx + 告警邮件 + 备份 | ✅ 模板齐备 |

## 目录

```
├── index.html               前端入口
├── pages/                   HTML 页面（公众 + admin）
├── scripts/                 前端 JS + 运维 shell
├── styles/                  CSS
├── collector/               采集中台（Python stdlib + Playwright + httpx）
│   ├── cli.py                       CLI: init-db / run / run-stream / export-*
│   ├── connectors.py                国家平台 + 浙江 + 省级 lvl1/lvl2 连接器
│   ├── pipeline.py                  流式 per-batch 提交 + cursor
│   ├── control_server.py            L1 控制 HTTP 服务（:8787 stdlib）
│   └── config/sources.json          数据源注册表
├── backend/                 L2 后端（FastAPI + SQLAlchemy + JWT）
│   ├── main.py / config.py / database.py
│   └── routers/                     auth / users / roles / alerts / appeals / projects / system
├── deploy/                  systemd units + nginx + install.sh
├── tests/                   pytest（52 个测试，CI 绿）
└── docs                     USAGE.md / DEPLOYMENT.md / HAR_CAPTURE.md / PLATFORM_LIST.md
```

## 文档地图

| 场景 | 看哪份 |
|------|--------|
| 第一次用、想跑起来 | [USAGE.md](USAGE.md) |
| 上服务器生产部署 | [DEPLOYMENT.md](DEPLOYMENT.md) |
| 接入新省级平台 | [HAR_CAPTURE.md](HAR_CAPTURE.md) |
| 省级平台清单 | [PLATFORM_LIST.md](PLATFORM_LIST.md) |
| 当贡献者（代码规范 / 命令）| [AGENTS.md](AGENTS.md) |
| L1 采集模块内部 | [collector/README.md](collector/README.md) |
| L2 后端模块内部 | [backend/README.md](backend/README.md) |

## 技术栈

- 前端：原生 HTML / CSS / JS，零构建
- 采集：Python 3.11+、Playwright（国家平台 AES 解密）、httpx（浙江明文）
- 控制服务：Python stdlib HTTP Server（零依赖）+ stdlib HS256 JWT 验证
- 后端：FastAPI 0.136 + SQLAlchemy 2.0 + Pydantic v2 + JWT + bcrypt
- 存储：SQLite（WAL 模式）+ Alembic 迁移 scaffold（PG 按需切换）
- 部署：systemd + nginx + Let's Encrypt

## 默认配置

- 前端 + 控制服务：`127.0.0.1:8787`
- FastAPI 后端：`127.0.0.1:8000`
- 默认管理员：`admin@example.com / build2026`（生产环境必改）
- DB：`collector/data/collector.db`（采集） + `backend/data/operation.db`（用户 / 工单）

---

**版本 v0.5**（2026-04-21）：L2 完整可部署、52 测试绿、CI 严格 ruff、浙江 connector + 增量采集就绪。

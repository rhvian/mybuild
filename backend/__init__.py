"""backend — L2 用户体系 + 权限后端

职责：
  - 用户 / 角色 / 权限（RBAC）
  - bcrypt 密码 + JWT 登录
  - 与 L1 control_server 并行运行；control_server 做采集操作，backend 做用户与业务数据
  - 数据库：SQLite（backend/data/operation.db），阶段 4 后迁 PostgreSQL

启动：
  uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""

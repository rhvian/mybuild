#!/usr/bin/env bash
# mybuild — 一键部署手册（对齐 v0.3 架构）
#
# 前提假设：
#   - Ubuntu 22.04+ / Debian 12+ / RHEL 9+ 之一
#   - python3 >= 3.10 已装
#   - 已有域名 + 证书（certbot 或手动）
#   - 代码放在 /opt/mybuild/

set -e

PROJECT_DIR=/opt/mybuild

# 1. 系统用户
id mybuild >/dev/null 2>&1 || sudo useradd --system --home "$PROJECT_DIR" --shell /usr/sbin/nologin mybuild
sudo chown -R mybuild:mybuild "$PROJECT_DIR"

# 2. Python 依赖（Playwright + 浏览器 + FastAPI）
cd "$PROJECT_DIR"
pip3 install --user -r requirements.txt
python3 -m playwright install --with-deps chromium

# 3. 初始化 DB
sudo -u mybuild python3 -m collector.cli init-db
# backend SQLite 表由 FastAPI startup lifespan 自动建，无需手动 init

# 4. 安装 systemd units
sudo cp deploy/mybuild-collect.service  /etc/systemd/system/
sudo cp deploy/mybuild-collect.timer    /etc/systemd/system/
sudo cp deploy/mybuild-server.service   /etc/systemd/system/
sudo cp deploy/mybuild-backend.service  /etc/systemd/system/
sudo cp deploy/mybuild-health.service   /etc/systemd/system/
sudo cp deploy/mybuild-health.timer     /etc/systemd/system/

# 5. 告警 + backend 环境变量
sudo mkdir -p /etc/mybuild
sudo cp deploy/alert.env.sample /etc/mybuild/alert.env
sudo cp deploy/backend.env.sample /etc/mybuild/backend.env
sudo chmod 600 /etc/mybuild/*.env
sudo chown root:mybuild /etc/mybuild/*.env
# 编辑两个 env 文件：
#   /etc/mybuild/alert.env    —— 填 SMTP + ALERT_EMAIL
#   /etc/mybuild/backend.env  —— 必改 MYBUILD_JWT_SECRET (openssl rand -base64 48)
#                                必改 MYBUILD_BOOTSTRAP_ADMIN_PASSWORD

# 6. 启用
sudo systemctl daemon-reload
sudo systemctl enable --now mybuild-server.service    # 控制服务 + 静态前端 :8787
sudo systemctl enable --now mybuild-backend.service   # L2 用户/JWT API :8000
sudo systemctl enable --now mybuild-collect.timer     # 每日 02:00 采集
sudo systemctl enable --now mybuild-health.timer      # 每小时健康检查

# 7. nginx（反代 + HTTPS）
sudo cp deploy/nginx-mybuild.conf /etc/nginx/sites-available/mybuild
sudo sed -i 's/your-domain.com/实际域名/g' /etc/nginx/sites-available/mybuild
sudo ln -sf /etc/nginx/sites-available/mybuild /etc/nginx/sites-enabled/mybuild
sudo nginx -t && sudo systemctl reload nginx

# 8. 验证
systemctl list-timers | grep mybuild
sudo -u mybuild bash /opt/mybuild/scripts/check-health.sh
curl -I https://实际域名/pages/login.html
curl -I https://实际域名/system/health

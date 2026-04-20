#!/usr/bin/env bash
# 告警邮件：读 stdin 作为邮件正文，通过本机 mail(1) / sendmail / SMTP 发送
#
# 用法：
#   echo "xxx" | bash scripts/alert-mail.sh "采集异常"
#   bash scripts/check-health.sh --quiet || bash scripts/check-health.sh 2>&1 | bash scripts/alert-mail.sh "mybuild 健康异常"
#
# 环境变量（按优先级）：
#   ALERT_EMAIL      收件人（必填，多个用逗号分隔）
#   ALERT_FROM       发件人，默认 mybuild@<hostname>
#   SMTP_HOST        外部 SMTP 服务器（用 python stdlib smtplib 发送）
#   SMTP_PORT        默认 587（STARTTLS）或 465（SSL）
#   SMTP_USER        SMTP 登录账号
#   SMTP_PASS        SMTP 登录口令（若 SMTP_USER 非空则必填）
#   SMTP_SSL         =1 强制 SSL (默认 STARTTLS on 587 / SSL on 465)
#
# 若未设 SMTP_HOST，回退尝试 mail(1) / sendmail(8)。都没有则写 stderr + 退 2。
#
# 退出码：0 发送成功 / 2 配置缺失 / 3 发送失败

set -u

SUBJECT="${1:-mybuild alert}"
BODY="$(cat || true)"
if [ -z "$BODY" ]; then
  BODY="(no body)"
fi

if [ -z "${ALERT_EMAIL:-}" ]; then
  echo "[alert-mail] ALERT_EMAIL is not set — skipping mail send" >&2
  echo "[alert-mail] subject: $SUBJECT" >&2
  echo "[alert-mail] body:" >&2
  echo "$BODY" >&2
  exit 2
fi

ALERT_FROM="${ALERT_FROM:-mybuild@$(hostname)}"

send_via_smtp() {
  python3 - "$ALERT_FROM" "$ALERT_EMAIL" "$SUBJECT" <<'PY'
import os, smtplib, sys, ssl
from email.message import EmailMessage
sender, recipient, subject = sys.argv[1], sys.argv[2], sys.argv[3]
body = sys.stdin.read()
host = os.environ.get("SMTP_HOST", "")
port = int(os.environ.get("SMTP_PORT") or "587")
user = os.environ.get("SMTP_USER", "")
pwd  = os.environ.get("SMTP_PASS", "")
force_ssl = os.environ.get("SMTP_SSL") == "1" or port == 465

msg = EmailMessage()
msg["From"] = sender
msg["To"]   = recipient
msg["Subject"] = subject
msg.set_content(body)

try:
    if force_ssl:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
            if user:
                s.login(user, pwd)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.ehlo()
            try:
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
            except smtplib.SMTPNotSupportedError:
                pass
            if user:
                s.login(user, pwd)
            s.send_message(msg)
except Exception as e:
    print(f"[alert-mail] SMTP send failed: {e}", file=sys.stderr)
    sys.exit(3)
PY
}

# 1) SMTP
if [ -n "${SMTP_HOST:-}" ]; then
  echo "$BODY" | send_via_smtp
  rc=$?
  if [ $rc -eq 0 ]; then
    echo "[alert-mail] sent via SMTP to $ALERT_EMAIL" >&2
    exit 0
  fi
  exit $rc
fi

# 2) mail(1)
if command -v mail >/dev/null 2>&1; then
  if echo "$BODY" | mail -s "$SUBJECT" -r "$ALERT_FROM" "$ALERT_EMAIL" 2>/dev/null; then
    echo "[alert-mail] sent via mail(1) to $ALERT_EMAIL" >&2
    exit 0
  fi
fi

# 3) sendmail(8)
if command -v sendmail >/dev/null 2>&1; then
  {
    echo "From: $ALERT_FROM"
    echo "To: $ALERT_EMAIL"
    echo "Subject: $SUBJECT"
    echo "Content-Type: text/plain; charset=utf-8"
    echo
    echo "$BODY"
  } | sendmail -t && {
    echo "[alert-mail] sent via sendmail to $ALERT_EMAIL" >&2
    exit 0
  }
fi

echo "[alert-mail] no SMTP_HOST / mail / sendmail available — cannot send" >&2
exit 2

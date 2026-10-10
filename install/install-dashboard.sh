#!/usr/bin/env bash
# 3proxy Dashboard 一键安装（使用本包中的 app.py）
# 用法：在 portable 目录执行  sudo bash install/install-dashboard.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"
APP_DIR="/opt/3proxy-dashboard"
ENV_FILE="/etc/3proxy-dashboard.env"
SERVICE_SRC="$SCRIPT_DIR/3proxy-dashboard.service"
SERVICE_DST="/etc/systemd/system/3proxy-dashboard.service"

if [[ $EUID -ne 0 ]]; then
  echo "请用 root / sudo 运行： sudo bash install/install-dashboard.sh"
  exit 1
fi

if [[ ! -f "$PKG_DIR/app/app.py" ]]; then
  echo "找不到 $PKG_DIR/app/app.py"
  exit 1
fi

echo "===== 安装 3proxy Dashboard（可移植包） ====="

apt-get update -qq
apt-get install -y python3 python3-venv python3-pip openssl curl >/dev/null

mkdir -p "$APP_DIR"

systemctl stop 3proxy-dashboard 2>/dev/null || true
pkill -f "gunicorn.*app:app" 2>/dev/null || true

# 面板端口冲突自动让位（服务器上已有其他项目占用时顺延）
DASH_PORT="${DASH_PORT:-18080}"
while ss -tln 2>/dev/null | grep -q ":${DASH_PORT} "; do
  echo "端口 ${DASH_PORT} 已被占用，顺延..."
  DASH_PORT=$((DASH_PORT + 1))
done

if [[ -f "$APP_DIR/app.py" ]]; then
  cp "$APP_DIR/app.py" "$APP_DIR/app.py.bak.$(date +%s)"
fi

cp "$PKG_DIR/app/app.py" "$APP_DIR/app.py"

if [[ ! -f "$ENV_FILE" ]]; then
  ADMIN_PASS="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 18)"
  CSRF_TOKEN="$(openssl rand -hex 32)"
  cat >"$ENV_FILE" <<EOF
ADMIN_USER=admin
ADMIN_PASS=${ADMIN_PASS}
CSRF_TOKEN=${CSRF_TOKEN}
TZ_NAME=Asia/Shanghai
EOF
  chmod 600 "$ENV_FILE"
  echo "已生成管理密码，请记好："
  echo "  用户: admin"
  echo "  密码: ${ADMIN_PASS}"
else
  echo "保留已有 $ENV_FILE"
fi

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip >/dev/null
"$APP_DIR/venv/bin/pip" install flask gunicorn >/dev/null

cp "$SERVICE_SRC" "$SERVICE_DST"
sed -i "s/127\.0\.0\.1:[0-9]*/127.0.0.1:${DASH_PORT}/" "$SERVICE_DST"
systemctl daemon-reload
systemctl enable 3proxy-dashboard >/dev/null
systemctl restart 3proxy-dashboard

sleep 1
if systemctl is-active --quiet 3proxy-dashboard; then
  echo "===== 完成 ====="
  echo "本地访问: http://127.0.0.1:${DASH_PORT}/"
  echo "面板账号密码在 $ENV_FILE"
  echo "如需外网，请用 Caddy 反代 127.0.0.1:${DASH_PORT}（菜单选项 4 一键追加）"
else
  echo "启动失败，查看日志："
  journalctl -u 3proxy-dashboard -n 50 --no-pager
  exit 1
fi

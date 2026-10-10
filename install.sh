#!/usr/bin/env bash
# 3proxy + 管理面板 一键部署脚本（Debian/Ubuntu）
#
# 用法：
#   sudo bash install.sh              # 交互菜单
#   sudo bash install.sh install      # 一键安装 3proxy + 管理面板
#   sudo bash install.sh uninstall    # 卸载
#   sudo bash install.sh status       # 查看状态与账号
#
# 任意服务器单行拉起（推送 GitHub 后把 REPO_RAW 改成你的仓库地址）：
#   bash <(curl -fsSL https://raw.githubusercontent.com/你的用户名/3proxy-dashboard-portable/main/install.sh)
set -euo pipefail

# 推送到 GitHub 后改成你的仓库 raw 地址
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/你的用户名/3proxy-dashboard-portable/main}"
GH_MIRROR="${GH_MIRROR-https://gh-proxy.com/}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

SCRIPT_PATH="${BASH_SOURCE[0]}"
PKG_DIR="$(cd "$(dirname "$SCRIPT_PATH")" 2>/dev/null && pwd || echo "")"

ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*"; }

fetch() {
  curl -fsSL --connect-timeout 15 -o "$2" "$1" \
    || curl -fsSL --connect-timeout 15 -o "$2" "${GH_MIRROR}$1"
}

prepare_package() {
  if [[ -n "$PKG_DIR" && -f "$PKG_DIR/app/app.py" ]]; then
    return
  fi
  # curl|bash 单行拉起：无本地包时从仓库下载
  warn "未找到完整安装包，从仓库下载组件..."
  PKG_DIR="$(mktemp -d)/pkg"
  mkdir -p "$PKG_DIR/app" "$PKG_DIR/install"
  local f
  for f in \
    app/app.py \
    install/install-3proxy.sh \
    install/install-dashboard.sh \
    install/3proxy.service \
    install/3proxy-dashboard.service; do
    fetch "$REPO_RAW/$f" "$PKG_DIR/$f" || { err "下载 $f 失败，请检查 REPO_RAW"; exit 1; }
  done
  ok "组件下载完成"
}

do_install() {
  prepare_package
  echo -e "${CYAN}===== 一键安装 3proxy + 管理面板 =====${NC}"
  bash "$PKG_DIR/install/install-3proxy.sh"
  echo
  bash "$PKG_DIR/install/install-dashboard.sh"
  echo
  do_status
}

do_uninstall() {
  echo -e "${CYAN}===== 卸载 3proxy 与管理面板 =====${NC}"
  systemctl stop 3proxy 3proxy-dashboard 2>/dev/null || true
  systemctl disable 3proxy 3proxy-dashboard 2>/dev/null || true
  rm -f /etc/systemd/system/3proxy.service /etc/systemd/system/3proxy-dashboard.service
  systemctl daemon-reload
  rm -rf /opt/3proxy /opt/3proxy-dashboard /etc/3proxy-dashboard.env
  ok "已卸载（保留 /etc/3proxy 配置与 /var/log/3proxy 日志，如需删除请手动 rm）"
}

do_status() {
  echo -e "${CYAN}===== 状态 =====${NC}"
  for s in 3proxy 3proxy-dashboard; do
    if systemctl is-active --quiet "$s" 2>/dev/null; then
      ok "$s: 运行中"
    else
      err "$s: 未运行"
    fi
  done
  local socks_port
  socks_port="$(grep -oP 'socks\s+-p\K[0-9]+' /etc/3proxy/3proxy.cfg 2>/dev/null | head -n 1 || true)"
  echo "SOCKS5 端口: ${socks_port:-1234}  面板端口: 18080（仅本机，需反代）"
  if [[ -f /etc/3proxy-dashboard.env ]]; then
    echo "----- 面板账号（/etc/3proxy-dashboard.env） -----"
    grep -E '^ADMIN_(USER|PASS)=' /etc/3proxy-dashboard.env || true
  fi
  local public_ip
  public_ip="$(curl -fsSL --connect-timeout 5 ifconfig.me 2>/dev/null || echo "服务器IP")"
  echo "地址: ${public_ip}"
  echo "面板: http://${public_ip}:18080/ （若已配置反代则走 https）"
}

menu() {
  echo -e "${CYAN}"
  echo "========================================"
  echo "   3proxy Dashboard 一键部署脚本"
  echo "========================================"
  echo -e "${NC}"
  echo " 1. 一键安装（3proxy + 管理面板）"
  echo " 2. 仅安装 3proxy（SOCKS5）"
  echo " 3. 仅安装管理面板"
  echo " 4. 卸载全部"
  echo " 5. 查看状态与账号"
  echo " 0. 退出"
  echo
  read -r -p "请选择 [0-5]: " opt || opt=0
  case "$opt" in
    1) do_install ;;
    2) prepare_package; bash "$PKG_DIR/install/install-3proxy.sh" ;;
    3) prepare_package; bash "$PKG_DIR/install/install-dashboard.sh" ;;
    4) read -r -p "确认卸载? [y/N]: " c; [[ "$c" == "y" || "$c" == "Y" ]] && do_uninstall ;;
    5) do_status ;;
    0) exit 0 ;;
    *) err "无效选项"; exit 1 ;;
  esac
}

if [[ $EUID -ne 0 ]]; then
  err "请用 root / sudo 运行： sudo bash install.sh"
  exit 1
fi

case "${1:-menu}" in
  install|all)  do_install ;;
  uninstall)    do_uninstall ;;
  status)       do_status ;;
  menu|*)       menu ;;
esac

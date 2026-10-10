#!/usr/bin/env bash
# 3proxy + 管理面板 一键部署脚本（Debian/Ubuntu）
#
# 用法：
#   sudo bash install.sh              # 交互菜单
#   sudo bash install.sh install      # 一键安装 3proxy + 管理面板
#   sudo bash install.sh update       # 更新到最新版（main 分支，SHA256 哈希校验）
#   sudo bash install.sh caddy        # 追加 Caddy 反代（不动已有配置）并申请 HTTPS
#   sudo bash install.sh cert         # 重新申请 HTTPS 证书（首次失败后手动重试）
#   sudo bash install.sh status       # 查看状态与账号
#   sudo bash install.sh restart      # 重启服务
#   sudo bash install.sh uninstall    # 卸载
#
# 安装完成后终端输入 3p 即可随时打开管理菜单（等同 bash install.sh）
#
# 任意服务器单行拉起：
#   bash <(curl -fsSL https://raw.githubusercontent.com/keiraee/3proxy-dashboard-portable/main/install.sh)
set -euo pipefail

# 更新轨道：main 分支（Release 仅作稳定版本快照，见 README）
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/keiraee/3proxy-dashboard-portable/main}"
GH_MIRROR="${GH_MIRROR-https://gh-proxy.com/}"
CADDYFILE="/etc/caddy/Caddyfile"
CADDY_MARK="# --- 3proxy dashboard (由 3p 追加) ---"

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
    SHA256SUMS \
    install.sh \
    app/app.py \
    install/install-3proxy.sh \
    install/install-dashboard.sh \
    install/3proxy.service \
    install/3proxy-dashboard.service; do
    fetch "$REPO_RAW/$f" "$PKG_DIR/$f" || { err "下载 $f 失败，请检查 REPO_RAW"; exit 1; }
  done
  # 哈希校验：确保下载的每个文件与仓库发布一致（损坏/篡改直接拒绝）
  if ! (cd "$PKG_DIR" && sha256sum -c SHA256SUMS >/dev/null 2>&1); then
    err "SHA256 哈希校验失败，已中止（文件可能损坏或被篡改）："
    (cd "$PKG_DIR" && sha256sum -c SHA256SUMS 2>&1 | grep -v ': OK$' || true)
    exit 1
  fi
  ok "组件下载完成，SHA256 哈希校验通过"
}

install_cli() {
  # 装完注册 3p 管理命令：终端敲 3p 即可打开本菜单
  prepare_package
  install -m 755 "$PKG_DIR/install.sh" /usr/local/bin/3p
  ok "管理命令已安装：终端输入 3p 打开管理菜单"
}

panel_port() {
  # 面板实际端口（安装时若被占用会自动让位，以单元文件为准）
  grep -oP 'bind 127\.0\.0\.1:\K[0-9]+' /etc/systemd/system/3proxy-dashboard.service 2>/dev/null | head -n 1
}

do_restart() {
  systemctl restart 3proxy 3proxy-dashboard 2>/dev/null || true
  ok "已重启 3proxy 与管理面板"
}

do_install() {
  prepare_package
  echo -e "${CYAN}===== 一键安装 3proxy + 管理面板 =====${NC}"
  bash "$PKG_DIR/install/install-3proxy.sh"
  echo
  bash "$PKG_DIR/install/install-dashboard.sh"
  echo
  install_cli
  echo
  do_status
}

do_update() {
  echo -e "${CYAN}===== 更新到最新版（main 分支，SHA256 校验） =====${NC}"
  PKG_DIR="" # 强制从仓库重新拉取最新文件
  prepare_package
  bash "$PKG_DIR/install/install-dashboard.sh"
  if [[ ! -x /opt/3proxy/bin/3proxy ]]; then
    bash "$PKG_DIR/install/install-3proxy.sh"
  fi
  install_cli
  ok "更新完成（3proxy 本体未动，需升级本体请手动执行 install/install-3proxy.sh）"
  do_status
}

do_caddy() {
  # 只往 Caddyfile 末尾追加 3proxy. 子域站点，绝不改动已有项目配置
  echo -e "${CYAN}===== 配置 Caddy 反代（追加模式） =====${NC}"
  if ! command -v caddy >/dev/null 2>&1; then
    warn "未检测到 Caddy，正在安装..."
    apt-get update -qq
    apt-get install -y caddy >/dev/null
    ok "Caddy 已安装"
  fi

  local port
  port="$(panel_port)"
  port="${port:-18080}"
  if [[ ! -f /etc/systemd/system/3proxy-dashboard.service ]]; then
    err "面板尚未安装，请先执行安装（选项 1 或 3）"
    exit 1
  fi

  if grep -qF "$CADDY_MARK" "$CADDYFILE" 2>/dev/null; then
    warn "Caddyfile 已包含 3proxy 配置，跳过追加（重新配置请先执行选项 5 卸载或手动删除标记段）"
  else
    local public_ip default_domain domain
    public_ip="$(curl -fsSL --connect-timeout 5 ifconfig.me 2>/dev/null || echo "")"
    default_domain="3proxy.${public_ip//./-}.sslip.io"
    [[ -z "$public_ip" ]] && default_domain=""
    read -r -p "面板域名 [${default_domain}]: " domain
    domain="${domain:-$default_domain}"
    if [[ -z "$domain" ]]; then
      err "未输入域名"
      exit 1
    fi

    touch "$CADDYFILE"
    local before
    before="$(wc -l <"$CADDYFILE")"
    cat >>"$CADDYFILE" <<EOF

${CADDY_MARK}
${domain} {
	reverse_proxy 127.0.0.1:${port}
}
# --- end 3proxy dashboard ---
EOF
    if ! caddy validate --config "$CADDYFILE" >/dev/null 2>&1; then
      head -n "$before" "$CADDYFILE" >"$CADDYFILE.3p-tmp" && mv "$CADDYFILE.3p-tmp" "$CADDYFILE"
      err "Caddy 配置校验失败，已回滚本次追加（不影响已有配置）"
      caddy validate --config "$CADDYFILE" || true
      exit 1
    fi
    ok "已追加站点 ${domain} -> 127.0.0.1:${port}（只追加，未改动其他项目）"
  fi

  systemctl enable caddy >/dev/null 2>&1 || true
  do_cert
  echo "面板地址: https://${domain:-<你的域名>}/"
}

do_cert() {
  # 手动重新申请 HTTPS 证书：首次 ACME 失败（DNS 未生效等）后可多次重试
  echo -e "${CYAN}===== 申请/重签 HTTPS 证书 =====${NC}"
  if ! caddy validate --config "$CADDYFILE" >/dev/null 2>&1; then
    err "Caddyfile 校验失败，请先修复配置："
    caddy validate --config "$CADDYFILE" || true
    exit 1
  fi
  systemctl restart caddy
  sleep 2
  if systemctl is-active --quiet caddy; then
    ok "Caddy 已重启，证书申请通常 1 分钟内完成"
  else
    err "Caddy 启动失败，查看日志： journalctl -u caddy -n 30"
    exit 1
  fi
  echo "----- 最近的 Caddy 日志（证书申请情况） -----"
  journalctl -u caddy -n 15 --no-pager || true
  echo "持续观察: journalctl -u caddy -f"
}

do_uninstall() {
  echo -e "${CYAN}===== 卸载 3proxy 与管理面板 =====${NC}"
  systemctl stop 3proxy 3proxy-dashboard 2>/dev/null || true
  systemctl disable 3proxy 3proxy-dashboard 2>/dev/null || true
  rm -f /etc/systemd/system/3proxy.service /etc/systemd/system/3proxy-dashboard.service
  systemctl daemon-reload
  rm -rf /opt/3proxy /opt/3proxy-dashboard /etc/3proxy-dashboard.env
  rm -f /usr/local/bin/3p
  # 只清理 3p 标记段，Caddyfile 其他项目配置原样保留
  if grep -qF "$CADDY_MARK" "$CADDYFILE" 2>/dev/null; then
    sed -i "/^${CADDY_MARK}\$/,/^# --- end 3proxy dashboard ---\$/d" "$CADDYFILE"
    systemctl reload caddy 2>/dev/null || true
    ok "已从 Caddyfile 移除 3proxy 站点段（其他项目配置未动）"
  fi
  ok "已卸载（保留 /etc/3proxy 配置与 /var/log/3proxy 日志，如需删除请手动 rm）"
}

do_status() {
  echo -e "${CYAN}===== 状态 =====${NC}"
  for s in 3proxy 3proxy-dashboard caddy; do
    if systemctl is-active --quiet "$s" 2>/dev/null; then
      ok "$s: 运行中"
    else
      warn "$s: 未运行"
    fi
  done
  local socks_port port app_hash
  socks_port="$(grep -oP 'socks\s+-p\K[0-9]+' /etc/3proxy/3proxy.cfg 2>/dev/null | head -n 1 || true)"
  port="$(panel_port)"
  port="${port:-18080}"
  app_hash="$(sha256sum /opt/3proxy-dashboard/app.py 2>/dev/null | cut -c1-12 || true)"
  echo "SOCKS5 端口: ${socks_port:-1234}  面板端口: ${port}（仅本机，需反代）"
  echo "面板哈希: ${app_hash:-未安装}（对照仓库 SHA256SUMS 确认版本）"
  if [[ -f /etc/3proxy-dashboard.env ]]; then
    echo "----- 面板账号（/etc/3proxy-dashboard.env） -----"
    grep -E '^ADMIN_(USER|PASS)=' /etc/3proxy-dashboard.env || true
  fi
  local public_ip
  public_ip="$(curl -fsSL --connect-timeout 5 ifconfig.me 2>/dev/null || echo "服务器IP")"
  echo "地址: ${public_ip}"
  echo "面板: http://${public_ip}:${port}/ （若已配置反代则走 https 域名）"
}

menu() {
  echo -e "${CYAN}"
  echo "========================================"
  echo "   3proxy 管理菜单（命令：3p）"
  echo "========================================"
  echo -e "${NC}"
  echo " 1. 一键安装（3proxy + 管理面板）"
  echo " 2. 仅安装 3proxy（SOCKS5）"
  echo " 3. 仅安装管理面板"
  echo " 4. 更新到最新版（main 分支，SHA256 校验）"
  echo " 5. 配置 Caddy 反代（追加式，自动申请 HTTPS）"
  echo " 6. 重新申请 HTTPS 证书（首次失败后重试）"
  echo " 7. 重启服务"
  echo " 8. 卸载全部"
  echo " 9. 查看状态与账号"
  echo " 0. 退出"
  echo
  read -r -p "请选择 [0-9]: " opt || opt=0
  case "$opt" in
    1) do_install ;;
    2) prepare_package; bash "$PKG_DIR/install/install-3proxy.sh"; install_cli ;;
    3) prepare_package; bash "$PKG_DIR/install/install-dashboard.sh"; install_cli ;;
    4) do_update ;;
    5) do_caddy ;;
    6) do_cert ;;
    7) do_restart ;;
    8) read -r -p "确认卸载? [y/N]: " c; [[ "$c" == "y" || "$c" == "Y" ]] && do_uninstall ;;
    9) do_status ;;
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
  update)       do_update ;;
  caddy)        do_caddy ;;
  cert)         do_cert ;;
  uninstall)    do_uninstall ;;
  status)       do_status ;;
  restart)      do_restart ;;
  menu|*)       menu ;;
esac

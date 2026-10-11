#!/usr/bin/env bash
# 3proxy + 管理面板 一键部署脚本（Debian/Ubuntu）
#
# 用法：
#   sudo bash install.sh              # 交互菜单
#   sudo bash install.sh install      # 一键安装 3proxy + 管理面板
#   sudo bash install.sh update       # 更新到最新发布版（Release 轨道，SHA256 哈希校验）
#   sudo bash install.sh caddy        # 追加 Caddy 反代（不动已有配置）并申请 HTTPS
#   sudo bash install.sh cert         # 重新申请 HTTPS 证书（首次失败后手动重试）
#   sudo bash install.sh status       # 查看状态与账号
#   sudo bash install.sh start        # 启动服务
#   sudo bash install.sh stop         # 临时停止服务（3proxy + 面板）
#   sudo bash install.sh restart      # 重启服务
#   sudo bash install.sh uninstall    # 完全卸载
#
# 安装完成后终端输入 3p 即可随时打开管理菜单（等同 bash install.sh）
#
# 任意服务器单行拉起（以发版为准，跟随最新 Release）：
#   bash <(curl -fsSL https://github.com/keiraee/3proxy-dashboard-portable/releases/latest/download/install.sh)
set -euo pipefail

# 更新轨道：Release（以发版为准，跟随最新 Release）。开发调试可 REPO_REF=main，或写入 env 的 UPDATE_REF
ENV_FILE="/etc/3proxy-dashboard.env"
RELEASE_FALLBACK="v1.0.0" # GitHub API 不可用时的兜底版本（发新版时同步更新）
REF="${REPO_REF:-}"
if [[ -z "$REF" && -f "$ENV_FILE" ]]; then
  REF="$(grep -E '^UPDATE_REF=' "$ENV_FILE" | head -n 1 | cut -d= -f2- || true)"
fi
REF="${REF:-}" # 空 = 跟随最新 Release，pin_repo 时解析
REPO_BASE="${REPO_BASE:-https://raw.githubusercontent.com/keiraee/3proxy-dashboard-portable}"
REPO_RAW="${REPO_BASE}/${REF}"
GH_MIRROR="${GH_MIRROR-https://gh-proxy.com/}"
CADDYFILE="/etc/caddy/Caddyfile"
CADDY_MARK="# --- 3proxy dashboard (由 3p 追加) ---"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

SCRIPT_PATH="${BASH_SOURCE[0]}"
PKG_DIR="$(cd "$(dirname "$SCRIPT_PATH")" 2>/dev/null && pwd || echo "")"

ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*"; }

print_banner() {
  echo -e "${CYAN}"
  cat <<'EOF'
 _____ ____  ____   _____  ____   __
|___ /|  _ \|  _ \ / _ \ \/ /\ \ / /
  |_ \| |_) | |_) | | | \  /  \ V /
 ___) |  __/|  _ <| |_| /  \   | |
|____/|_|   |_| \_\\___/_/\_\  |_|

 ____    _    ____  _   _ ____   ___    _    ____  ____
|  _ \  / \  / ___|| | | | __ ) / _ \  / \  |  _ \|  _ \
| | | |/ _ \ \___ \| |_| |  _ \| | | |/ _ \ | |_) | | | |
| |_| / ___ \ ___) |  _  | |_) | |_| / ___ \|  _ <| |_| |
|____/_/   \_\____/|_| |_|____/ \___/_/   \_\_| \_\____/
EOF
  echo -e "${NC}"
  echo "Welcome 3proxy Dashboard"
  echo "作者 @keiraee"
  echo "开源地址：https://github.com/keiraee/3proxy-dashboard-portable.git"
  echo
}

fetch() {
  curl -fsSL --connect-timeout 15 -o "$2" "$1" \
    || curl -fsSL --connect-timeout 15 -o "$2" "${GH_MIRROR}$1"
}

prepare_package() {
  pin_repo
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
  # --ignore-missing：bin/ 预编译包只在装 3proxy 时按需下载，此处跳过缺失项
  if ! (cd "$PKG_DIR" && sha256sum -c --ignore-missing SHA256SUMS >/dev/null 2>&1); then
    err "SHA256 哈希校验失败，已中止（文件可能损坏或被篡改）："
    (cd "$PKG_DIR" && sha256sum -c --ignore-missing SHA256SUMS 2>&1 | grep -v ': OK$' || true)
    exit 1
  fi
  ok "组件下载完成，SHA256 哈希校验通过"
}

install_cli() {
  # 装完注册 3p 管理命令：终端敲 3p 即可打开本菜单
  prepare_package
  install -m 755 "$PKG_DIR/install.sh" /usr/local/bin/3p
  [[ "${UPDATE_MODE:-0}" == "1" ]] || ok "管理命令已安装：终端输入 3p 打开管理菜单"
}

update_hash_file="/opt/3proxy-dashboard/.update-hash"

pin_repo() {
  # 以发版为准：REF 为空时解析最新 Release 标签；API 不可用退回兜底版本
  if [[ -z "$REF" ]]; then
    REF="$(curl -fsSL --connect-timeout 5 \
      "https://api.github.com/repos/keiraee/3proxy-dashboard-portable/releases/latest" 2>/dev/null \
      | grep -o '"tag_name": *"[^"]*"' | head -n 1 | cut -d'"' -f4 || true)"
    REF="${REF:-$RELEASE_FALLBACK}"
  fi
  # 再经 GitHub API 解析当前提交 SHA，按 SHA 下载 —— 避开 raw 的
  # CDN 缓存（旧校验文件会让更新永远显示"已是最新"）。HY2 同款做法。
  [[ -n "${PIN:-}" ]] && return 0
  local sha=""
  sha="$(curl -fsSL --connect-timeout 5 \
    "https://api.github.com/repos/keiraee/3proxy-dashboard-portable/commits/${REF}" 2>/dev/null \
    | grep -o '"sha":\? *"[0-9a-f]\{40\}"' | head -n 1 | cut -d'"' -f4 || true)"
  if [[ -n "$sha" ]]; then
    PIN="$sha"
  else
    PIN="$REF" # API 不可用时退回按分支名/标签拉取
  fi
  REPO_RAW="${REPO_BASE}/${PIN}"
  export REPO_RAW
}

save_update_hash() {
  mkdir -p /opt/3proxy-dashboard
  sha256sum "$PKG_DIR/SHA256SUMS" | awk '{print $1}' >"$update_hash_file"
}

current_commit() {
  # 提交短号；API 失败时为空，不影响主流程
  [[ -n "${PIN:-}" && ${#PIN} -eq 40 ]] && echo "${PIN:0:7}" || true
}

panel_port() {
  # 面板实际端口（安装时若被占用会自动让位，以单元文件为准）
  grep -oP 'bind 127\.0\.0\.1:\K[0-9]+' /etc/systemd/system/3proxy-dashboard.service 2>/dev/null | head -n 1
}

panel_domain() {
  # 已配置的反代域名（Caddyfile 标记段首行）
  awk '/3proxy dashboard \(由 3p 追加\)/{getline; print $1; exit}' "$CADDYFILE" 2>/dev/null | tr -d '{} '
}

socks_port() {
  # 行首锚定跳过 # 注释行，否则注释掉的旧端口会被当成实际端口
  grep -oP '^\s*socks\s+-p\K[0-9]+' /etc/3proxy/3proxy.cfg 2>/dev/null | head -n 1
}

socks_creds() {
  # 从 3proxy 配置解析首个用户：user:CL:pass
  grep -oP '^users\s+\K\S+' /etc/3proxy/3proxy.cfg 2>/dev/null | head -n 1
}

env_get() {
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -n 1 | cut -d= -f2-
}

print_summary() {
  # 统一汇总：只给真正要用的信息（hy2 同款格式）
  local mode="${1:-all}"
  local public_ip domain s_port s_creds s_user s_pass a_user a_pass
  public_ip="$(curl -fsSL --connect-timeout 5 ifconfig.me 2>/dev/null || echo "服务器IP")"
  domain="$(panel_domain)"
  s_port="$(socks_port)"
  s_port="${s_port:-1234}"
  s_creds="$(socks_creds)"
  s_user="${s_creds%%:*}"
  s_pass="${s_creds#*CL:}"
  a_user="$(env_get ADMIN_USER)"
  a_pass="$(env_get ADMIN_PASS)"

  echo
  print_banner
  echo "============================================================"
  echo " 安装完成"
  echo "============================================================"
  if [[ "$mode" != "socks" && -n "$a_user" ]]; then
    if [[ -n "$domain" ]]; then
      echo "面板地址：https://${domain}/"
    else
      echo "面板地址：http://127.0.0.1:$(panel_port)/（仅本机，外网执行 3p caddy 开通）"
    fi
    echo "面板账号：${a_user}"
    echo "面板密码：${a_pass}"
  fi
  if [[ "$mode" != "panel" ]]; then
    echo
    if [[ -n "$s_user" && "$s_user" != "__no_active_users__" ]]; then
      echo "SOCKS5：${public_ip}:${s_port}"
      echo "用户名：${s_user}"
      echo "密码：  ${s_pass}"
    else
      echo "SOCKS5：未创建初始用户（在面板创建用户后即可使用）"
    fi
  fi
  echo
  echo "以后查看账号：3p status"
  echo "以后常用（需 root）："
  echo "  3p              # 菜单"
  echo "  3p update       # 更新到最新发布版（Release 轨道，SHA256 校验）"
  echo "  3p cert         # 证书没签下来时重新申请"
  echo
  echo "云控制台防火墙请放行：TCP 80、TCP 443、TCP ${s_port}"
  echo "============================================================"
}

test_https() {
  # 等 HTTPS 证书与面板就绪（hy2 同款实测）
  local domain="$1" a_user a_pass code=""
  [[ -z "$domain" ]] && return 0
  a_user="$(env_get ADMIN_USER)"
  a_pass="$(env_get ADMIN_PASS)"
  echo "等待 HTTPS 证书与面板可用..."
  for _ in $(seq 1 12); do
    code="$(curl -fsS -u "${a_user}:${a_pass}" -o /dev/null -w '%{http_code}' \
      --connect-timeout 5 --max-time 12 "https://${domain}/" 2>/dev/null || true)"
    [[ "$code" == "200" ]] && break
    sleep 5
  done
  if [[ "$code" == "200" ]]; then
    ok "HTTPS 面板测试成功：HTTP 200"
  else
    warn "面板 HTTPS 暂未成功（可能证书还在签发）。稍后重试：3p cert"
  fi
}

log_activity() {
  # 项目动态：系统事件与面板操作共用同一份记录（面板「项目动态」可见）
  mkdir -p /opt/3proxy-dashboard 2>/dev/null || true
  echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" >>/opt/3proxy-dashboard/activity.log 2>/dev/null || true
}

show_ports() {
  local s_port
  s_port="$(socks_port)"
  s_port="${s_port:-1234}"
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
    ufw allow 80/tcp >/dev/null 2>&1
    ufw allow 443/tcp >/dev/null 2>&1
    ufw allow "${s_port}/tcp" >/dev/null 2>&1
    ok "本机 ufw 已自动放行 80/443/${s_port}（云安全组仍需控制台操作）"
  elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-port=80/tcp >/dev/null 2>&1
    firewall-cmd --permanent --add-port=443/tcp >/dev/null 2>&1
    firewall-cmd --permanent --add-port="${s_port}/tcp" >/dev/null 2>&1
    firewall-cmd --reload >/dev/null 2>&1
    ok "本机 firewalld 已自动放行 80/443/${s_port}（云安全组仍需控制台操作）"
  fi
}

do_start() {
  systemctl start 3proxy 3proxy-dashboard 2>/dev/null || true
  log_activity "系统 启动服务"
  ok "已启动 3proxy 与管理面板"
}

do_stop() {
  systemctl stop 3proxy 3proxy-dashboard 2>/dev/null || true
  log_activity "系统 停止服务"
  ok "已临时停止 3proxy 与管理面板（配置与数据未动，3p start 恢复；Caddy 未停，其他项目不受影响）"
}

do_restart() {
  systemctl restart 3proxy 3proxy-dashboard 2>/dev/null || true
  log_activity "系统 重启服务"
  ok "已重启 3proxy 与管理面板"
}

do_install() {
  prepare_package
  echo "============================================================"
  echo " 一键安装 3proxy + 管理面板"
  echo "============================================================"
  echo "[1/4] 安装 3proxy 本体"
  bash "$PKG_DIR/install/install-3proxy.sh"
  echo "[2/4] 安装管理面板"
  bash "$PKG_DIR/install/install-dashboard.sh"
  echo "[3/4] 配置 HTTPS（自动申请证书）"
  install_cli
  save_update_hash
  # HTTPS 只是加分项：失败不能中断安装，否则下面的账号密码用户永远看不到
  do_caddy auto || warn "HTTPS 配置未完成（可稍后执行 3p caddy 重试），继续输出账号信息"
  show_ports
  echo "[4/4] 验证"
  domain="$(panel_domain)"
  test_https "$domain"
  log_activity "系统 安装完成（${REF}）"
  print_summary all
}

do_update() {
  local label sums_tmp sums_new sums_old commit s
  pin_repo
  if [[ "$REF" == "main" ]]; then
    label="轨道：main（开发版）"
  else
    label="版本：${REF}"
  fi
  echo -e "${CYAN}===== 更新（${label}） =====${NC}"

  # 先只拉 SHA256SUMS 比指纹：一致=没有更新，直接跳过
  sums_tmp="$(mktemp)"
  if ! fetch "$REPO_RAW/SHA256SUMS" "$sums_tmp"; then
    rm -f "$sums_tmp"
    err "拉取 SHA256SUMS 失败，请检查网络或 REPO_REF"
    exit 1
  fi
  sums_new="$(sha256sum "$sums_tmp" | awk '{print $1}')"
  rm -f "$sums_tmp"
  sums_old="$(cat "$update_hash_file" 2>/dev/null || echo "未记录")"
  commit=""
  [[ "$REF" == "main" ]] && commit="$(current_commit)"

  echo "上次哈希：${sums_old}"
  echo "本次哈希：${sums_new}${commit:+ （${REF}@${commit}）}"

  if [[ "$sums_old" == "$sums_new" ]]; then
    ok "哈希一致，已是最新，无需更新"
    return 0
  fi

  echo "哈希变化，开始更新..."
  PKG_DIR="" # 强制从仓库重新拉取最新文件
  prepare_package
  UPDATE_MODE=1 bash "$PKG_DIR/install/install-dashboard.sh"
  if [[ ! -x /opt/3proxy/bin/3proxy ]]; then
    UPDATE_MODE=1 bash "$PKG_DIR/install/install-3proxy.sh"
  fi
  install_cli
  save_update_hash
  log_activity "系统 更新 ${sums_old:0:8} → ${sums_new:0:8}${commit:+（${REF}@${commit}）}"
  ok "更新完成（${sums_new:0:12}）；3proxy 本体未动"
  for s in 3proxy 3proxy-dashboard; do
    if systemctl is-active --quiet "$s" 2>/dev/null; then
      ok "$s: 运行中"
    else
      err "$s: 未运行"
    fi
  done
}

do_caddy() {
  # 只往 Caddyfile 末尾追加 3proxy. 子域站点，绝不改动已有项目配置
  # $1=auto：无人值守模式，默认域名直接配置，不询问
  local mode="${1:-}"

  # 先确认面板已安装，否则不必白装一遍 Caddy
  if [[ ! -f /etc/systemd/system/3proxy-dashboard.service ]]; then
    err "面板尚未安装，请先执行安装（选项 1 或 3）"
    return 1
  fi

  if ! command -v caddy >/dev/null 2>&1; then
    warn "未检测到 Caddy，正在安装..."
    apt-get -o DPkg::Lock::Timeout=300 update -qq || true
    apt-get -o DPkg::Lock::Timeout=300 install -y caddy >/dev/null
    ok "Caddy 已安装"
  fi

  local port
  port="$(panel_port)"
  port="${port:-18080}"

  if grep -qF "$CADDY_MARK" "$CADDYFILE" 2>/dev/null; then
    warn "Caddyfile 已包含 3proxy 配置，跳过追加"
  else
    local public_ip default_domain domain
    public_ip="$(curl -fsSL --connect-timeout 5 ifconfig.me 2>/dev/null || echo "")"
    default_domain="3proxy.${public_ip//./-}.sslip.io"
    [[ -z "$public_ip" ]] && default_domain=""
    if [[ "$mode" != "auto" ]]; then
      read -r -p "面板域名 [${default_domain}]: " domain || true
    fi
    domain="${domain:-$default_domain}"
    if [[ -z "$domain" ]]; then
      err "未输入域名"
      return 1
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
      return 1
    fi
    ok "已追加站点 ${domain} -> 127.0.0.1:${port}（只追加，未改动其他项目）"
  fi

  systemctl enable caddy >/dev/null 2>&1 || true
  do_cert
}

do_cert() {
  # 手动重新申请 HTTPS 证书：首次 ACME 失败（DNS 未生效等）后可多次重试
  if ! caddy validate --config "$CADDYFILE" >/dev/null 2>&1; then
    err "Caddyfile 校验失败，请先修复配置："
    caddy validate --config "$CADDYFILE" || true
    return 1
  fi
  systemctl restart caddy
  sleep 2
  if systemctl is-active --quiet caddy; then
    log_activity "系统 重新申请 HTTPS 证书"
    ok "Caddy 已重启，证书申请通常 1 分钟内完成"
  else
    err "Caddy 启动失败，查看日志： journalctl -u caddy -n 30"
    return 1
  fi
  echo "持续观察: journalctl -u caddy -f"
}

do_uninstall() {
  echo -e "${CYAN}===== 完全卸载 3proxy 与管理面板 =====${NC}"
  echo "探测已安装组件..."
  local items=()
  [[ -f /etc/systemd/system/3proxy.service ]] && items+=("3proxy 服务")
  [[ -f /etc/systemd/system/3proxy-dashboard.service ]] && items+=("管理面板服务")
  [[ -d /opt/3proxy ]] && items+=("/opt/3proxy（程序）")
  [[ -d /opt/3proxy-dashboard ]] && items+=("/opt/3proxy-dashboard（面板与数据库）")
  [[ -d /etc/3proxy ]] && items+=("/etc/3proxy（配置与用户数据）")
  [[ -d /var/log/3proxy ]] && items+=("/var/log/3proxy（流量日志）")
  [[ -f "$ENV_FILE" ]] && items+=("/etc/3proxy-dashboard.env（面板账号）")
  [[ -f /usr/local/bin/3p ]] && items+=("3p 管理命令")
  grep -qF "$CADDY_MARK" "$CADDYFILE" 2>/dev/null && items+=("Caddy 站点段（其他项目配置不动）")

  if [[ ${#items[@]} -eq 0 ]]; then
    ok "未检测到已安装组件，无需卸载"
    return 0
  fi

  echo "检测到以下组件，确认后全部彻底删除："
  local it
  for it in "${items[@]}"; do echo "  - $it"; done
  echo
  read -r -p "确认完全卸载? [y/N]: " c || c=""
  if [[ "$c" != [Yy] ]]; then
    warn "已取消卸载"
    return 0
  fi

  systemctl stop 3proxy 3proxy-dashboard 2>/dev/null || true
  systemctl disable 3proxy 3proxy-dashboard 2>/dev/null || true
  rm -f /etc/systemd/system/3proxy.service /etc/systemd/system/3proxy-dashboard.service
  systemctl daemon-reload
  rm -rf /opt/3proxy /opt/3proxy-dashboard /etc/3proxy /var/log/3proxy
  rm -f "$ENV_FILE" /usr/local/bin/3p
  # 只清理 3p 标记段，Caddyfile 其他项目配置原样保留
  if grep -qF "$CADDY_MARK" "$CADDYFILE" 2>/dev/null; then
    sed -i "/^${CADDY_MARK}\$/,/^# --- end 3proxy dashboard ---\$/d" "$CADDYFILE"
    systemctl reload caddy 2>/dev/null || true
    ok "Caddy 站点段已移除（其他项目配置未动，Caddy 本身保留）"
  fi
  ok "已完全卸载，可直接重装（系统依赖包如 curl/python3 保留，其他项目可能在用）"
}

do_status() {
  local domain s_port port a_user a_pass s_creds s_user s_pass
  domain="$(panel_domain)"
  s_port="$(socks_port)"
  s_port="${s_port:-1234}"
  port="$(panel_port)"
  port="${port:-18080}"
  a_user="$(env_get ADMIN_USER)"
  a_pass="$(env_get ADMIN_PASS)"
  s_creds="$(socks_creds)"
  s_user="${s_creds%%:*}"
  s_pass="${s_creds#*CL:}"

  echo "============================================================"
  echo " 状态"
  echo "============================================================"
  for s in 3proxy 3proxy-dashboard; do
    if systemctl is-active --quiet "$s" 2>/dev/null; then
      ok "$s: 运行中"
    else
      err "$s: 未运行"
    fi
  done
  echo
  if [[ -n "$domain" ]]; then
    echo "面板地址：https://${domain}/"
  else
    echo "面板地址：http://127.0.0.1:${port}/（仅本机，外网执行 3p caddy 开通）"
  fi
  if [[ -n "$a_user" ]]; then
    echo "面板账号：${a_user}"
    echo "面板密码：${a_pass}"
  fi
  if [[ -n "$s_user" && "$s_user" != "__no_active_users__" ]]; then
    echo
    echo "SOCKS5：$(curl -fsSL --connect-timeout 5 ifconfig.me 2>/dev/null || echo 服务器IP):${s_port}"
    echo "用户名：${s_user}"
    echo "密码：  ${s_pass}"
  else
    echo
    echo "SOCKS5：未创建初始用户（在面板创建用户后即可使用）"
  fi
  echo
  echo "云控制台防火墙请放行：TCP 80、TCP 443、TCP ${s_port}"
  echo "============================================================"
}

menu() {
  print_banner
  echo " 1. 一键安装（3proxy + 管理面板）"
  echo " 2. 仅安装 3proxy（SOCKS5）"
  echo " 3. 仅安装管理面板"
  echo " 4. 更新（哈希对比，一致自动跳过）"
  echo " 5. 配置 Caddy 反代（追加式，自动申请 HTTPS）"
  echo " 6. 重新申请 HTTPS 证书（首次失败后重试）"
  echo " 7. 启动服务"
  echo " 8. 停止服务（临时停止 3proxy + 面板，配置数据不动）"
  echo " 9. 重启服务"
  echo "10. 完全卸载（服务、配置、数据全清，可直接重装）"
  echo "11. 查看状态与账号"
  echo " 0. 退出"
  echo
  read -r -p "请选择 [0-11]: " opt || opt=0
  case "$opt" in
    1) do_install ;;
    2) prepare_package; bash "$PKG_DIR/install/install-3proxy.sh"; install_cli; print_summary socks ;;
    3) prepare_package; bash "$PKG_DIR/install/install-dashboard.sh"; install_cli; print_summary panel ;;
    4) do_update ;;
    5) do_caddy ;;
    6) do_cert ;;
    7) do_start ;;
    8) do_stop ;;
    9) do_restart ;;
    10) do_uninstall ;;
    11) do_status ;;
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
  start)        do_start ;;
  stop)         do_stop ;;
  restart)      do_restart ;;
  menu|*)       menu ;;
esac

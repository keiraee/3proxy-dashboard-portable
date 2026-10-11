#!/usr/bin/env bash
# 安装 3proxy 本体：优先下载预编译静态二进制（免编译，适合 512M 小机器）
# 下载失败或非 amd64/arm64 架构时自动回退源码编译
# 用法： sudo bash install/install-3proxy.sh
# 环境变量： SOCKS_PORT=1234 可覆盖默认端口
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPT_DIR="/opt/3proxy"
SRC_DIR="$OPT_DIR/source"
BIN_DIR="$OPT_DIR/bin"
CFG_DIR="/etc/3proxy"
CFG_FILE="$CFG_DIR/3proxy.cfg"
LOG_DIR="/var/log/3proxy"
SERVICE_SRC="$SCRIPT_DIR/3proxy.service"
SERVICE_DST="/etc/systemd/system/3proxy.service"
SOCKS_PORT="${SOCKS_PORT:-1234}"
# 3proxy 官方 releases 只发源码；预编译二进制由本仓库 bin/ 提供
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/keiraee/3proxy-dashboard-portable/main}"
VER3PROXY="0.9.4"
# 国内服务器直连 GitHub 失败时走镜像（GH_MIRROR= 可禁用）
GH_MIRROR="${GH_MIRROR-https://gh-proxy.com/}"

if [[ $EUID -ne 0 ]]; then
  echo "请用 root / sudo 运行"
  exit 1
fi

echo "===== 安装 3proxy ====="

# -o DPkg::Lock::Timeout：等 unattended-upgrades 等进程放锁，避免安装被系统自动更新打断
apt-get -o DPkg::Lock::Timeout=300 update -qq || true
apt-get -o DPkg::Lock::Timeout=300 install -y curl ca-certificates openssl >/dev/null

fetch() { # fetch <url> <输出文件>：直连失败走镜像
  curl -fsSL --connect-timeout 15 -o "$2" "$1" \
    || curl -fsSL --connect-timeout 15 -o "$2" "${GH_MIRROR}$1"
}

mkdir -p "$BIN_DIR" "$CFG_DIR" "$LOG_DIR"

if [[ ! -x "$BIN_DIR/3proxy" ]]; then
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64|amd64)  ARCH=amd64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    *)             ARCH="" ;;
  esac

  GOT=0
  if [[ -n "$ARCH" ]]; then
    echo "下载预编译 3proxy（linux-${ARCH} 静态二进制，免编译）..."
    TMP_TAR="$(mktemp -d)"
    if fetch "$REPO_RAW/bin/3proxy-linux-${ARCH}.gz" "$TMP_TAR/3proxy.gz" \
      && fetch "$REPO_RAW/SHA256SUMS" "$TMP_TAR/SHA256SUMS"; then
      WANT="$(grep "bin/3proxy-linux-${ARCH}.gz" "$TMP_TAR/SHA256SUMS" | awk '{print $1}')"
      GOT_HASH="$(sha256sum "$TMP_TAR/3proxy.gz" | awk '{print $1}')"
      if [[ -n "$WANT" && "$WANT" == "$GOT_HASH" ]]; then
        gunzip -c "$TMP_TAR/3proxy.gz" >"$BIN_DIR/3proxy"
        chmod 755 "$BIN_DIR/3proxy"
        GOT=1
        echo "预编译二进制安装完成（SHA256 校验通过）"
      else
        echo "SHA256 校验失败，弃用预编译包"
      fi
    fi
    rm -rf "$TMP_TAR"
  fi

  if [[ "$GOT" -eq 0 ]]; then
    echo "预编译不可用（架构不支持或下载失败），改用源码编译..."
    apt-get -o DPkg::Lock::Timeout=300 install -y build-essential tar >/dev/null
    if [[ ! -f "$SRC_DIR/Makefile.Linux" ]]; then
      echo "下载 3proxy ${VER3PROXY} 源码..."
      TMP_TAR="$(mktemp -d)"
      if ! fetch "https://github.com/3proxy/3proxy/archive/refs/tags/${VER3PROXY}.tar.gz" "$TMP_TAR/3proxy.tar.gz"; then
        echo "tag ${VER3PROXY} 下载失败，改用 master 分支"
        fetch "https://github.com/3proxy/3proxy/archive/refs/heads/master.tar.gz" "$TMP_TAR/3proxy.tar.gz"
      fi
      mkdir -p "$SRC_DIR"
      tar -xzf "$TMP_TAR/3proxy.tar.gz" -C "$TMP_TAR"
      SRC_FOUND="$(find "$TMP_TAR" -maxdepth 1 -mindepth 1 -type d | head -n 1)"
      cp -a "$SRC_FOUND"/. "$SRC_DIR/"
      rm -rf "$TMP_TAR"
    fi
    echo "编译 3proxy..."
    make -C "$SRC_DIR" -f Makefile.Linux >/dev/null
    install -m 755 "$SRC_DIR/bin/3proxy" "$BIN_DIR/3proxy"
  fi
fi

if [[ ! -x "$BIN_DIR/3proxy" ]]; then
  echo "3proxy 安装失败：$BIN_DIR/3proxy 不存在"
  exit 1
fi

if [[ ! -f "$CFG_FILE" ]]; then
  systemctl stop 3proxy 2>/dev/null || true
  # SOCKS 端口冲突自动让位（服务器上已有其他项目占用时顺延）
  while ss -tln 2>/dev/null | grep -q ":${SOCKS_PORT} "; do
    echo "端口 ${SOCKS_PORT} 已被占用，顺延..."
    SOCKS_PORT=$((SOCKS_PORT + 1))
  done
  SOCKS_USER="u$(openssl rand -hex 4)"
  SOCKS_PASS="$(openssl rand -base64 16 | tr -dc 'A-Za-z0-9' | head -c 16)"
  cat >"$CFG_FILE" <<EOF
# 由 install-3proxy.sh 生成
# 用户行 users <用户名>:CL:<密码> 通过管理面板维护
maxconn 100

nserver 1.1.1.1
nserver 8.8.8.8

timeouts 1 5 30 60 180 1800 15 60

log /var/log/3proxy/access.log
logformat "-L%t %U %C:%c %R:%r IN:%I OUT:%O"

auth strong

users ${SOCKS_USER}:CL:${SOCKS_PASS}

socks -p${SOCKS_PORT}

flush
EOF
  chmod 600 "$CFG_FILE"
  NEW_USER=1
  echo "已生成配置 $CFG_FILE"
else
  NEW_USER=0
  echo "保留已有 $CFG_FILE"
fi

cp "$SERVICE_SRC" "$SERVICE_DST"
systemctl daemon-reload
systemctl enable 3proxy >/dev/null
systemctl restart 3proxy

sleep 1
if ! systemctl is-active --quiet 3proxy; then
  echo "3proxy 启动失败，查看日志："
  journalctl -u 3proxy -n 30 --no-pager
  exit 1
fi

echo "3proxy 运行正常（账号汇总见安装结束输出，或 3p status）"

#!/usr/bin/env bash
# 重新生成 SHA256SUMS（每次改动后、提交前必跑）
# 文本文件按 LF 归一化后计算 —— 与 git 仓库 / GitHub raw 内容一致，
# Windows 上误写出 CRLF 也不会导致哈希漂移。
set -euo pipefail
cd "$(dirname "$0")"

out=SHA256SUMS
: >"$out"

for f in \
  app/app.py \
  install/install-3proxy.sh \
  install/install-dashboard.sh \
  install/3proxy.service \
  install/3proxy-dashboard.service \
  install.sh; do
  sum="$(tr -d '\r' <"$f" | sha256sum | awk '{print $1}')"
  echo "$sum *$f" >>"$out"
done

# 二进制按原样计算，不做归一化
sum="$(sha256sum bin/3proxy-linux-amd64.gz | awk '{print $1}')"
echo "$sum *bin/3proxy-linux-amd64.gz" >>"$out"

cat "$out"

# 3proxy-dashboard-portable

SOCKS5 代理（3proxy）+ 流量管理面板 的**一键部署包**。任意 Debian/Ubuntu 服务器一条命令装完，带 `3p` 管理命令、Caddy HTTPS 追加式接入、SHA256 哈希校验更新。

提取自 AWS Lightsail 新加坡服务器 `13.228.203.217` 的生产环境，已重构为可移植一键部署。

## 功能

- **一键安装**：预编译 3proxy + Flask 管理面板一步装完，随机生成 SOCKS 账号密码
- **管理面板**：Basic Auth 登录，管理 SOCKS 用户（增删/启停/改密），按日/月统计流量、在线状态、最近 IP；深/浅色主题，小机器友好
- **`3p` 管理命令**：装完即可用，菜单式管理（安装/更新/HTTPS/证书/卸载/状态）
- **与已有项目共存**：端口冲突自动让位；Caddy 只追加不覆盖；`3proxy.` 子域前缀不撞其他站点
- **哈希校验更新**：`3p update` 逐文件 SHA256 校验后才落地，损坏/篡改直接拒绝

## 系统要求

- Debian / Ubuntu（apt 系）
- root 权限（`sudo`）
- 可访问 GitHub（国内自动走 gh-proxy 镜像）

## 一键安装

### 方式一：单行拉起（推荐，服务器上直接执行）

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/keiraee/3proxy-dashboard-portable/main/install.sh)
```

> 国内服务器 GitHub 不通时：
> ```bash
> bash <(curl -fsSL https://gh-proxy.com/https://raw.githubusercontent.com/keiraee/3proxy-dashboard-portable/main/install.sh)
> ```

回车后出现菜单，选 `1` 一键安装（3proxy + 管理面板）。也可以非交互直接装：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/keiraee/3proxy-dashboard-portable/main/install.sh) install
```

### 方式二：克隆后安装

```bash
git clone https://github.com/keiraee/3proxy-dashboard-portable
cd 3proxy-dashboard-portable
sudo bash install.sh
```

### 方式三：离线拷贝

把整个目录 `scp`/`rsync` 到服务器后执行：

```bash
cd 3proxy-dashboard-portable
sudo bash install.sh
```

### 安装时会发生什么

1. 下载**预编译 3proxy 静态二进制**（amd64/arm64，约 150KB，SHA256 校验），**不装编译器、不占内存**——512M 小机器无压力；下载失败或特殊架构才回退源码编译（此时才装编译工具）
2. 检测 SOCKS5（默认 1234）与面板（默认 18080）端口，**被占用自动顺延**
3. 生成 `/etc/3proxy/3proxy.cfg` 与 systemd 服务；**自动生成随机初始 SOCKS 账号**（3proxy 配置必须含用户行才能认证，装前会说明原因；账号可随时在面板删除/更换）
4. 面板建 venv 装 flask+gunicorn，生成 `/etc/3proxy-dashboard.env`（随机 admin 密码）
5. 注册 `3p` 管理命令，打印连接信息（地址/端口/账号/密码）
6. **自动配置 Caddy 反代并申请 HTTPS 证书**（零确认直接申请，默认 `3proxy.<IP>.sslip.io` 免 DNS；想用自己域名装完执行 `3p caddy`）
7. 打印**需放行端口清单**（本机防火墙 ufw/firewalld 自动放行；云服务商安全组/防火墙请到控制台放行）

### 安装后验证

```bash
3p status                                   # 服务状态、端口、面板哈希、账号
curl -I http://127.0.0.1:18080/             # 面板 HTTP 200
systemctl status 3proxy 3proxy-dashboard    # 两个服务 running
```

浏览器打开 `http://服务器IP:端口/`，账号密码见 `3p status` 或 `/etc/3proxy-dashboard.env`。

SOCKS5 连通测试：

```bash
curl --socks5 用户名:密码@服务器IP:端口 https://ifconfig.me
```

## 3p 管理命令

安装后任意目录敲 `3p` 打开菜单，或带参数直接执行：

| 命令 | 作用 |
|------|------|
| `3p` | 打开管理菜单 |
| `3p install` | 一键安装（3proxy + 面板） |
| `3p update` | 更新到最新版（main 分支，SHA256 校验） |
| `3p caddy` | 追加 Caddy 反代（不动已有配置）并申请 HTTPS |
| `3p cert` | 重新申请 HTTPS 证书（首次失败后重试） |
| `3p status` | 查看状态、端口、面板哈希与账号 |
| `3p start` | 启动服务 |
| `3p stop` | 临时停止 3proxy + 面板（配置数据不动，Caddy 不停） |
| `3p restart` | 重启服务 |
| `3p uninstall` | 完全卸载（先探测列出组件清单 → 确认 → 服务/配置/数据全清，可直接重装） |

## 外网 HTTPS（Caddy）

### 已有 Caddy 且跑着其他项目？放心用

`3p caddy` **只往 `/etc/caddy/Caddyfile` 末尾追加**一段带标记的 `3proxy.` 子域站点，绝不动已有配置：

```caddy
# --- 3proxy dashboard (由 3p 追加) ---
3proxy.你的域名 {
	reverse_proxy 127.0.0.1:18080
}
# --- end 3proxy dashboard ---
```

- 追加后自动 `caddy validate`，**校验失败立即回滚**，其他项目零影响
- 默认域名 `3proxy.<服务器IP>.sslip.io`（免 DNS 配置，自动签发真证书），也可输入自己的域名
- `3proxy.` 子域前缀与已有站点天然不冲突
- 卸载时只删这个标记段，Caddyfile 其他内容原样保留

### 证书申请失败怎么办

首次 ACME 申请可能失败（常见原因：DNS 还没解析生效），此时 HTTPS 打不开是正常的：

```bash
3p cert        # 随时手动重新申请：校验配置 → 重启 Caddy 触发重签 → 显示申请日志
```

可反复重试。日志持续观察：`journalctl -u caddy -f`。

## 更新机制

### 怎么更新

```bash
3p update
```

流程（与 HY2 AIO 同款）：先拉 `SHA256SUMS` 与上次记录**比指纹**——

- **哈希一致**：日志打印「上次哈希 / 本次哈希」后直接跳过，不重装不重启
- **哈希变化**：下载组件 → 逐文件 SHA256 校验 → 落地重启，日志标明变化前后的哈希

main 轨道的哈希行会附带**提交短号**（`main@abc1234`），一眼看出更新到了哪个提交。首次安装即记录基准哈希。

### 更新轨道定位（重要）

| 轨道 | 定位 |
|------|------|
| **main（当前，未发版）** | **更新轨道**。`3p update` 跟 main，凭哈希变化判断有无更新 |
| **Release/tag（发版后）** | 稳定版本。`3p update` 显示**版本号**，变更见 GitHub Release 说明；锁定版本：`UPDATE_REF=v1.0.0` 写入 `/etc/3proxy-dashboard.env`（或临时 `REPO_REF=v1.0.0 3p update`） |

发版后想切回开发版：把 `UPDATE_REF=main`（或删掉该行）。

### 哈希机制（每次更新必须带）

仓库根目录的 `SHA256SUMS` 是发布完整性凭据，覆盖所有落地文件：

```
app/app.py
install/install-3proxy.sh
install/install-dashboard.sh
install/3proxy.service
install/3proxy-dashboard.service
install.sh
bin/3proxy-linux-amd64.gz
```

**每次改动后、提交前必须重新生成**（否则 `3p update` 会校验失败拒绝更新）：

```bash
bash gen-sums.sh
```

（脚本会按 LF 归一化文本后计算，Windows 上误写出 CRLF 也不会导致哈希与仓库内容漂移；二进制按原样计算。）

手动核对（可选）：

```bash
sha256sum -c SHA256SUMS        # 在仓库根目录执行，全部 OK 即一致
3p status                      # 面板哈希（app.py 前 12 位）与 SHA256SUMS 里对照
```

发版时：Release 说明里附上 `SHA256SUMS` 内容，方便锁版本用户核对。

## 目录与端口

| 组件 | 路径 | 端口 |
|------|------|------|
| 3proxy SOCKS5 | `/opt/3proxy/bin/3proxy` | `1234`（占用自动顺延） |
| 管理面板 (Flask+gunicorn) | `/opt/3proxy-dashboard/app.py` | `127.0.0.1:18080`（占用自动顺延） |
| 3proxy 配置 | `/etc/3proxy/3proxy.cfg` | — |
| 面板环境变量（含账号） | `/etc/3proxy-dashboard.env` | — |
| 反代（可选） | Caddy | `80/443` |

面板默认只绑 `127.0.0.1`，外网访问必须走反代，不要直接暴露端口。

## 常见问题

**改 admin 密码**：编辑 `/etc/3proxy-dashboard.env` 的 `ADMIN_PASS=`，然后 `3p restart`。

**改 SOCKS 端口**：编辑 `/etc/3proxy/3proxy.cfg` 的 `socks -p端口`，然后 `3p restart`。安装时也支持 `SOCKS_PORT=1080` 预指定。

**面板密码忘了**：`cat /etc/3proxy-dashboard.env`。

**换面板端口**：`DASH_PORT=18090` 预指定，或改 `/etc/systemd/system/3proxy-dashboard.service` 里的 `--bind` 后 `systemctl daemon-reload && 3p restart`。

**日志在哪**：3proxy 流量日志 `/var/log/3proxy/access.log`；面板日志 `journalctl -u 3proxy-dashboard`；面板流量统计由日志增量解析而来。

**3proxy 本体要不要跟着更新**：`3p update` 只更新面板与脚本，不动 3proxy 二进制（生产稳定优先）。要升本体：删掉 `/opt/3proxy/bin/3proxy` 后 `sudo bash install/install-3proxy.sh`（配置与账号保留）。

**为什么不用编译安装？** 3proxy 官方 releases 只发源码、没有预编译包（不像 hysteria2）。本仓库 `bin/` 直接提供 **musl 静态编译**的二进制（任何 Linux 发行版通用、与 glibc 版本无关），安装时直接下载并 SHA256 校验——512M 内存小机器全程不装编译器。编译只是兜底路径。

**旧服务器数据**：无需拷贝 `dashboard_v3.db`，首次启动自动建表并从 `3proxy.cfg` 导入用户名。

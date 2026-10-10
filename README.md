# 3proxy Dashboard 一键部署包

从服务器 `13.228.203.217`（AWS Lightsail 新加坡）提取的完整源码与配置，重构为**任意 Debian/Ubuntu 服务器一键部署**。

## 一键安装

```bash
# 方式一：克隆后安装
git clone https://github.com/你的用户名/3proxy-dashboard-portable
cd 3proxy-dashboard-portable
sudo bash install.sh

# 方式二：任意服务器单行拉起（推送 GitHub 后把 install.sh 里的 REPO_RAW 改成你的仓库地址）
bash <(curl -fsSL https://raw.githubusercontent.com/你的用户名/3proxy-dashboard-portable/main/install.sh)
```

`install.sh` 是交互菜单（也支持 `install` / `uninstall` / `status` 参数）：

```
1. 一键安装（3proxy + 管理面板）
2. 仅安装 3proxy（SOCKS5）
3. 仅安装管理面板
4. 卸载全部
5. 查看状态与账号
```

安装脚本会**真实安装 3proxy**：自动装编译工具 → 拉取官方源码（GitHub，失败自动走 gh-proxy 镜像）→ 本地编译 → 注册 systemd 服务，并生成随机 SOCKS 账号密码，装完直接打印连接信息。

## 包内容

```
├── install.sh                        # 一键部署入口（菜单/单行拉起/卸载/状态）
├── app/
│   └── app.py                        # 面板主程序（Flask，当前生产版）
├── install/
│   ├── install-3proxy.sh             # 3proxy 本体安装（源码编译）
│   ├── install-dashboard.sh          # 面板安装
│   ├── 3proxy.service                # systemd 单元
│   └── 3proxy-dashboard.service
├── config/                           # 配置示例（安装时自动生成，无需手改）
└── server-original/                  # 原服务器完整安装脚本与历史备份
```

## 架构说明

| 组件 | 路径 | 端口 |
|------|------|------|
| 3proxy SOCKS5 | `/opt/3proxy/bin/3proxy` | `1234` |
| Dashboard (Flask+gunicorn) | `/opt/3proxy-dashboard/app.py` | `127.0.0.1:18080` |
| 反向代理（可选） | Caddy/Nginx | `80/443` |

面板不是纯静态 HTML：是一个带 Basic Auth 的 Flask 应用，可管理 3proxy 用户、改密、看流量。

依赖：`flask` + `gunicorn`（安装脚本会自动建 venv 并安装）。

## 外网 HTTPS（推荐 Caddy）

`/etc/caddy/Caddyfile` 末尾追加（示例见 `config/Caddyfile.example`）：

```caddy
3proxy.你的域名 {
    reverse_proxy 127.0.0.1:18080
}
```

```bash
caddy validate --config /etc/caddy/Caddyfile
caddy reload --config /etc/caddy/Caddyfile
```

## 修改管理员密码

编辑 `/etc/3proxy-dashboard.env`：

```bash
ADMIN_USER=admin
ADMIN_PASS=你的新密码
CSRF_TOKEN=$(openssl rand -hex 32)
TZ_NAME=Asia/Shanghai
```

然后：

```bash
sudo systemctl restart 3proxy-dashboard
```

## 注意事项

1. **不需要拷贝 `dashboard_v3.db`**：首次启动自动建表；若 `/etc/3proxy/3proxy.cfg` 里已有 users，会自动导入用户名。
2. 面板默认只绑 `127.0.0.1:18080`，外网必须反代（不建议直接 0.0.0.0 暴露）。
3. SOCKS 账号密码在 `/etc/3proxy/3proxy.cfg` 的 `users` 行，安装时随机生成，日常在面板里管理。
4. `SOCKS_PORT=1080 bash install/install-3proxy.sh` 可指定端口。
5. 原服务器自包含安装脚本在 `server-original/`，日常部署用根目录 `install.sh` 即可。

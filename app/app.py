import hmac
import os
import re
import shlex
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template_string,
    request,
    url_for,
)

APP_DIR = Path("/opt/3proxy-dashboard")
DB_PATH = APP_DIR / "dashboard_v3.db"
LOG_PATH = Path("/var/log/3proxy/access.log")
PROXY_CONFIG = Path("/etc/3proxy/3proxy.cfg")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "")
CSRF_TOKEN = os.environ.get("CSRF_TOKEN", "")
TZ_NAME = os.environ.get("TZ_NAME", "Asia/Singapore")
TZ = ZoneInfo(TZ_NAME)

app = Flask(__name__)
app.secret_key = CSRF_TOKEN or os.urandom(32)
parse_lock = threading.Lock()

BASE_STYLE = """
<style>
:root{
  --bg:#ffffff;--surface:#ffffff;--surface-2:#f5f5f4;--surface-3:#e9e9e7;
  --line:#e4e4e1;--text:#111111;--muted:#5c5c59;--faint:#8c8c88;
  --accent:#2a78d6;--bad:#d9463f;
  --radius:6px;
  --font:Inter,-apple-system,"Segoe UI",system-ui,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --shadow:0 8px 24px rgba(17,17,17,.08);
  color-scheme:light;
  font-family:var(--font);font-size:13.5px;line-height:1.45;
  color:var(--text);background:var(--bg);
}
html[data-theme="dark"]{
  --bg:#111111;--surface:#161616;--surface-2:#1e1e1e;--surface-3:#2a2a2a;
  --line:#2a2a29;--text:#ececea;--muted:#a3a3a0;--faint:#6f6f6c;
  --accent:#3987e5;--bad:#d9463f;
  --shadow:0 12px 32px rgba(0,0,0,.45);
  color-scheme:dark;
}
*{box-sizing:border-box}html,body{margin:0;min-height:100vh;background:var(--bg);color:var(--text)}
a{color:inherit}button,input{font:inherit;color:inherit}
.mono,.metric .value,th,td.num,.user-name,.daily-row .amt{font-family:var(--mono);font-variant-numeric:tabular-nums}
.shell{min-height:100vh;display:flex;flex-direction:column}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;height:48px;
  padding:0 20px;background:var(--bg);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:30}
.nav-left,.nav-right{display:flex;align-items:center;gap:14px;min-width:0}
.nav-right{flex-shrink:0}
.brand{font-size:13px;font-weight:700;letter-spacing:.02em;white-space:nowrap}
.nav-status{font-size:12px;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  max-width:min(42vw,520px);font-family:var(--mono)}
.icon-btn{width:28px;height:28px;border:1px solid var(--line);border-radius:4px;background:var(--surface);
  color:var(--muted);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;padding:0}
.icon-btn:hover{background:var(--surface-2);color:var(--text)}
.ico{width:16px;height:16px;display:block;flex-shrink:0}
.btn{border:1px solid var(--line);border-radius:4px;background:var(--surface);color:inherit;
  padding:5px 10px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:6px;line-height:1.3}
.btn:hover{background:var(--surface-2)}
.btn.primary{background:var(--text);color:var(--bg);border-color:var(--text)}
.btn.primary:hover{filter:brightness(1.08)}
.btn.bad{color:var(--bad)}
.btn.ghost{border-color:transparent;background:transparent}
.btn.ghost:hover{background:var(--surface-2)}
.main{flex:1;padding:20px;max-width:1440px;width:100%;margin:0 auto}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}
.metric{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:12px 14px}
.metric .label{font-size:13px;font-weight:700;display:flex;align-items:center;gap:6px}
.metric .value{font-size:20px;font-weight:700;margin-top:6px}
.metric .extra{font-size:12px;color:var(--faint);margin-top:4px}
.section{margin-top:18px}
.section-h{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 10px}
.section-h h2{margin:0;font-size:13px;font-weight:700;display:flex;align-items:center;gap:6px}
.hint{font-size:12px;color:var(--muted);margin:2px 0 0}
.table-wrap{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);overflow:auto}
table{width:100%;border-collapse:collapse}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:13px;vertical-align:middle}
th{font-size:11.5px;color:var(--faint);font-weight:600;background:var(--surface)}
td.num{text-align:right}
tr:last-child td{border-bottom:0}
tr:hover td{background:var(--surface-2)}
tr.disabled td{opacity:.55}
.user-name{font-weight:650;text-decoration:none}
.user-name:hover{text-decoration:underline}
.user-note{color:var(--muted);font-size:12px;margin-top:2px}
.status-dot{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.status-dot::before{content:"";width:7px;height:7px;border-radius:99px;background:currentColor;display:block}
.status-dot.on{color:var(--accent)}.status-dot.off{color:var(--faint)}.status-dot.ban{color:var(--bad)}
.ops{display:flex;gap:6px;justify-content:flex-end;flex-wrap:wrap}
.ops .btn{padding:4px 9px;font-size:12px}
.empty{padding:22px 12px;text-align:center;color:var(--faint);background:var(--surface);border:1px solid var(--line);border-radius:var(--radius)}
.flash{margin:0 0 14px;padding:10px 12px;border-radius:var(--radius);font-size:13px;border:1px solid var(--line)}
.flash.success{background:var(--surface-2);color:var(--muted)}
.flash.error{background:var(--surface);color:var(--bad);border-color:var(--bad)}
.form-body{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px}
.form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:end}
.field{display:flex;flex-direction:column;gap:6px;min-width:0}
.field label{font-size:12px;color:var(--faint);font-weight:650}
.input{border:1px solid var(--line);border-radius:4px;padding:8px 10px;width:100%;background:var(--surface);font-family:var(--mono);font-size:13px}
.input:focus{outline:none;border-color:var(--text)}
.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.daily-row{display:grid;grid-template-columns:96px minmax(0,1fr) 92px;gap:10px;align-items:center;font-size:12px;padding:4px 0}
.daily-row .amt{text-align:right}
.bar-track{height:4px;background:var(--surface-3);border-radius:2px;overflow:hidden}
.bar-track i{display:block;height:100%;background:var(--accent);border-radius:2px}
.footer{margin-top:18px;font-size:12px;color:var(--faint)}
svg.sprite{position:absolute;overflow:hidden;width:0;height:0}
@media(max-width:1100px){.metrics{grid-template-columns:repeat(2,1fr)}}
@media(max-width:900px){.nav-status{display:none}.detail-grid{grid-template-columns:1fr}}
@media(max-width:720px){.form-grid{grid-template-columns:1fr}}
@media(max-width:560px){.metrics{grid-template-columns:1fr}.main{padding:14px}.topbar{padding:0 12px}}
</style>
<script>
try{var t=localStorage.getItem("3p-panel-theme");
if(t==="dark"||t==="light"){document.documentElement.setAttribute("data-theme",t);}
else if(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches){document.documentElement.setAttribute("data-theme","dark");}}catch(e){}
function toggleTheme(){
  var next=document.documentElement.getAttribute("data-theme")==="dark"?"light":"dark";
  document.documentElement.setAttribute("data-theme",next);
  try{localStorage.setItem("3p-panel-theme",next)}catch(e){}
  var u=document.querySelector("#themeBtn use");
  if(u){u.setAttribute("href",next==="dark"?"#i-sun":"#i-moon");}
}
</script>
"""

HEADER = """
<svg class="sprite" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <symbol id="i-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></symbol>
  <symbol id="i-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/></symbol>
  <symbol id="i-users" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="3"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></symbol>
  <symbol id="i-activity" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M22 12h-4l-3 7L9 5l-3 7H2"/></symbol>
  <symbol id="i-chart" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M18 20V10M12 20V4M6 20v-6"/></symbol>
  <symbol id="i-server" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01"/></symbol>
</svg>
<header class="topbar">
  <div class="nav-left">
    <div class="brand">3proxy Panel</div>
  </div>
  <div class="nav-right">
    <div class="nav-status">SOCKS5 代理 · 时区 {{ timezone }}</div>
    <button id="themeBtn" class="icon-btn" type="button" aria-label="切换主题" title="主题" onclick="toggleTheme()">
      <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-moon"/></svg>
    </button>
    <a class="btn primary" href="{{ url_for('index') }}">总览</a>
  </div>
</header>
"""


def db_connection():
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    APP_DIR.mkdir(parents=True, exist_ok=True)

    with db_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS traffic (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                ts INTEGER NOT NULL,
                username TEXT NOT NULL,
                client_ip TEXT NOT NULL,
                target TEXT NOT NULL,
                download INTEGER NOT NULL DEFAULT 0,
                upload INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_traffic_user_ts "
            "ON traffic(username, ts)"
        )


def get_state(conn, key, default=""):
    row = conn.execute(
        "SELECT value FROM state WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_state(conn, key, value):
    conn.execute(
        """
        INSERT INTO state(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )


def import_users_from_config():
    if not PROXY_CONFIG.exists():
        return

    try:
        lines = PROXY_CONFIG.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return

    imported = []

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        try:
            parts = shlex.split(stripped)
        except ValueError:
            continue

        if not parts or parts[0] != "users":
            continue

        for token in parts[1:]:
            segments = token.split(":", 2)

            if len(segments) != 3 or segments[1].upper() != "CL":
                continue

            username, _, password = segments

            if username.startswith("__"):
                continue

            imported.append((username, password))

    now = int(datetime.now(TZ).timestamp())

    with db_connection() as conn:
        for username, password in imported:
            conn.execute(
                """
                INSERT OR IGNORE INTO users(username, password, enabled, created_at)
                VALUES(?, ?, 1, ?)
                """,
                (username, password, now),
            )


def split_endpoint(endpoint):
    if ":" not in endpoint:
        return endpoint

    host, port = endpoint.rsplit(":", 1)

    if port.isdigit():
        return host

    return endpoint


def parse_log_incrementally():
    if not LOG_PATH.exists():
        return

    with parse_lock:
        try:
            stat = LOG_PATH.stat()
        except OSError:
            return

        inode = f"{stat.st_dev}:{stat.st_ino}"

        with db_connection() as conn:
            old_inode = get_state(conn, "log_inode")
            old_offset = int(get_state(conn, "log_offset", "0") or 0)

            if old_inode != inode or stat.st_size < old_offset:
                old_offset = 0

            with LOG_PATH.open("rb") as log_file:
                log_file.seek(old_offset)

                while True:
                    line_offset = log_file.tell()
                    raw_line = log_file.readline()

                    if not raw_line:
                        break

                    line = raw_line.decode("utf-8", errors="ignore").strip()

                    match = re.search(
                        r"^L(\d+)\s+(\S+)\s+(\S+)\s+(\S+).*?"
                        r"IN:(\d+)\s+OUT:(\d+)",
                        line,
                    )

                    if not match:
                        continue

                    ts = int(match.group(1))
                    username = match.group(2)

                    if username == "-":
                        continue

                    client_ip = split_endpoint(match.group(3))
                    target = match.group(4)
                    download = int(match.group(5))
                    upload = int(match.group(6))
                    event_key = f"{inode}:{line_offset}"

                    conn.execute(
                        """
                        INSERT OR IGNORE INTO traffic(
                            event_key, ts, username, client_ip,
                            target, download, upload
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_key,
                            ts,
                            username,
                            client_ip,
                            target,
                            download,
                            upload,
                        ),
                    )

                set_state(conn, "log_inode", inode)
                set_state(conn, "log_offset", log_file.tell())


def authorized():
    auth = request.authorization

    if not auth:
        return False

    return (
        hmac.compare_digest(auth.username or "", ADMIN_USER)
        and hmac.compare_digest(auth.password or "", ADMIN_PASS)
    )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not authorized():
            return Response(
                "需要管理员身份验证",
                401,
                {"WWW-Authenticate": 'Basic realm="3proxy Dashboard"'},
            )

        return view(*args, **kwargs)

    return wrapped


def validate_csrf():
    token = request.form.get("csrf_token", "")

    if not hmac.compare_digest(token, CSRF_TOKEN):
        abort(403)


def format_bytes(value):
    value = int(value or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)

    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"

            return f"{amount:.2f} {unit}"

        amount /= 1024

    return f"{value} B"


app.jinja_env.filters["bytes"] = format_bytes


def time_boundaries():
    now = datetime.now(TZ)
    day_start = int(
        now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    )
    month_start = int(
        now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
    )

    return now, day_start, month_start


def restart_3proxy():
    result = subprocess.run(
        ["systemctl", "restart", "3proxy"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(message or "无法重启 3proxy")


def rebuild_users_config():
    if not PROXY_CONFIG.exists():
        raise RuntimeError("未找到 3proxy 配置文件")

    with db_connection() as conn:
        active_users = conn.execute(
            """
            SELECT username, password
            FROM users
            WHERE enabled = 1
            ORDER BY username
            """
        ).fetchall()

    original = PROXY_CONFIG.read_text(
        encoding="utf-8", errors="ignore"
    ).splitlines()

    backup = PROXY_CONFIG.with_suffix(".cfg.dashboard.bak")
    backup.write_text("\n".join(original) + "\n", encoding="utf-8")

    filtered = []
    inserted = False

    if active_users:
        credentials = " ".join(
            f"{row['username']}:CL:{row['password']}"
            for row in active_users
        )
    else:
        placeholder = os.urandom(24).hex()
        credentials = f"__no_active_users__:CL:{placeholder}"

    users_line = f"users {credentials}"

    for line in original:
        stripped = line.strip()

        if stripped.startswith("users "):
            continue

        if not inserted and stripped.startswith("socks "):
            filtered.append(users_line)
            filtered.append("")
            inserted = True

        filtered.append(line)

    if not inserted:
        filtered.append("")
        filtered.append(users_line)

    PROXY_CONFIG.write_text(
        "\n".join(filtered).rstrip() + "\n",
        encoding="utf-8",
    )

    try:
        restart_3proxy()
    except Exception:
        PROXY_CONFIG.write_text(
            backup.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        restart_3proxy()
        raise


def dashboard_rows():
    now, day_start, month_start = time_boundaries()
    now_ts = int(now.timestamp())
    online_cutoff = now_ts - 180
    recent_ip_cutoff = now_ts - 86400

    with db_connection() as conn:
        users = conn.execute(
            "SELECT * FROM users ORDER BY username"
        ).fetchall()

        output = []

        for user in users:
            totals = conn.execute(
                """
                SELECT
                    COALESCE(SUM(
                        CASE WHEN ts >= ? THEN download + upload ELSE 0 END
                    ), 0) AS today_total,
                    COALESCE(SUM(
                        CASE WHEN ts >= ? THEN download + upload ELSE 0 END
                    ), 0) AS month_total,
                    COALESCE(SUM(download), 0) AS total_download,
                    COALESCE(SUM(upload), 0) AS total_upload,
                    COALESCE(MAX(ts), 0) AS last_seen
                FROM traffic
                WHERE username = ?
                """,
                (day_start, month_start, user["username"]),
            ).fetchone()

            last = conn.execute(
                """
                SELECT client_ip, target
                FROM traffic
                WHERE username = ?
                ORDER BY ts DESC
                LIMIT 1
                """,
                (user["username"],),
            ).fetchone()

            ip_count = conn.execute(
                """
                SELECT COUNT(DISTINCT client_ip) AS count
                FROM traffic
                WHERE username = ? AND ts >= ?
                """,
                (user["username"], recent_ip_cutoff),
            ).fetchone()["count"]

            output.append(
                {
                    "username": user["username"],
                    "enabled": bool(user["enabled"]),
                    "today_total": totals["today_total"],
                    "month_total": totals["month_total"],
                    "total_download": totals["total_download"],
                    "total_upload": totals["total_upload"],
                    "last_seen": totals["last_seen"],
                    "last_ip": last["client_ip"] if last else "—",
                    "last_target": last["target"] if last else "—",
                    "ip_count": ip_count,
                    "online": (
                        bool(user["enabled"])
                        and totals["last_seen"] >= online_cutoff
                    ),
                }
            )

    return output


@app.route("/")
@login_required
def index():
    parse_log_incrementally()
    rows = dashboard_rows()

    total_today = sum(row["today_total"] for row in rows)
    total_month = sum(row["month_total"] for row in rows)
    online_count = sum(1 for row in rows if row["online"])

    template = """
<!doctype html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>3proxy 管理面板</title>
""" + BASE_STYLE + """
</head>
<body>
<div class="shell">
""" + HEADER + """
<main class="main">
{% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, message in messages %}
        <div class="flash {{ category }}">{{ message }}</div>
    {% endfor %}
{% endwith %}

<div class="metrics">
    <div class="metric">
        <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-users"/></svg>用户总数</div>
        <div class="value">{{ rows|length }}</div>
        <div class="extra">已启用 {{ enabled_count }}</div>
    </div>
    <div class="metric">
        <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-activity"/></svg>当前在线</div>
        <div class="value">{{ online_count }}</div>
        <div class="extra">最近 3 分钟有活动</div>
    </div>
    <div class="metric">
        <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-chart"/></svg>今日流量</div>
        <div class="value">{{ total_today|bytes }}</div>
        <div class="extra">下载 + 上传合计</div>
    </div>
    <div class="metric">
        <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-server"/></svg>本月流量</div>
        <div class="value">{{ total_month|bytes }}</div>
        <div class="extra">时区 {{ timezone }}</div>
    </div>
</div>

<section class="section">
    <div class="section-h">
        <div>
            <h2><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-users"/></svg>用户列表</h2>
            <p class="hint">在线状态根据最近 3 分钟内的连接活动判断；点击用户名查看明细。</p>
        </div>
    </div>
    {% if rows %}
    <div class="table-wrap">
        <table>
            <thead>
            <tr>
                <th>用户</th>
                <th>状态</th>
                <th>今日</th>
                <th>本月</th>
                <th>累计下载 / 上传</th>
                <th>最近 IP</th>
                <th>24h IP</th>
                <th style="text-align:right">操作</th>
            </tr>
            </thead>
            <tbody>
            {% for row in rows %}
            <tr class="{{ 'disabled' if not row.enabled else '' }}">
                <td>
                    <a class="user-name" href="{{ url_for('user_detail', username=row.username) }}">{{ row.username }}</a>
                    <div class="user-note">最近目标 · {{ row.last_target }}</div>
                </td>
                <td>
                    {% if not row.enabled %}
                        <span class="status-dot ban">已禁用</span>
                    {% elif row.online %}
                        <span class="status-dot on">在线</span>
                    {% else %}
                        <span class="status-dot off">离线</span>
                    {% endif %}
                </td>
                <td class="num">{{ row.today_total|bytes }}</td>
                <td class="num">{{ row.month_total|bytes }}</td>
                <td class="num">
                    ↓ {{ row.total_download|bytes }}
                    <div class="user-note">↑ {{ row.total_upload|bytes }}</div>
                </td>
                <td class="mono">{{ row.last_ip }}</td>
                <td class="num">{{ row.ip_count }}</td>
                <td>
                    <div class="ops">
                        <form method="post" action="{{ url_for('toggle_user', username=row.username) }}" style="display:inline">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                            <button class="btn" type="submit">{{ "启用" if not row.enabled else "禁用" }}</button>
                        </form>
                        <a class="btn ghost" href="{{ url_for('user_detail', username=row.username) }}">详情</a>
                        <form method="post" action="{{ url_for('delete_user', username=row.username) }}" style="display:inline"
                              onsubmit="return confirm('确定永久删除该用户吗？')">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                            <button class="btn bad" type="submit">删除</button>
                        </form>
                    </div>
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
    {% else %}
        <div class="empty">暂未配置任何用户。</div>
    {% endif %}
</section>

<section class="section" id="add-user">
    <div class="section-h">
        <div>
            <h2>新增用户</h2>
            <p class="hint">创建后将立即写入 3proxy 配置并生效。</p>
        </div>
    </div>
    <div class="form-body">
        <form class="form-grid" method="post" action="{{ url_for('add_user') }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <div class="field">
                <label>用户名</label>
                <input class="input" name="username" maxlength="32" pattern="[A-Za-z0-9_.-]+"
                       placeholder="字母/数字/._-" required>
            </div>
            <div class="field">
                <label>密码</label>
                <input class="input" name="password" type="password" minlength="4" maxlength="64"
                       autocomplete="new-password" placeholder="至少 4 位" required>
            </div>
            <button class="btn primary" type="submit">创建用户</button>
        </form>
    </div>
</section>

<footer class="footer">3proxy Panel · 私人管理</footer>
</main>
</div>
</body>
</html>
"""

    return render_template_string(
        template,
        rows=rows,
        online_count=online_count,
        enabled_count=sum(1 for row in rows if row["enabled"]),
        total_today=total_today,
        total_month=total_month,
        csrf_token=CSRF_TOKEN,
        timezone=TZ_NAME,
    )


@app.route("/users/add", methods=["POST"])
@login_required
def add_user():
    validate_csrf()

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", username):
        flash("用户名格式不正确。", "error")
        return redirect(url_for("index"))

    if (
        len(password) < 4
        or len(password) > 64
        or ":" in password
        or any(char.isspace() for char in password)
    ):
        flash(
            "密码必须为 4—64 个字符，且不能包含空格或冒号。",
            "error",
        )
        return redirect(url_for("index"))

    with db_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if exists:
            flash("该用户名已存在。", "error")
            return redirect(url_for("index"))

        conn.execute(
            """
            INSERT INTO users(username, password, enabled, created_at)
            VALUES(?, ?, 1, ?)
            """,
            (username, password, int(datetime.now(TZ).timestamp())),
        )

    try:
        rebuild_users_config()
        flash(f"用户 {username} 创建成功。", "success")
    except Exception as exc:
        with db_connection() as conn:
            conn.execute(
                "DELETE FROM users WHERE username = ?",
                (username,),
            )

        flash(f"更新 3proxy 失败：{exc}", "error")

    return redirect(url_for("index"))


@app.route("/users/<username>/toggle", methods=["POST"])
@login_required
def toggle_user(username):
    validate_csrf()

    with db_connection() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if not user:
            abort(404)

        new_state = 0 if user["enabled"] else 1

        conn.execute(
            "UPDATE users SET enabled = ? WHERE username = ?",
            (new_state, username),
        )

    try:
        rebuild_users_config()
        action = "启用" if new_state else "禁用"
        flash(f"用户 {username} 已{action}。", "success")
    except Exception as exc:
        with db_connection() as conn:
            conn.execute(
                "UPDATE users SET enabled = ? WHERE username = ?",
                (user["enabled"], username),
            )

        flash(f"更新 3proxy 失败：{exc}", "error")

    return redirect(url_for("index"))


@app.route("/users/<username>/password", methods=["POST"])
@login_required
def change_password(username):
    validate_csrf()
    password = request.form.get("password", "").strip()

    if (
        len(password) < 4
        or len(password) > 64
        or ":" in password
        or any(char.isspace() for char in password)
    ):
        flash(
            "密码必须为 4—64 个字符，且不能包含空格或冒号。",
            "error",
        )
        return redirect(url_for("index"))

    with db_connection() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if not user:
            abort(404)

        old_password = user["password"]

        conn.execute(
            "UPDATE users SET password = ? WHERE username = ?",
            (password, username),
        )

    try:
        rebuild_users_config()
        flash(f"用户 {username} 的密码已修改。", "success")
    except Exception as exc:
        with db_connection() as conn:
            conn.execute(
                "UPDATE users SET password = ? WHERE username = ?",
                (old_password, username),
            )

        flash(f"更新 3proxy 失败：{exc}", "error")

    return redirect(url_for("index"))


@app.route("/users/<username>/delete", methods=["POST"])
@login_required
def delete_user(username):
    validate_csrf()

    with db_connection() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if not user:
            abort(404)

        conn.execute(
            "DELETE FROM users WHERE username = ?",
            (username,),
        )

    try:
        rebuild_users_config()
        flash(f"用户 {username} 已删除。", "success")
    except Exception as exc:
        with db_connection() as conn:
            conn.execute(
                """
                INSERT INTO users(username, password, enabled, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (
                    user["username"],
                    user["password"],
                    user["enabled"],
                    user["created_at"],
                ),
            )

        flash(f"更新 3proxy 失败：{exc}", "error")

    return redirect(url_for("index"))


@app.route("/users/<username>")
@login_required
def user_detail(username):
    parse_log_incrementally()

    with db_connection() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if not user:
            abort(404)

        traffic = conn.execute(
            """
            SELECT ts, client_ip, target, download, upload
            FROM traffic
            WHERE username = ?
            ORDER BY ts DESC
            """,
            (username,),
        ).fetchall()

    daily = {}
    recent = []

    for row in traffic:
        local_dt = datetime.fromtimestamp(row["ts"], TZ)
        day_key = local_dt.strftime("%Y-%m-%d")
        daily.setdefault(day_key, 0)
        daily[day_key] += row["download"] + row["upload"]

        if len(recent) < 30:
            recent.append(
                {
                    "time": local_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "ip": row["client_ip"],
                    "target": row["target"],
                    "download": row["download"],
                    "upload": row["upload"],
                }
            )

    days = []

    for offset in range(29, -1, -1):
        current_day = (
            datetime.now(TZ).date() - timedelta(days=offset)
        ).strftime("%Y-%m-%d")

        days.append(
            {
                "date": current_day,
                "value": daily.get(current_day, 0),
            }
        )

    maximum = max((day["value"] for day in days), default=1) or 1

    for day in days:
        day["percent"] = max(1, round(day["value"] / maximum * 100))

    template = """
<!doctype html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{{ username }} · 3proxy 管理面板</title>
""" + BASE_STYLE + """
</head>
<body>
<div class="shell">
""" + HEADER + """
<main class="main">
{% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, message in messages %}
        <div class="flash {{ category }}">{{ message }}</div>
    {% endfor %}
{% endwith %}

<div class="detail-grid">
    <section class="section" style="margin-top:0">
        <div class="section-h">
            <div>
                <h2><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-chart"/></svg>{{ username }} · 近 30 天流量</h2>
                <p class="hint">下载与上传流量合计。</p>
            </div>
            <a class="btn ghost" href="{{ url_for('index') }}">← 返回总览</a>
        </div>
        <div class="form-body">
            {% for day in days %}
            <div class="daily-row">
                <div>{{ day.date }}</div>
                <div class="bar-track"><i style="width:{{ day.percent }}%"></i></div>
                <div class="amt">{{ day.value|bytes }}</div>
            </div>
            {% endfor %}
        </div>
    </section>

    <section class="section" style="margin-top:0">
        <div class="section-h">
            <div>
                <h2>最近连接</h2>
                <p class="hint">最近 30 条已完成的代理连接。</p>
            </div>
        </div>
        {% if recent %}
        <div class="table-wrap">
            <table>
                <thead>
                <tr>
                    <th>时间</th>
                    <th>客户端 IP</th>
                    <th>目标地址</th>
                    <th>下载 / 上传</th>
                </tr>
                </thead>
                <tbody>
                {% for item in recent %}
                <tr>
                    <td class="mono">{{ item.time }}</td>
                    <td class="mono">{{ item.ip }}</td>
                    <td class="mono">{{ item.target }}</td>
                    <td class="num">
                        ↓ {{ item.download|bytes }}
                        <div class="user-note">↑ {{ item.upload|bytes }}</div>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
            <div class="empty">暂无流量记录。</div>
        {% endif %}
    </section>
</div>

<section class="section">
    <div class="section-h">
        <div>
            <h2>修改 {{ username }} 的密码</h2>
            <p class="hint">保存后立即写入 3proxy 配置并生效。</p>
        </div>
    </div>
    <div class="form-body">
        <form class="form-grid" method="post" action="{{ url_for('change_password', username=username) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <div class="field">
                <label>新密码</label>
                <input class="input" name="password" type="password" minlength="4" maxlength="64"
                       autocomplete="new-password" placeholder="至少 4 位" required>
            </div>
            <div></div>
            <button class="btn primary" type="submit">保存密码</button>
        </form>
    </div>
</section>

<footer class="footer">3proxy Panel · 私人管理</footer>
</main>
</div>
</body>
</html>
"""

    return render_template_string(
        template,
        username=username,
        days=days,
        recent=recent,
        csrf_token=CSRF_TOKEN,
        timezone=TZ_NAME,
    )


init_db()
import_users_from_config()
parse_log_incrementally()

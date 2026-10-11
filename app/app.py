import hmac
import csv
import io
import os
import re
import shlex
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import quote, urlparse
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
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect x='3' y='4' width='18' height='6' rx='1.5' fill='none' stroke='%232a78d6' stroke-width='1.75'/%3E%3Crect x='3' y='14' width='18' height='6' rx='1.5' fill='none' stroke='%232a78d6' stroke-width='1.75'/%3E%3C/svg%3E">
<style>
:root{
  --bg:#ffffff;--surface:#ffffff;--surface-2:#f5f5f4;--surface-3:#e9e9e7;
  --line:#e4e4e1;--text:#111111;--muted:#5c5c59;--faint:#8c8c88;
  --accent:#2a78d6;--bad:#d9463f;--ok:#2f7a4d;
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
  --accent:#3987e5;--bad:#d9463f;--ok:#4caf7d;
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
.brand{font-size:13px;font-weight:700;letter-spacing:.02em;white-space:nowrap;text-decoration:none;cursor:pointer}
.brand:hover{opacity:.75}
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
td.num,th.num{text-align:right}
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
.ops-cell{text-align:right;white-space:nowrap}
.menu-btn{width:28px;height:28px;border-radius:4px;border:1px solid transparent;background:transparent;
  cursor:pointer;display:inline-flex;align-items:center;justify-content:center;padding:0;color:var(--muted)}
.menu-btn:hover,.menu-btn.open{background:var(--surface-2);border-color:var(--line);color:var(--text)}
.menu{display:none;position:fixed;min-width:172px;background:var(--surface);
  border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);padding:4px;z-index:80;
  max-height:calc(100vh - 16px);overflow:auto}
.menu.open{display:block}
.menu form{display:block;margin:0}
.menu button{display:block;width:100%;text-align:left;border:0;background:transparent;padding:8px 10px;
  border-radius:4px;font:inherit;cursor:pointer;color:var(--text);box-sizing:border-box}
.menu button:hover{background:var(--surface-2)}
.menu button.bad{color:var(--bad)}
.menu .sep{height:1px;background:var(--line);margin:4px}
th.sortable{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable:hover{color:var(--text)}
th.sortable.active{color:var(--text)}
th.sortable.active::after{content:attr(data-dir);margin-left:4px;font-size:10px}
.stack{display:flex;flex-direction:column;gap:8px}
.modal-scrim{display:none;position:fixed;inset:0;background:rgba(17,17,17,.4);z-index:70;align-items:center;justify-content:center;padding:8px}
.modal-scrim.open{display:flex}
html[data-theme="dark"] .modal-scrim{background:rgba(0,0,0,.55)}
.modal{background:var(--surface);border-radius:var(--radius);border:1px solid var(--line);width:min(400px,100%);padding:16px;box-shadow:var(--shadow)}
.modal h3{margin:0 0 6px;font-size:14px}
.modal .hint{margin-bottom:12px}
.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}
.toast{position:fixed;right:16px;bottom:16px;background:var(--text);color:var(--bg);padding:10px 14px;
  border-radius:var(--radius);opacity:0;pointer-events:none;transition:opacity .2s;z-index:100;max-width:320px;font-size:13px}
.toast.show{opacity:1}
.log-box{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  padding:10px 12px;font-family:var(--mono);font-size:11.5px;line-height:1.65;
  max-height:340px;overflow:auto;white-space:pre-wrap;word-break:break-all}
.act-list{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);overflow:auto;max-height:420px}
.act-row{display:flex;gap:14px;padding:8px 12px;border-bottom:1px solid var(--line);font-size:12.5px;align-items:baseline}
.act-row:last-child{border-bottom:0}
.act-row:hover{background:var(--surface-2)}
.act-row .t{color:var(--faint);font-family:var(--mono);white-space:nowrap;flex-shrink:0}
.empty{padding:22px 12px;text-align:center;color:var(--faint);background:var(--surface);border:1px solid var(--line);border-radius:var(--radius)}
.flash{margin:0 0 14px;padding:10px 12px;border-radius:var(--radius);font-size:13px;border:1px solid var(--line)}
.flash.success{background:var(--surface);color:var(--ok);border-color:var(--ok)}
.flash.error{background:var(--surface);color:var(--bad);border-color:var(--bad)}
.form-body{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px}
.form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:end}
.field{display:flex;flex-direction:column;gap:6px;min-width:0}
.field label{font-size:12px;color:var(--faint);font-weight:650}
.input{border:1px solid var(--line);border-radius:4px;padding:8px 10px;width:100%;background:var(--surface);font-family:var(--mono);font-size:13px}
.input:focus{outline:2px solid var(--accent);outline-offset:1px;border-color:var(--accent)}
.btn:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.daily-row{display:grid;grid-template-columns:96px minmax(0,1fr) 92px;gap:10px;align-items:center;font-size:12px;padding:4px 0}
.daily-row .amt{text-align:right}
.bar-track{height:4px;background:var(--surface-3);border-radius:2px;overflow:hidden}
.bar-track i{display:block;height:100%;background:var(--accent);border-radius:2px}
.day-cols{display:flex;align-items:stretch;gap:4px;height:180px}
.day-col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;min-width:0}
.day-col .amt{font-size:10px;color:var(--faint);font-family:var(--mono);margin:0 0 4px;white-space:nowrap;opacity:0}
.day-col:hover .amt{opacity:1}
.day-col .stack-bar{display:flex;flex-direction:column;justify-content:flex-end;width:100%;min-height:3px;border-radius:2px 2px 0 0;overflow:hidden}
.day-col .stack-bar i{display:block;width:100%;min-height:0}
.day-col .stack-bar .up{background:var(--muted)}
.day-col .stack-bar .down{background:var(--accent)}
.day-col .lbl{font-size:10px;color:var(--faint);font-family:var(--mono);white-space:nowrap;margin-top:5px}
.hour-cols{display:flex;align-items:flex-end;gap:4px;height:150px}
.hour-col{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;min-width:0;height:100%}
.hour-col .bar{display:block;width:100%;border-radius:2px 2px 0 0;min-height:3px;background:var(--accent)}
.hour-col.peak .bar{background:var(--bad)}
.hour-col .lbl{font-size:10px;color:var(--faint);font-family:var(--mono);margin-top:5px}
.updown-legend{display:flex;gap:12px;font-size:12px;color:var(--muted);font-family:var(--mono)}
.updown-legend i{width:8px;height:8px;border-radius:2px;display:inline-block;margin-right:4px}
.updown-legend .up i{background:var(--muted)}
.updown-legend .down i{background:var(--accent)}
.dest-wrap{overflow:auto;border:1px solid var(--line);border-radius:var(--radius);background:var(--surface)}
.dest-table{width:100%;border-collapse:collapse;font-size:12px}
.dest-table th,.dest-table td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left}
.dest-table th{font-size:11px;color:var(--faint);font-weight:600}
.dest-table td.num,.dest-table th.num{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums}
.dest-table tr:last-child td{border-bottom:0}
.dest-table tr:hover td{background:var(--surface-2)}
.dest-host{font-weight:650;word-break:break-all}
.chart-empty{display:flex;align-items:center;justify-content:center;height:120px;color:var(--faint);font-size:12px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}
.bar-btn{height:10px;border-radius:2px;overflow:hidden;display:flex}
.bar-btn i{display:block;height:100%}
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
document.addEventListener("submit",function(e){
  if(e.defaultPrevented)return; // 用户取消确认框时不要置灰按钮,否则会一直卡在"处理中…"
  var b=e.target.querySelector("button[type=submit]");
  if(b&&!b.disabled){b.dataset.label=b.textContent;b.disabled=true;b.textContent="处理中…";}
});
function sortUsers(th){
  var table=document.getElementById("userTable");
  if(!table)return;
  var idx=Array.prototype.indexOf.call(th.parentNode.children,th);
  var dir=th.dataset.sortdir==="asc"?-1:1;
  Array.prototype.forEach.call(th.parentNode.children,function(h){h.classList.remove("active");h.removeAttribute("data-dir");h.removeAttribute("data-sortdir");});
  th.classList.add("active");
  th.dataset.sortdir=dir===1?"asc":"desc";
  th.setAttribute("data-dir",dir===1?"↑":"↓");
  var rows=Array.prototype.slice.call(table.tBodies[0].rows);
  rows.sort(function(a,b){
    var ca=a.cells[idx],cb=b.cells[idx];
    var va=ca.dataset.v,vb=cb.dataset.v;
    if(va!==undefined&&vb!==undefined){return (parseFloat(va)-parseFloat(vb))*dir;}
    var sa=(ca.dataset.s!==undefined?ca.dataset.s:ca.textContent).trim();
    var sb=(cb.dataset.s!==undefined?cb.dataset.s:cb.textContent).trim();
    return (sa<sb?-1:sa>sb?1:0)*dir;
  });
  rows.forEach(function(r){table.tBodies[0].appendChild(r);});
}
function openModal(id){
  var m=document.getElementById(id||"addModal");
  if(!m)return;
  m.classList.add("open");
  var f=m.querySelector("input");
  if(f)f.focus();
}
function closeModal(m){
  var s=(m&&m.classList&&m.classList.contains("modal-scrim"))?m:document.querySelector(".modal-scrim.open");
  if(s)s.classList.remove("open");
}
document.addEventListener("keydown",function(e){
  if(e.key==="Escape"){
    var s=document.querySelector(".modal-scrim.open");
    if(s)s.classList.remove("open");
    closeMenus();
  }
});
function toast(msg){
  var t=document.getElementById("toast");
  if(!t){t=document.createElement("div");t.id="toast";t.className="toast";document.body.appendChild(t);}
  t.textContent=msg;t.classList.add("show");
  clearTimeout(t._h);t._h=setTimeout(function(){t.classList.remove("show");},1800);
}
function copyText(text,msg){
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(function(){toast(msg||"已复制");},function(){fallbackCopy(text,msg);});
  }else{fallbackCopy(text,msg);}
}
function fallbackCopy(text,msg){
  var ta=document.createElement("textarea");
  ta.value=text;ta.style.position="fixed";ta.style.opacity="0";
  document.body.appendChild(ta);ta.select();
  try{document.execCommand("copy");toast(msg||"已复制");}catch(e){toast("复制失败");}
  document.body.removeChild(ta);
}
function copyProxy(name){
  fetch("/users/"+encodeURIComponent(name)+"/proxy",{credentials:"same-origin"})
    .then(function(r){if(!r.ok)throw new Error("bad");return r.text();})
    .then(function(t){copyText(t,"已复制代理连接");})
    .catch(function(){toast("获取代理连接失败");});
}
function copyPassword(name){
  fetch("/users/"+encodeURIComponent(name)+"/password",{credentials:"same-origin"})
    .then(function(r){if(!r.ok)throw new Error("bad");return r.text();})
    .then(function(t){copyText(t,"已复制密码");})
    .catch(function(){toast("获取密码失败");});
}
function closeMenus(){
  Array.prototype.forEach.call(document.querySelectorAll(".menu.open"),function(m){m.classList.remove("open");});
  Array.prototype.forEach.call(document.querySelectorAll(".menu-btn.open"),function(b){b.classList.remove("open");});
}
function toggleMenu(btn,ev){
  if(ev&&ev.stopPropagation){ev.stopPropagation();}
  var menu=btn.nextElementSibling;
  if(!menu)return;
  var wasOpen=menu.classList.contains("open");
  closeMenus();
  if(wasOpen)return;
  menu.classList.add("open");
  btn.classList.add("open");
  var r=btn.getBoundingClientRect();
  var top=r.bottom+4;
  if(top+menu.offsetHeight>window.innerHeight-8){top=Math.max(8,r.top-4-menu.offsetHeight);}
  menu.style.top=top+"px";
  menu.style.left=Math.max(8,Math.min(r.right-menu.offsetWidth,window.innerWidth-menu.offsetWidth-8))+"px";
}
document.addEventListener("click",function(e){
  if(!e.target.closest||(!e.target.closest(".menu")&&!e.target.closest(".menu-btn"))){closeMenus();}
});
window.addEventListener("scroll",closeMenus,true);
</script>
"""

HEADER = """
<svg class="sprite" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <symbol id="i-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></symbol>
  <symbol id="i-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/></symbol>
  <symbol id="i-users" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="3"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></symbol>
  <symbol id="i-more" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="6" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="18" r="1.6"/></symbol>
  <symbol id="i-activity" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M22 12h-4l-3 7L9 5l-3 7H2"/></symbol>
  <symbol id="i-chart" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M18 20V10M12 20V4M6 20v-6"/></symbol>
  <symbol id="i-server" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01"/></symbol>
</svg>
<header class="topbar">
  <div class="nav-left">
    <a class="brand" href="{{ url_for('index') }}">3proxy Panel</a>
  </div>
  <div class="nav-right">
    <div class="nav-status">SOCKS5 代理 · 时区 {{ timezone }}</div>
    <button id="themeBtn" class="icon-btn" type="button" aria-label="切换主题" title="主题" onclick="toggleTheme()">
      <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-moon"/></svg>
    </button>
    <button class="btn" type="button" onclick="toggleMenu(this,event)">菜单</button>
    <div class="menu">
      <button type="button" onclick="location.href='{{ url_for('logs_page') }}'">系统日志总览</button>
      <div class="sep"></div>
      <button type="button" onclick="location.href='{{ url_for('logs_download', h=1) }}'">下载连接日志 · 最近 1 小时</button>
      <button type="button" onclick="location.href='{{ url_for('logs_download', h=24) }}'">下载连接日志 · 最近 24 小时</button>
      <button type="button" onclick="location.href='{{ url_for('logs_download', h=72) }}'">下载连接日志 · 最近 3 天</button>
      <button type="button" onclick="location.href='{{ url_for('logs_download') }}'">下载连接日志 · 全部</button>
    </div>
  </div>
</header>
"""


def local_day(ts):
    # 把 Unix 时间戳按面板配置的时区 TZ_NAME 折算成 YYYY-MM-DD。
    # 不能依赖 SQLite 的 'localtime'：它用的是服务器系统时区（/etc/localtime 或 TZ 环境变量），
    # 与面板配置的 TZ_NAME 不一致时，趋势图/24 小时分布会整体偏移。
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), TZ).strftime("%Y-%m-%d")


def local_hour(ts):
    # 同上，折算成 00-23 的小时字符串，供 24 小时分布使用。
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H")


def db_connection():
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    # 注册按 TZ_NAME 分桶的函数，替代受系统时区影响的 'localtime'
    connection.create_function("local_day", 1, local_day, deterministic=True)
    connection.create_function("local_hour", 1, local_hour, deterministic=True)
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
                upload INTEGER NOT NULL DEFAULT 0,
                host TEXT
            )
            """
        )
        # 旧库迁移：补 host 列（目标域名，来自日志 H:%n）
        try:
            conn.execute("ALTER TABLE traffic ADD COLUMN host TEXT")
        except sqlite3.OperationalError:
            pass
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


def upgrade_logformat():
    # 旧配置迁移：logformat 补 H:%n（目标域名）/ D:%D（时长）/ E:%E（结果码）
    # 只改配置文件，3proxy 重启后生效（不在此处重启，避免面板崩溃循环牵动代理）
    if not PROXY_CONFIG.exists():
        return

    try:
        lines = PROXY_CONFIG.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines()
    except OSError:
        return

    if any("H:%n" in line for line in lines):
        return

    new_line = (
        'logformat "-L%t %U %C:%c %R:%r IN:%I OUT:%O H:%n D:%D E:%E"'
    )

    for index, line in enumerate(lines):
        if line.strip().startswith("logformat "):
            lines[index] = new_line
            break
    else:
        return

    try:
        PROXY_CONFIG.write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    except OSError:
        pass


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
            generation = int(get_state(conn, "log_generation", "0") or 0)

            if old_inode != inode or stat.st_size < old_offset:
                old_offset = 0
                # 截断(如 copytruncate)/换文件后偏移量从头再来,
                # event_key 递增代数,避免与旧记录同键碰撞被 INSERT OR IGNORE 静默丢弃
                generation += 1

            with LOG_PATH.open("rb") as log_file:
                log_file.seek(old_offset)
                # 只有完整读到换行结尾的行,才把偏移量推进到该行之后;
                # 半行(3proxy 尚未写完)不推进,留待下次补全后再解析
                safe_offset = old_offset

                while True:
                    line_offset = log_file.tell()
                    raw_line = log_file.readline()

                    if not raw_line:
                        break

                    # 3proxy 仍在写入的半行(无换行结尾)留待下次解析,避免被截断入库
                    if not raw_line.endswith(b"\n"):
                        break

                    # 这一行已完整读取,偏移量可安全推进(格式不匹配也可永久跳过)
                    safe_offset = log_file.tell()

                    line = raw_line.decode("utf-8", errors="ignore").strip()

                    match = re.search(
                        r"^L(\d+)\s+(\S+)\s+(\S+)\s+(\S+).*?"
                        r"IN:(\d+)\s+OUT:(\d+)"
                        r"(?:\s+H:(\S+))?(?:\s+D:(\d+))?(?:\s+E:(\d+))?",
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
                    host = (match.group(7) or "").strip("[]")
                    event_key = f"{inode}:{generation}:{line_offset}"

                    conn.execute(
                        """
                        INSERT OR IGNORE INTO traffic(
                            event_key, ts, username, client_ip,
                            target, download, upload, host
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_key,
                            ts,
                            username,
                            client_ip,
                            target,
                            download,
                            upload,
                            host,
                        ),
                    )

                set_state(conn, "log_inode", inode)
                set_state(conn, "log_offset", safe_offset)
                set_state(conn, "log_generation", generation)


def authorized():
    auth = request.authorization

    # ADMIN_PASS 未配置(为空)时必须拒绝,否则空密码会通过比较直接登录
    if not ADMIN_PASS or not auth:
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

    # CSRF_TOKEN 为空时必须拒绝,否则空 token 会通过比较
    if not CSRF_TOKEN or not hmac.compare_digest(token, CSRF_TOKEN):
        abort(403)


def format_bytes(value):
    value = int(value or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)

    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"

            return f"{amount:.2f} {unit}".replace(".00 ", " ")

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


def redirect_back(fallback="index"):
    # 操作后回到来源页（仅允许站内路径，防开放重定向）
    target = request.form.get("next") or request.referrer or ""
    path = urlparse(target).path
    # 浏览器会把 \ 当作 /,因此 "/\evil.com" 同样会跳转到外站
    if (
        path.startswith("/")
        and not path.startswith("//")
        and "\\" not in path
        and not any(ord(char) < 32 for char in path)
    ):
        return redirect(path)
    return redirect(url_for(fallback))


@app.route("/")
@login_required
def index():
    parse_log_incrementally()
    rows = dashboard_rows()
    # 复制 IP 用：取主机名（IPv6 不带方括号，便于粘到客户端服务器栏）
    proxy_host = urlparse("//" + request.host).hostname or request.host

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
            <p class="hint">在线状态根据最近 3 分钟内的连接活动判断；点击用户名查看流量分析。</p>
        </div>
        <div class="ops-bar">
            <button class="btn" type="button" data-ip="{{ proxy_host|e }}" onclick="copyText(this.dataset.ip,'已复制 IP')">复制 IP</button>
            <button class="btn primary" type="button" onclick="openModal('addModal')">+ 新增用户</button>
        </div>
    </div>
    {% if rows %}
    <div class="table-wrap">
        <table id="userTable">
            <thead>
            <tr>
                <th class="sortable" onclick="sortUsers(this)">用户</th>
                <th>状态</th>
                <th class="num sortable" onclick="sortUsers(this)">今日</th>
                <th class="num sortable" onclick="sortUsers(this)">本月</th>
                <th class="num sortable" onclick="sortUsers(this)">累计下载 / 上传</th>
                <th>最近 IP</th>
                <th class="num sortable" onclick="sortUsers(this)" title="近 24 小时内出现过的不同客户端 IP 数">24h IP ⓘ</th>
                <th class="num">操作</th>
            </tr>
            </thead>
            <tbody>
            {% for row in rows %}
            <tr class="{{ 'disabled' if not row.enabled else '' }}" data-name="{{ row.username }}">
                <td data-s="{{ row.username }}">
                    <a class="user-name" href="{{ url_for('user_detail', username=row.username) }}">{{ row.username }}</a>
                    <div class="user-note" title="最近目标 · {{ row.last_target }}">最近目标 · {{ row.last_target }}</div>
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
                <td class="num" data-v="{{ row.today_total }}">{{ row.today_total|bytes }}</td>
                <td class="num" data-v="{{ row.month_total }}">{{ row.month_total|bytes }}</td>
                <td class="num" data-v="{{ row.total_download + row.total_upload }}">
                    ↓ {{ row.total_download|bytes }}
                    <div class="user-note">↑ {{ row.total_upload|bytes }}</div>
                </td>
                <td class="mono">{{ row.last_ip }}</td>
                <td class="num" data-v="{{ row.ip_count }}">{{ row.ip_count }}</td>
                <td class="ops-cell">
                    <button class="menu-btn" type="button" aria-label="操作" onclick="toggleMenu(this,event)">
                        <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-more"/></svg>
                    </button>
                    <div class="menu">
                        <button type="button" data-username="{{ row.username|e }}" onclick="copyText(this.dataset.username,'已复制用户名')">复制用户名</button>
                        <button type="button" data-username="{{ row.username|e }}" onclick="copyPassword(this.dataset.username)">复制密码</button>
                        <button type="button" onclick="location.href='{{ url_for('user_detail', username=row.username) }}'">查看详情</button>
                        <button type="button" onclick="location.href='{{ url_for('export_user_csv', username=row.username) }}'">导出 CSV</button>
                        <form method="post" action="{{ url_for('toggle_user', username=row.username) }}">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                            <button type="submit">{{ "启用" if not row.enabled else "禁用" }}用户</button>
                        </form>
                        <button type="button" data-username="{{ row.username|e }}" onclick="copyProxy(this.dataset.username)">复制代理连接</button>
                        <div class="sep"></div>
                        <form method="post" action="{{ url_for('delete_user', username=row.username) }}"
                              data-username="{{ row.username|e }}" onsubmit="return confirm('确定永久删除用户 '+this.dataset.username+'？\\n该用户的流量统计会保留，但账号将从 3proxy 移除。')">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                            <button class="bad" type="submit">删除用户</button>
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

<div class="modal-scrim" id="addModal" onclick="if(event.target===this)closeModal(this)">
    <div class="modal" role="dialog" aria-label="新增用户">
        <h3>新增用户</h3>
        <p class="hint">创建后立即写入 3proxy 配置并生效。</p>
        <form class="stack" method="post" action="{{ url_for('add_user') }}">
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
            <div class="modal-actions">
                <button class="btn" type="button" onclick="closeModal()">取消</button>
                <button class="btn primary" type="submit">创建用户</button>
            </div>
        </form>
    </div>
</div>

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
        proxy_host=proxy_host,
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
        return redirect_back()

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
        return redirect_back()

    with db_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if exists:
            flash("该用户名已存在。", "error")
            return redirect_back()

        conn.execute(
            """
            INSERT INTO users(username, password, enabled, created_at)
            VALUES(?, ?, 1, ?)
            """,
            (username, password, int(datetime.now(TZ).timestamp())),
        )

    try:
        rebuild_users_config()
        log_activity(f"创建用户 {username}")
        flash(f"用户 {username} 创建成功。", "success")
    except Exception as exc:
        with db_connection() as conn:
            conn.execute(
                "DELETE FROM users WHERE username = ?",
                (username,),
            )

        flash(f"3proxy 配置更新失败，已回滚到之前状态：{exc}", "error")

    return redirect_back()


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
        log_activity(f"{action}用户 {username}")
        flash(f"用户 {username} 已{action}。", "success")
    except Exception as exc:
        with db_connection() as conn:
            conn.execute(
                "UPDATE users SET enabled = ? WHERE username = ?",
                (user["enabled"], username),
            )

        flash(f"3proxy 配置更新失败，已回滚到之前状态：{exc}", "error")

    return redirect_back()


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
        return redirect_back()

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
        log_activity(f"修改用户 {username} 的密码")
        flash(f"用户 {username} 的密码已修改。", "success")
    except Exception as exc:
        with db_connection() as conn:
            conn.execute(
                "UPDATE users SET password = ? WHERE username = ?",
                (old_password, username),
            )

        flash(f"3proxy 配置更新失败，已回滚到之前状态：{exc}", "error")

    return redirect_back()


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
        log_activity(f"删除用户 {username}")
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

        flash(f"3proxy 配置更新失败，已回滚到之前状态：{exc}", "error")

    return redirect_back()


def socks_port():
    try:
        text = PROXY_CONFIG.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "1234"

    # 行首锚定跳过 # 注释行，否则注释掉的旧端口会被当成实际端口
    match = re.search(r"^\s*socks\s+-p(\d+)", text, re.MULTILINE)
    return match.group(1) if match else "1234"


ACTIVITY_LOG = APP_DIR / "activity.log"


def log_activity(text):
    # 项目动态：面板操作与 install.sh 系统事件共用此文件
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        with open(ACTIVITY_LOG, "a", encoding="utf-8") as file:
            file.write(f"{stamp}  {text}\n")
    except OSError:
        pass


def read_activity(limit=200):
    try:
        with open(ACTIVITY_LOG, encoding="utf-8", errors="ignore") as file:
            return file.read().splitlines()[-limit:]
    except OSError:
        return []


def service_log(unit, lines=60):
    try:
        result = subprocess.run(
            [
                "journalctl",
                "-u",
                unit,
                "-n",
                str(lines),
                "--no-pager",
                "-o",
                "short-iso",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip().splitlines()
    except Exception:
        return []


def tail_log(path, lines=200):
    try:
        with open(path, "rb") as file:
            file.seek(0, 2)
            size = file.tell()
            file.seek(max(0, size - 256 * 1024))
            data = file.read().decode("utf-8", errors="ignore")
        return data.splitlines()[-lines:]
    except OSError:
        return []


@app.route("/users/<username>/proxy")
@login_required
def user_proxy(username):
    # 一键复制用：返回 socks5://user:pass@host:port 连接串
    with db_connection() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    if not user:
        abort(404)

    auth = quote(username, safe="") + ":" + quote(user["password"], safe="")
    # 用 urlparse 取主机名:直接 split(":") 在 IPv6 字面量(如 [::1]:18080)下会得到 "["
    host = urlparse("//" + request.host).hostname or request.host
    if ":" in host:
        host = f"[{host}]"  # IPv6 字面量在 URL 里必须带方括号
    return f"socks5://{auth}@{host}:{socks_port()}"


@app.route("/users/<username>/password", methods=["GET"])
@login_required
def user_password(username):
    # 一键复制用：返回明文密码（密码不渲染进页面，由前端按需取）
    with db_connection() as conn:
        user = conn.execute(
            "SELECT password FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    if not user:
        abort(404)
    return user["password"]


def export_csv_response(username=None, hours=None):
    parse_log_incrementally()

    query = (
        "SELECT ts, username, client_ip, target, download, upload, host "
        "FROM traffic"
    )
    conditions = []
    params = []

    if username:
        conditions.append("username = ?")
        params.append(username)

    if hours:
        cutoff = int(datetime.now(TZ).timestamp()) - int(hours) * 3600
        conditions.append("ts >= ?")
        params.append(cutoff)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY ts DESC"

    stamp = datetime.now(TZ).strftime("%Y%m%d")
    window = f"{hours}h" if hours else "all"
    filename = f"3proxy-{username or 'all'}-{window}-{stamp}.csv"

    # 先执行查询(出错时仍能正常返回 500),再逐行流式输出,
    # 避免把整张流量表 fetchall 进内存(与连接日志下载同样的处理)
    conn = db_connection()
    try:
        cursor = conn.execute(query, tuple(params))
    except Exception:
        conn.close()
        raise

    def generate():
        try:
            buffer = io.StringIO()
            writer = csv.writer(buffer)

            def row_text(values):
                buffer.seek(0)
                buffer.truncate(0)
                writer.writerow(values)
                return buffer.getvalue()

            yield "\ufeff" + row_text(
                ["时间", "用户名", "客户端IP", "目标", "域名", "下载(字节)", "上传(字节)"]
            )

            for row in cursor:
                yield row_text(
                    [
                        datetime.fromtimestamp(row["ts"], TZ).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        row["username"],
                        row["client_ip"],
                        row["target"],
                        row["host"] or "",
                        row["download"],
                        row["upload"],
                    ]
                )
        finally:
            conn.close()

    return Response(
        generate(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        },
    )


@app.route("/export.csv")
@login_required
def export_csv():
    return export_csv_response(None, request.args.get("h", type=int))


@app.route("/users/<username>/export.csv")
@login_required
def export_user_csv(username):
    with db_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    if not exists:
        abort(404)

    return export_csv_response(username)


@app.route("/logs/download")
@login_required
def logs_download():
    # 系统级连接日志下载（3proxy access.log 原始行，按时间窗过滤）
    hours = request.args.get("h", type=int)
    cutoff = (
        int(datetime.now(TZ).timestamp()) - int(hours) * 3600 if hours else None
    )
    def generate():
        # 流式逐行输出,避免大日志整体载入内存
        try:
            with LOG_PATH.open("rb") as file:
                for raw in file:
                    line = raw.decode("utf-8", errors="ignore").rstrip()
                    if cutoff is not None:
                        match = re.match(r"^L(\d+)", line)
                        if not match or int(match.group(1)) < cutoff:
                            continue
                    yield line + "\n"
        except OSError:
            pass

    stamp = datetime.now(TZ).strftime("%Y%m%d")
    window = f"{hours}h" if hours else "all"
    filename = f"3proxy-log-{window}-{stamp}.txt"

    return Response(
        generate(),
        mimetype="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        },
    )


@app.route("/logs")
@login_required
def logs_page():
    # 系统级日志中心：项目动态 / 运行日志 / 流量
    parse_log_incrementally()
    _, day_start, month_start = time_boundaries()

    with db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY username"
        ).fetchall()

        totals = conn.execute(
            """
            SELECT COALESCE(SUM(download), 0) AS dl,
                   COALESCE(SUM(upload), 0) AS ul,
                   COALESCE(SUM(CASE WHEN ts >= ? THEN download + upload ELSE 0 END), 0) AS today,
                   COALESCE(SUM(CASE WHEN ts >= ? THEN download + upload ELSE 0 END), 0) AS month
            FROM traffic
            """,
            (day_start, month_start),
        ).fetchone()

        now_dt = datetime.now(TZ)
        cutoff30 = int(
            (now_dt - timedelta(days=29))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
        )

        day_rows = conn.execute(
            """
            SELECT local_day(ts) AS day,
                   COALESCE(SUM(download), 0) AS dl,
                   COALESCE(SUM(upload), 0) AS ul
            FROM traffic WHERE ts >= ?
            GROUP BY day
            """,
            (cutoff30,),
        ).fetchall()

        hour_rows = conn.execute(
            """
            SELECT local_hour(ts) AS hour,
                   COALESCE(SUM(download + upload), 0) AS total
            FROM traffic WHERE ts >= ?
            GROUP BY hour
            """,
            (cutoff30,),
        ).fetchall()

        user_rows = conn.execute(
            """
            SELECT username,
                   COALESCE(SUM(CASE WHEN ts >= ? THEN download + upload ELSE 0 END), 0) AS today,
                   COALESCE(SUM(CASE WHEN ts >= ? THEN download + upload ELSE 0 END), 0) AS month,
                   COALESCE(SUM(download + upload), 0) AS total
            FROM traffic
            GROUP BY username
            ORDER BY total DESC
            """,
            (day_start, month_start),
        ).fetchall()

    day_map = {
        row["day"]: (int(row["dl"] or 0), int(row["ul"] or 0))
        for row in day_rows
    }
    days = []

    for offset in range(29, -1, -1):
        day_key = (now_dt.date() - timedelta(days=offset)).strftime(
            "%Y-%m-%d"
        )
        dl, ul = day_map.get(day_key, (0, 0))
        days.append(
            {"date": day_key, "download": dl, "upload": ul, "total": dl + ul}
        )

    day_max = max((day["total"] for day in days), default=1) or 1

    for day in days:
        day["pct_total"] = (
            max(2, round(day["total"] / day_max * 100)) if day["total"] else 0
        )
        if day["total"]:
            day["pct_down"] = round(day["download"] / day["total"] * 100)
            day["pct_up"] = 100 - day["pct_down"]
        else:
            day["pct_down"] = day["pct_up"] = 0

    hour_map = {
        int(row["hour"]): int(row["total"] or 0) for row in hour_rows
    }
    hours = [
        {"hour": hour, "total": hour_map.get(hour, 0)} for hour in range(24)
    ]
    hour_max = max((hour["total"] for hour in hours), default=1) or 1
    peak_hour = max(hours, key=lambda hour: hour["total"])

    for hour in hours:
        hour["pct"] = (
            max(2, round(hour["total"] / hour_max * 100))
            if hour["total"]
            else 0
        )
        hour["is_peak"] = (
            hour["hour"] == peak_hour["hour"] and hour["total"] > 0
        )

    activity_lines = read_activity()
    svc_lines = (
        ["— 3proxy —"]
        + service_log("3proxy")
        + ["", "— 面板 —"]
        + service_log("3proxy-dashboard")
    )
    conn_lines = tail_log(LOG_PATH)

    template = """
<!doctype html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>日志与动态 · 3proxy 管理面板</title>
""" + BASE_STYLE + """
</head>
<body>
<div class="shell">
""" + HEADER + """
<main class="main">

<section class="section" id="activity" style="margin-top:0">
    <div class="section-h">
        <div>
            <h2><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-activity"/></svg>项目动态</h2>
            <p class="hint">安装、更新与全部管理操作的变更记录。</p>
        </div>
    </div>
    {% if activity_lines %}
    <div class="act-list">
        {% for line in activity_lines|reverse %}
        {% set parts = line.split('  ', 1) %}
        <div class="act-row">
            <span class="t">{{ parts[0] }}</span>
            <span>{{ parts[1] if parts|length > 1 else line }}</span>
        </div>
        {% endfor %}
    </div>
    {% else %}
        <div class="empty">暂无动态记录。</div>
    {% endif %}
</section>

<section class="section" id="runtime">
    <div class="section-h">
        <div>
            <h2>运行日志</h2>
            <p class="hint">服务运行日志与最近连接日志。</p>
        </div>
    </div>
    <div class="detail-grid">
        <div>
            <p class="hint" style="margin:0 0 8px">服务日志（journalctl）</p>
            <div class="log-box">{{ svc_lines|join("\\n") }}</div>
        </div>
        <div>
            <div class="section-h" style="margin:0 0 8px">
                <p class="hint" style="margin:0">连接日志（access.log 最近 200 行）</p>
                <div class="ops">
                    <button class="btn ghost" type="button" onclick="location.href='{{ url_for('logs_download', h=1) }}'">1h</button>
                    <button class="btn ghost" type="button" onclick="location.href='{{ url_for('logs_download', h=24) }}'">24h</button>
                    <button class="btn ghost" type="button" onclick="location.href='{{ url_for('logs_download', h=72) }}'">3日</button>
                    <button class="btn ghost" type="button" onclick="location.href='{{ url_for('logs_download') }}'">全部</button>
                </div>
            </div>
            <div class="log-box">{{ conn_lines|join("\\n") or "暂无连接日志。" }}</div>
        </div>
    </div>
</section>

<section class="section" id="traffic">
    <div class="section-h">
        <div>
            <h2><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-chart"/></svg>流量</h2>
            <p class="hint">整机流量概览（下载 + 上传）。</p>
        </div>
    </div>
    <div class="kpis">
        <div class="metric">
            <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-activity"/></svg>今日流量</div>
            <div class="value">{{ total_today|bytes }}</div>
            <div class="extra">时区 {{ timezone }}</div>
        </div>
        <div class="metric">
            <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-chart"/></svg>本月流量</div>
            <div class="value">{{ total_month|bytes }}</div>
            <div class="extra">自然月合计</div>
        </div>
        <div class="metric">
            <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-server"/></svg>累计流量</div>
            <div class="value">{{ total_all|bytes }}</div>
            <div class="extra">↓ {{ total_download|bytes }} · ↑ {{ total_upload|bytes }}</div>
        </div>
        <div class="metric">
            <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-users"/></svg>峰值时段</div>
            <div class="value mono">{{ "%02d:00"|format(peak_hour.hour) }}</div>
            <div class="extra">{% if peak_hour.total %}近 30 天最忙小时 · {{ peak_hour.total|bytes }}{% else %}近 30 天暂无流量{% endif %}</div>
        </div>
    </div>

    <div class="detail-grid">
        <div class="form-body">
            <p class="hint" style="margin:0 0 10px">近 30 天趋势（下下载 · 上上传）</p>
            <div class="day-cols">
                {% for day in days %}
                <div class="day-col" title="{{ day.date }}  ↓ {{ day.download|bytes }}  ↑ {{ day.upload|bytes }}">
                    <div class="amt">{{ day.total|bytes }}</div>
                    {% if day.pct_total %}
                    <div class="stack-bar" style="height:{{ day.pct_total }}%">
                        <i class="up" style="height:{{ day.pct_up }}%"></i>
                        <i class="down" style="height:{{ day.pct_down }}%"></i>
                    </div>
                    {% else %}
                    <div class="stack-bar" style="height:2px"></div>
                    {% endif %}
                    <div class="lbl">{% if loop.index0 % 6 == 0 %}{{ day.date[5:] }}{% endif %}</div>
                </div>
                {% endfor %}
            </div>
        </div>
        <div class="form-body">
            <p class="hint" style="margin:0 0 10px">24 小时分布（近 30 天）</p>
            <div class="hour-cols">
                {% for hour in hours %}
                <div class="hour-col {{ 'peak' if hour.is_peak else '' }}"
                     title="{{ "%02d:00"|format(hour.hour) }} · {{ hour.total|bytes }}">
                    <div class="bar" style="height:{{ hour.pct }}%"></div>
                    <div class="lbl">{% if hour.hour % 3 == 0 %}{{ hour.hour }}{% endif %}</div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>

    <div class="table-wrap" style="margin-top:12px">
        <table>
            <thead>
            <tr>
                <th>用户</th>
                <th class="num">今日</th>
                <th class="num">本月</th>
                <th class="num">累计</th>
                <th class="num">操作</th>
            </tr>
            </thead>
            <tbody>
            {% for row in user_rows %}
            <tr>
                <td><a class="user-name" href="{{ url_for('user_detail', username=row.username) }}">{{ row.username }}</a></td>
                <td class="num">{{ row.today|bytes }}</td>
                <td class="num">{{ row.month|bytes }}</td>
                <td class="num">{{ row.total|bytes }}</td>
                <td class="num"><a class="btn ghost" href="{{ url_for('user_detail', username=row.username) }}">分析</a></td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
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
        activity_lines=activity_lines,
        svc_lines=svc_lines,
        conn_lines=conn_lines,
        days=days,
        hours=hours,
        peak_hour=peak_hour,
        user_rows=user_rows,
        total_today=int(totals["today"] or 0),
        total_month=int(totals["month"] or 0),
        total_download=int(totals["dl"] or 0),
        total_upload=int(totals["ul"] or 0),
        total_all=int(totals["dl"] or 0) + int(totals["ul"] or 0),
        timezone=TZ_NAME,
    )


@app.route("/users/<username>")
@login_required
def user_detail(username):
    parse_log_incrementally()
    _, day_start, month_start = time_boundaries()

    with db_connection() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if not user:
            abort(404)

        recent_rows = conn.execute(
            """
            SELECT ts, client_ip, target, download, upload
            FROM traffic
            WHERE username = ?
            ORDER BY ts DESC
            LIMIT 30
            """,
            (username,),
        ).fetchall()

        totals = conn.execute(
            """
            SELECT COALESCE(SUM(download), 0) AS dl,
                   COALESCE(SUM(upload), 0) AS ul
            FROM traffic WHERE username = ?
            """,
            (username,),
        ).fetchone()

        today_month = conn.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN ts >= ? THEN download + upload ELSE 0 END), 0) AS today,
                   COALESCE(SUM(CASE WHEN ts >= ? THEN download + upload ELSE 0 END), 0) AS month
            FROM traffic WHERE username = ?
            """,
            (day_start, month_start, username),
        ).fetchone()

        month_all = conn.execute(
            "SELECT COALESCE(SUM(download + upload), 0) FROM traffic WHERE ts >= ?",
            (month_start,),
        ).fetchone()[0]

        now_dt = datetime.now(TZ)
        cutoff30 = int(
            (now_dt - timedelta(days=29))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
        )

        day_rows = conn.execute(
            """
            SELECT local_day(ts) AS day,
                   COALESCE(SUM(download), 0) AS dl,
                   COALESCE(SUM(upload), 0) AS ul
            FROM traffic
            WHERE username = ? AND ts >= ?
            GROUP BY day
            """,
            (username, cutoff30),
        ).fetchall()

        hour_rows = conn.execute(
            """
            SELECT local_hour(ts) AS hour,
                   COALESCE(SUM(download + upload), 0) AS total
            FROM traffic
            WHERE username = ? AND ts >= ?
            GROUP BY hour
            """,
            (username, cutoff30),
        ).fetchall()

        site_rows = conn.execute(
            """
            SELECT COALESCE(NULLIF(host, ''), target) AS site,
                   COUNT(*) AS hits,
                   COALESCE(SUM(upload), 0) AS ul,
                   COALESCE(SUM(download), 0) AS dl,
                   COALESCE(SUM(upload + download), 0) AS total,
                   MAX(ts) AS last_ts
            FROM traffic
            WHERE username = ?
            GROUP BY site
            ORDER BY total DESC
            LIMIT 15
            """,
            (username,),
        ).fetchall()

        ip_rows = conn.execute(
            """
            SELECT client_ip, COUNT(*) AS hits,
                   COALESCE(SUM(upload + download), 0) AS total,
                   MAX(ts) AS last_ts
            FROM traffic
            WHERE username = ?
            GROUP BY client_ip
            ORDER BY total DESC
            LIMIT 10
            """,
            (username,),
        ).fetchall()

    recent = [
        {
            "time": datetime.fromtimestamp(row["ts"], TZ).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "ip": row["client_ip"],
            "target": row["target"],
            "download": row["download"],
            "upload": row["upload"],
        }
        for row in recent_rows
    ]

    day_map = {
        row["day"]: (int(row["dl"] or 0), int(row["ul"] or 0))
        for row in day_rows
    }
    days = []

    for offset in range(29, -1, -1):
        day_key = (now_dt.date() - timedelta(days=offset)).strftime(
            "%Y-%m-%d"
        )
        dl, ul = day_map.get(day_key, (0, 0))
        days.append(
            {
                "date": day_key,
                "download": dl,
                "upload": ul,
                "total": dl + ul,
            }
        )

    day_max = max((day["total"] for day in days), default=1) or 1

    for day in days:
        day["pct_total"] = (
            max(2, round(day["total"] / day_max * 100)) if day["total"] else 0
        )
        if day["total"]:
            day["pct_down"] = round(day["download"] / day["total"] * 100)
            day["pct_up"] = 100 - day["pct_down"]
        else:
            day["pct_down"] = day["pct_up"] = 0

    hour_map = {
        int(row["hour"]): int(row["total"] or 0) for row in hour_rows
    }
    hours = [
        {"hour": hour, "total": hour_map.get(hour, 0)} for hour in range(24)
    ]
    hour_max = max((hour["total"] for hour in hours), default=1) or 1
    peak_hour = max(hours, key=lambda hour: hour["total"])

    for hour in hours:
        hour["pct"] = (
            max(2, round(hour["total"] / hour_max * 100))
            if hour["total"]
            else 0
        )
        hour["is_peak"] = (
            hour["hour"] == peak_hour["hour"] and hour["total"] > 0
        )

    def fmt_ts(value):
        return (
            datetime.fromtimestamp(value, TZ).strftime("%m-%d %H:%M")
            if value
            else "—"
        )

    sites = [
        {
            "site": row["site"],
            "hits": row["hits"],
            "download": int(row["dl"] or 0),
            "upload": int(row["ul"] or 0),
            "total": int(row["total"] or 0),
            "last": fmt_ts(row["last_ts"]),
        }
        for row in site_rows
    ]
    ips = [
        {
            "ip": row["client_ip"],
            "hits": row["hits"],
            "total": int(row["total"] or 0),
            "last": fmt_ts(row["last_ts"]),
        }
        for row in ip_rows
    ]

    today_total = int(today_month["today"] or 0)
    month_total = int(today_month["month"] or 0)
    total_download = int(totals["dl"] or 0)
    total_upload = int(totals["ul"] or 0)
    share = round(month_total / month_all * 100, 1) if month_all else 0.0

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

<div class="kpis">
    <div class="metric">
        <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-chart"/></svg>本月流量</div>
        <div class="value">{{ month_total|bytes }}</div>
        <div class="extra">占全站 {{ share }}%</div>
    </div>
    <div class="metric">
        <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-activity"/></svg>今日流量</div>
        <div class="value">{{ today_total|bytes }}</div>
        <div class="extra">{{ username }} · 时区 {{ timezone }}</div>
    </div>
    <div class="metric">
        <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-server"/></svg>累计流量</div>
        <div class="value">{{ (total_download + total_upload)|bytes }}</div>
        <div class="extra">↓ {{ total_download|bytes }} · ↑ {{ total_upload|bytes }}</div>
    </div>
    <div class="metric">
        <div class="label"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-users"/></svg>峰值时段</div>
        <div class="value mono">{{ "%02d:00"|format(peak_hour.hour) }}</div>
        <div class="extra">{% if peak_hour.total %}近 30 天最忙小时 · {{ peak_hour.total|bytes }}{% else %}近 30 天暂无流量{% endif %}</div>
    </div>
</div>

<section class="section" style="margin-top:0">
    <div class="section-h">
        <div>
            <h2>近 30 天流量趋势</h2>
            <p class="hint">按天分层展示下载与上传；悬停查看数值。</p>
        </div>
        <div class="updown-legend">
            <span class="down"><i></i>下载</span>
            <span class="up"><i></i>上传</span>
        </div>
    </div>
    <div class="form-body">
        <div class="day-cols">
            {% for day in days %}
            <div class="day-col" title="{{ day.date }}  ↓ {{ day.download|bytes }}  ↑ {{ day.upload|bytes }}">
                <div class="amt">{{ day.total|bytes }}</div>
                {% if day.pct_total %}
                <div class="stack-bar" style="height:{{ day.pct_total }}%">
                    <i class="up" style="height:{{ day.pct_up }}%"></i>
                    <i class="down" style="height:{{ day.pct_down }}%"></i>
                </div>
                {% else %}
                <div class="stack-bar" style="height:2px"></div>
                {% endif %}
                <div class="lbl">{% if loop.index0 % 6 == 0 %}{{ day.date[5:] }}{% endif %}</div>
            </div>
            {% endfor %}
        </div>
    </div>
</section>

<section class="section">
    <div class="section-h">
        <div>
            <h2>24 小时使用分布</h2>
            <p class="hint">近 30 天各小时流量合计，红色为峰值时段。</p>
        </div>
    </div>
    <div class="form-body">
        <div class="hour-cols">
            {% for hour in hours %}
            <div class="hour-col {{ 'peak' if hour.is_peak else '' }}"
                 title="{{ "%02d:00"|format(hour.hour) }} · {{ hour.total|bytes }}">
                <div class="bar" style="height:{{ hour.pct }}%"></div>
                <div class="lbl">{% if hour.hour % 3 == 0 %}{{ hour.hour }}{% endif %}</div>
            </div>
            {% endfor %}
        </div>
    </div>
</section>

<div class="detail-grid">
    <section class="section" style="margin-top:0">
        <div class="section-h">
            <div>
                <h2>目标站点分析</h2>
                <p class="hint">按流量排序的 Top 15 目标（域名或地址）。</p>
            </div>
        </div>
        {% if sites %}
        <div class="dest-wrap">
            <table class="dest-table">
                <thead>
                <tr><th>目标</th><th class="num">次数</th><th class="num">下载</th><th class="num">上传</th><th class="num">合计</th><th>最近</th></tr>
                </thead>
                <tbody>
                {% for item in sites %}
                <tr>
                    <td class="dest-host">{{ item.site }}</td>
                    <td class="num">{{ item.hits }}</td>
                    <td class="num">{{ item.download|bytes }}</td>
                    <td class="num">{{ item.upload|bytes }}</td>
                    <td class="num">{{ item.total|bytes }}</td>
                    <td class="mono">{{ item.last }}</td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
            <div class="empty">暂无站点记录。</div>
        {% endif %}
    </section>

    <section class="section" style="margin-top:0">
        <div class="section-h">
            <div>
                <h2>客户端 IP 分析</h2>
                <p class="hint">按流量排序的 Top 10 来源。</p>
            </div>
        </div>
        {% if ips %}
        <div class="dest-wrap">
            <table class="dest-table">
                <thead>
                <tr><th>客户端 IP</th><th class="num">次数</th><th class="num">流量</th><th>最近</th></tr>
                </thead>
                <tbody>
                {% for item in ips %}
                <tr>
                    <td class="dest-host mono">{{ item.ip }}</td>
                    <td class="num">{{ item.hits }}</td>
                    <td class="num">{{ item.total|bytes }}</td>
                    <td class="mono">{{ item.last }}</td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
            <div class="empty">暂无来源记录。</div>
        {% endif %}
    </section>
</div>

<section class="section">
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

<section class="section">
    <div class="section-h">
        <div>
            <h2>用户操作</h2>
            <p class="hint">改动立即写入 3proxy 配置并生效；流量统计不会被删除。</p>
        </div>
        <a class="btn ghost" href="{{ url_for('index') }}">← 返回总览</a>
    </div>
    <div class="form-body">
        <div class="ops" style="justify-content:flex-start;margin-bottom:16px">
            <button class="btn" type="button" data-username="{{ username|e }}" onclick="copyProxy(this.dataset.username)">复制代理连接</button>
            <button class="btn" type="button" onclick="location.href='{{ url_for('export_user_csv', username=username) }}'">导出 CSV</button>
            <form method="post" action="{{ url_for('toggle_user', username=username) }}" style="display:inline">
                <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                <input type="hidden" name="next" value="/users/{{ username }}">
                <button class="btn" type="submit">{{ "启用" if not enabled else "禁用" }}</button>
            </form>
            <form method="post" action="{{ url_for('delete_user', username=username) }}" style="display:inline"
                  data-username="{{ username|e }}" onsubmit="return confirm('确定永久删除用户 '+this.dataset.username+'？\\n该用户的流量统计会保留，但账号将从 3proxy 移除。')">
                <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                <input type="hidden" name="next" value="{{ url_for('index') }}">
                <button class="btn bad" type="submit">删除用户</button>
            </form>
        </div>
        <form class="form-grid" method="post" action="{{ url_for('change_password', username=username) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <input type="hidden" name="next" value="/users/{{ username }}">
            <div class="field">
                <label>新密码</label>
                <input class="input" name="password" type="password" minlength="4" maxlength="64"
                       autocomplete="new-password" placeholder="至少 4 位" required>
            </div>
            <div class="field">
                <label>保存</label>
                <button class="btn primary" type="submit">保存密码</button>
            </div>
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
        enabled=bool(user["enabled"]),
        days=days,
        hours=hours,
        peak_hour=peak_hour,
        sites=sites,
        ips=ips,
        recent=recent,
        today_total=today_total,
        month_total=month_total,
        total_download=total_download,
        total_upload=total_upload,
        share=share,
        csrf_token=CSRF_TOKEN,
        timezone=TZ_NAME,
    )


init_db()
import_users_from_config()
upgrade_logformat()
parse_log_incrementally()

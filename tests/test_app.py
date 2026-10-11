# -*- coding: utf-8 -*-
"""3proxy Dashboard 自检测试。

这些用例覆盖曾经出过问题的地方（半行日志、图表时区分桶、鉴权/CSRF），
以及一次端到端冒烟，确保面板各页面在改动后仍能正常渲染。

运行： python -m unittest discover -s tests -v
"""
import base64
import os
import shutil
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_SRC = REPO_ROOT / "app" / "app.py"

CSRF = "a" * 64
ADMIN_USER = "admin"
ADMIN_PASS = "testpass"


def load_app(tmp, tz_name="Asia/Shanghai"):
    """把 app/app.py 当模块加载，但把运行期路径改到临时目录，避免碰 /opt、/etc。"""
    os.environ["TZ_NAME"] = tz_name
    os.environ["ADMIN_USER"] = ADMIN_USER
    os.environ["ADMIN_PASS"] = ADMIN_PASS
    os.environ["CSRF_TOKEN"] = CSRF

    src = APP_SRC.read_text(encoding="utf-8")
    tmp = Path(tmp)
    src = src.replace('APP_DIR = Path("/opt/3proxy-dashboard")', f'APP_DIR = Path(r"{tmp}")')
    src = src.replace('LOG_PATH = Path("/var/log/3proxy/access.log")',
                      f'LOG_PATH = Path(r"{tmp / "access.log"}")')
    src = src.replace('PROXY_CONFIG = Path("/etc/3proxy/3proxy.cfg")',
                      f'PROXY_CONFIG = Path(r"{tmp / "3proxy.cfg"}")')

    module = types.ModuleType("app_under_test")
    module.__dict__["__name__"] = "app_under_test"
    exec(compile(src, str(APP_SRC), "exec"), module.__dict__)
    return module


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="3p-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mod = load_app(self.tmp)
        self.auth = {"Authorization": "Basic " + base64.b64encode(
            f"{ADMIN_USER}:{ADMIN_PASS}".encode()).decode()}

    def seed_user_and_traffic(self, username="alice", ts=None):
        ts = ts if ts is not None else int(datetime.now(self.mod.TZ).timestamp())
        with self.mod.db_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(username, password, enabled, created_at)"
                " VALUES(?, 'pw', 1, ?)", (username, ts))
            conn.execute(
                "INSERT OR IGNORE INTO traffic(event_key, ts, username, client_ip, target,"
                " download, upload, host) VALUES(?, ?, ?, '1.2.3.4', '93.184.216.34:443', 100, 200,"
                " 'example.com')", (f"k-{username}-{ts}", ts, username))
        return ts


class TestLogParsing(AppTestCase):
    COMPLETE = b"L1760000000 alice 1.2.3.4:53444 93.184.216.34:443 IN:100 OUT:200 H:example.com D:2 E:0\n"
    PARTIAL = b"L1760000100 bob 5.6.7.8:53445 1.1.1.1:80 IN:500 OUT:900 H:test"

    def _rows(self):
        with self.mod.db_connection() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT username FROM traffic ORDER BY ts").fetchall()]

    def _offset(self):
        with self.mod.db_connection() as conn:
            return int(self.mod.get_state(conn, "log_offset", "0") or 0)

    def test_halfline_is_not_skipped(self):
        """半行(3proxy 未写完)不能推进偏移量，补全后必须完整入库。"""
        self.mod.LOG_PATH.write_bytes(self.COMPLETE + self.PARTIAL)
        self.mod.parse_log_incrementally()

        self.assertEqual(["alice"], [r["username"] for r in self._rows()])
        self.assertEqual(len(self.COMPLETE), self._offset(),
                         "偏移量应停在完整行末尾，而不是越过半行")

        with open(self.mod.LOG_PATH, "ab") as handle:
            handle.write(b".com D:3 E:0\n")
        self.mod.parse_log_incrementally()

        self.assertEqual(["alice", "bob"], [r["username"] for r in self._rows()],
                         "半行补全后必须入库，不能丢失整条记录")

    def test_truncated_log_is_reingested(self):
        """回归：日志被截断(copytruncate)后，同偏移量的新行不能与旧 event_key 碰撞被丢弃。"""
        self.mod.LOG_PATH.write_bytes(self.COMPLETE)
        self.mod.parse_log_incrementally()
        self.assertEqual(["alice"], [r["username"] for r in self._rows()])

        # 截断后写入更短的新行（总长度 < 旧偏移量，截断可被检测到），
        # 且新行起点与旧记录同为偏移量 0，制造 event_key 碰撞
        short = b"L1760000099 bob 1.2.3.4:53444 93.184.216.34:443 IN:1 OUT:2 H:x D:1 E:0\n"
        self.mod.LOG_PATH.write_bytes(short)
        self.mod.parse_log_incrementally()
        self.assertEqual(["alice", "bob"],
                         sorted(r["username"] for r in self._rows()),
                         "截断后同偏移量的新行必须重新入库，不能被去重静默丢弃")

    def test_parses_real_3proxy_output(self):
        """用 3proxy 二进制实测抓到的真实日志行校验正则（含启动行需跳过）。"""
        real = (
            b"L1791711502 - 0.0.0.0:18081 0.0.0.0:0 IN:0 OUT:0 H:[0.0.0.0] D:0 E:00000\n"
            b"L1791711504 tester 127.0.0.1:55092 127.0.0.1:18090 IN:543 OUT:79"
            b" H:127.0.0.1 D:2 E:00000\n"
        )
        self.mod.LOG_PATH.write_bytes(real)
        self.mod.parse_log_incrementally()
        with self.mod.db_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT username, client_ip, target, download, upload, host FROM traffic"
            ).fetchall()]
        self.assertEqual(1, len(rows), "用户为 - 的启动行必须跳过")
        self.assertEqual("tester", rows[0]["username"])
        self.assertEqual("127.0.0.1", rows[0]["client_ip"])
        self.assertEqual("127.0.0.1:18090", rows[0]["target"])
        self.assertEqual(543, rows[0]["download"])
        self.assertEqual(79, rows[0]["upload"])
        self.assertEqual("127.0.0.1", rows[0]["host"])


class TestTimezoneBuckets(AppTestCase):
    def test_buckets_follow_tz_name_not_system(self):
        """图表分桶必须按面板 TZ_NAME，而不是服务器系统时区。"""
        mod = load_app(self.tmp, tz_name="America/New_York")
        ts = 1760000000  # UTC 2025-10-09 08:13:20
        expected = datetime.fromtimestamp(ts, ZoneInfo("America/New_York"))
        with mod.db_connection() as conn:
            day, hour = conn.execute("SELECT local_day(?), local_hour(?)", (ts, ts)).fetchone()
        self.assertEqual(expected.strftime("%Y-%m-%d"), day)
        self.assertEqual(expected.strftime("%H"), hour)


class TestAuthAndCsrf(AppTestCase):
    def test_unauthenticated_is_rejected(self):
        client = self.mod.app.test_client()
        self.assertEqual(401, client.get("/").status_code)

    def test_wrong_password_is_rejected(self):
        client = self.mod.app.test_client()
        bad = {"Authorization": "Basic " + base64.b64encode(b"admin:nope").decode()}
        self.assertEqual(401, client.get("/", headers=bad).status_code)

    def test_empty_csrf_is_rejected(self):
        client = self.mod.app.test_client()
        response = client.post("/users/add", headers=self.auth,
                               data={"username": "newuser", "password": "secret1"})
        self.assertEqual(403, response.status_code)

    def test_valid_csrf_creates_user(self):
        # 提供最小 3proxy 配置，并屏蔽真实 systemctl 重启，使创建流程可离线验证
        self.mod.PROXY_CONFIG.write_text(
            "# test\nusers old:CL:pw\nsocks -p1234\n", encoding="utf-8")
        self.mod.restart_3proxy = lambda: None

        client = self.mod.app.test_client()
        response = client.post("/users/add", headers=self.auth,
                               data={"username": "newuser", "password": "secret1",
                                     "csrf_token": CSRF}, follow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        with self.mod.db_connection() as conn:
            row = conn.execute("SELECT username FROM users WHERE username='newuser'").fetchone()
        self.assertIsNotNone(row)
        # 新用户必须写回 3proxy 配置
        config = self.mod.PROXY_CONFIG.read_text(encoding="utf-8")
        self.assertIn("newuser:CL:secret1", config)
        self.assertNotIn("users old:CL:pw", config)


class TestPagesSmoke(AppTestCase):
    def test_pages_render(self):
        self.seed_user_and_traffic()
        client = self.mod.app.test_client()
        for path in ("/", "/logs", "/users/alice", "/export.csv",
                     "/users/alice/export.csv", "/logs/download", "/users/alice/proxy"):
            with self.subTest(path=path):
                self.assertEqual(200, client.get(path, headers=self.auth).status_code)

    def test_proxy_url_host_handling(self):
        """回归：IPv6 字面量主机名要保留方括号，普通域名/端口则正常取主机名。"""
        self.seed_user_and_traffic()
        client = self.mod.app.test_client()

        body = client.get("/users/alice/proxy",
                          headers=dict(self.auth, Host="[::1]:18080")).data.decode()
        self.assertEqual("socks5://alice:pw@[::1]:1234", body)

        body = client.get("/users/alice/proxy",
                          headers=dict(self.auth, Host="panel.example.com")).data.decode()
        self.assertEqual("socks5://alice:pw@panel.example.com:1234", body)

        body = client.get("/users/alice/proxy",
                          headers=dict(self.auth, Host="127.0.0.1:18080")).data.decode()
        self.assertEqual("socks5://alice:pw@127.0.0.1:1234", body)

    def test_csv_export_content(self):
        ts = self.seed_user_and_traffic()
        client = self.mod.app.test_client()
        body = client.get("/users/alice/export.csv", headers=self.auth).data.decode("utf-8")
        self.assertTrue(body.startswith("\ufeff"), "CSV 需要 BOM 以便 Excel 识别 UTF-8")
        self.assertIn("时间,用户名,客户端IP,目标,域名,下载(字节),上传(字节)", body)
        self.assertIn("alice", body)
        self.assertIn("example.com", body)

    def test_csv_export_exact_format(self):
        """锁定 CSV 逐字节格式（BOM + 表头 + 行），改造为流式输出后必须完全一致。"""
        ts = self.seed_user_and_traffic()
        client = self.mod.app.test_client()
        body = client.get("/users/alice/export.csv", headers=self.auth).data.decode("utf-8")
        when = datetime.fromtimestamp(ts, self.mod.TZ).strftime("%Y-%m-%d %H:%M:%S")
        expected = (
            "\ufeff"
            "时间,用户名,客户端IP,目标,域名,下载(字节),上传(字节)\r\n"
            f"{when},alice,1.2.3.4,93.184.216.34:443,example.com,100,200\r\n"
        )
        self.assertEqual(expected, body)

    def test_csv_export_many_rows_streams_all(self):
        """流式输出：行数完整，且按时间倒序（ORDER BY ts DESC）。"""
        base = int(datetime.now(self.mod.TZ).timestamp()) - 1000
        with self.mod.db_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO users(username, password, enabled, created_at)"
                         " VALUES('alice', 'pw', 1, ?)", (base,))
            for i in range(150):
                conn.execute(
                    "INSERT INTO traffic(event_key, ts, username, client_ip, target,"
                    " download, upload, host) VALUES(?, ?, 'alice', '1.2.3.4', 't:1', ?, 0, 'h')",
                    (f"bulk-{i}", base + i, i))
        client = self.mod.app.test_client()
        body = client.get("/users/alice/export.csv", headers=self.auth).data.decode("utf-8")
        lines = body.lstrip("\ufeff").split("\r\n")
        rows = [ln for ln in lines if ln]
        self.assertEqual(151, len(rows), "1 行表头 + 150 行数据")
        # 第一行数据应是 ts 最大的那条(download=149)
        self.assertTrue(rows[1].endswith(",149,0"), rows[1])

    def test_index_contains_sort_toggle_state(self):
        """回归：排序方向状态必须与箭头属性分开，否则方向无法切换。"""
        client = self.mod.app.test_client()
        body = client.get("/", headers=self.auth).data.decode("utf-8")
        self.assertIn("data-sortdir", body)

    def test_submit_handler_ignores_cancelled_events(self):
        """回归：取消删除确认后按钮不能卡在"处理中…"（需检查 defaultPrevented）。"""
        self.seed_user_and_traffic()
        client = self.mod.app.test_client()
        body = client.get("/", headers=self.auth).data.decode("utf-8")
        self.assertIn("if(e.defaultPrevented)return;", body)
        # 删除表单确实使用 confirm 取消事件，正是这个场景会触发上面的分支
        self.assertIn("onsubmit=\"return confirm(", body)


if __name__ == "__main__":
    unittest.main()

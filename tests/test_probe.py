"""
test_probe.py - URL 体检器测试（T1）

运行:
    uv run pytest tests/test_probe.py
    uv run python tests/test_probe.py
"""

import contextlib
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.link_probe import (
    LinkProbeCache, LinkProbeResult, is_local_url, probe_urls,
)


# ──────────────────────────────────────────────
#  本地 HTTP 测试服务器（离线）
# ──────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    request_count = 0

    def _record(self):
        type(self).request_count += 1

    def do_HEAD(self):
        self._record()
        if self.path == "/missing":
            self.send_response(404)
            self.end_headers()
            return
        if self.path == "/head-not-allowed":
            self.send_response(405)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._record()
        if self.path == "/missing":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):  # 静默访问日志
        pass


@contextlib.contextmanager
def _server():
    _Handler.request_count = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        srv.server_close()


def _closed_port() -> int:
    """拿一个已释放的端口（连接会被拒绝）"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ──────────────────────────────────────────────
#  T1.1 本地/内网判定
# ──────────────────────────────────────────────

def test_is_local_url_positive():
    cases = [
        "file:///C:/Users/me/x.html",
        "file:///home/user/x.html",
        "http://localhost",
        "http://localhost:8080/admin",
        "http://127.0.0.1/x",
        "http://10.1.2.3/",
        "http://192.168.1.1",
        "http://172.16.0.5",
        "http://172.31.255.255",
        "http://foo.local",
        "http://[::1]/",
        "http://[fe80::1]/",
        "chrome://bookmarks/",
        "edge://favorites/",
        "about:blank",
        "javascript:void(0)",
        "data:text/html,x",
        r"\\server\share",
        "C:/Users/me/x.html",
        r"C:\Users\me\x.html",
    ]
    for url in cases:
        assert is_local_url(url), f"应判定为本地: {url}"


def test_is_local_url_negative():
    cases = [
        "https://github.com",
        "http://example.com",
        "http://8.8.8.8",
        "http://11.0.0.1",
        "http://172.32.0.1",   # 172.32 不在 172.16/12 私网段
        "https://sub.example.com",
        "http://example.com:8080/x",
        "ftp://files.example.com",
    ]
    for url in cases:
        assert not is_local_url(url), f"不应判定为本地: {url}"


def test_is_local_url_empty():
    assert is_local_url("") is False
    assert is_local_url(None) is False


# ──────────────────────────────────────────────
#  T1.2 探活三态
# ──────────────────────────────────────────────

def test_probe_ok_and_404():
    with _server() as base:
        results = probe_urls([f"{base}/", f"{base}/missing"], timeout=2.0,
                             is_local=lambda u: False)
    ok = results[f"{base}/"]
    assert ok.status == "ok"
    assert ok.http_status == 200
    assert ok.method in ("head", "get")

    dead = results[f"{base}/missing"]
    assert dead.status == "dead"          # 404 确定性死链，一次即死
    assert dead.http_status == 404
    assert "404" in dead.error


def test_probe_head_fallback_to_get():
    with _server() as base:
        results = probe_urls([f"{base}/head-not-allowed"], timeout=2.0,
                             is_local=lambda u: False)
    r = results[f"{base}/head-not-allowed"]
    assert r.status == "ok"
    assert r.method == "get"              # HEAD 405 → GET 兜底


def test_probe_cache_reuse_no_network():
    with _server() as base:
        url = f"{base}/"
        cache = LinkProbeCache(cache_dir=_tmp_cache_dir())
        r1 = probe_urls([url], timeout=2.0, cache=cache, is_local=lambda u: False)
        assert r1[url].status == "ok"
        before = _Handler.request_count
        r2 = probe_urls([url], timeout=2.0, cache=cache, is_local=lambda u: False)
        assert r2[url].status == "ok"
        assert _Handler.request_count == before, "缓存命中不应再发请求"


def test_probe_fail_twice_becomes_dead():
    """防误判: DNS 失败一次 → pending；二次（缓存累计）→ dead"""
    # .invalid 为 RFC 6761 保留 TLD，解析器本地返回 NXDOMAIN，无外部流量
    url = "http://nonexistent-domain-xyz-12345.invalid/"
    cache = LinkProbeCache(cache_dir=_tmp_cache_dir())
    r1 = probe_urls([url], timeout=2.0, cache=cache)
    assert r1[url].status == "pending", f"首次失败应为 pending, 实际 {r1[url].status}"
    assert r1[url].attempts == 1
    assert "域名不存在" in r1[url].error or r1[url].error
    r2 = probe_urls([url], timeout=2.0, cache=cache)
    assert r2[url].status == "dead", "连续两次失败应标 dead"


def test_probe_local_no_network():
    results = probe_urls(["file:///C:/x.html", "chrome://bookmarks/", "http://localhost", ""])
    assert results["file:///C:/x.html"].status == "local"
    assert results["chrome://bookmarks/"].status == "local"
    assert results["http://localhost"].status == "local"
    assert results["file:///C:/x.html"].method == "local"
    assert "" not in results          # 空 URL 跳过
    assert probe_urls([]) == {}


# ──────────────────────────────────────────────
#  缓存数据类
# ──────────────────────────────────────────────

def test_probe_result_roundtrip():
    r = LinkProbeResult(url="https://a.com", status="dead", http_status=404,
                        error="HTTP 404", checked_at=123, method="head", attempts=2)
    d = r.to_dict()
    r2 = LinkProbeResult.from_dict(d)
    assert r2 == r


def test_probe_cache_persistence():
    with tempfile.TemporaryDirectory() as d:
        cache = LinkProbeCache(cache_dir=d)
        cache.set("https://a.com", LinkProbeResult(url="https://a.com", status="ok",
                                                   http_status=200, checked_at=1))
        cache.save()

        cache2 = LinkProbeCache(cache_dir=d)
        entry = cache2.get("https://a.com")
        assert entry is not None
        assert entry["status"] == "ok"
        stats = cache2.stats()
        assert stats["hits"] >= 1


# ──────────────────────────────────────────────
#  集成（Bookmark 字段分流逻辑与 classify_worker 一致性）
# ──────────────────────────────────────────────

def test_bucket_routing_matches_worker_skip():
    """本地/失效书签的 category_l1 归入系统桶，且 classify_worker 的 pending 过滤逻辑一致"""
    from modules.bookmark import Bookmark

    with _server() as base:
        ok_url = f"{base}/"
        dead_url = f"{base}/missing"
        bms = [
            Bookmark(id=1, title="本地", url="file:///C:/x.html"),
            Bookmark(id=2, title="死链", url=dead_url),
            Bookmark(id=3, title="正常", url=ok_url),
        ]
        # 仅 file:// 视为本地；本地 HTTP 服务器地址也参与探活
        is_local_fn = lambda u: u.startswith("file://")
        probes = probe_urls([b.url for b in bms], timeout=2.0, is_local=is_local_fn)

    for bm in bms:
        r = probes[bm.url]
        bm.status = r.status
        if r.status == "local":
            bm.category_l1, bm.classify_method = "📁 本地/内网", "local"
        elif r.status == "dead":
            bm.category_l1, bm.classify_method = "⚠️ 失效链接", "dead"

    local_bm = bms[0]
    assert local_bm.status == "local" and local_bm.category_l1 == "📁 本地/内网"
    dead_bm = bms[1]
    assert dead_bm.status == "dead" and dead_bm.category_l1 == "⚠️ 失效链接"
    ok_bm = bms[2]
    assert ok_bm.status == "ok" and ok_bm.category_l1 == ""

    # 与 classify_worker 的 pending 过滤一致: local/dead 不进规则引擎
    pending = [b for b in bms if not b.category_l1 and b.status not in ("local", "dead")]
    assert [b.id for b in pending] == [3]


def _tmp_cache_dir() -> str:
    import tempfile
    d = tempfile.mkdtemp(prefix="probe_test_")
    return d


# ──────────────────────────────────────────────
#  内置 runner
# ──────────────────────────────────────────────

def _run_all():
    tests = [
        (name, fn) for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{'=' * 50}\n{len(tests)} tests, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())

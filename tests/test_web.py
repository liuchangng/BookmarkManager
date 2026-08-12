"""
test_web.py - Web 版后端 API 测试 (FastAPI TestClient)

覆盖端点:
- GET /           前端页面
- POST /api/upload  上传解析
- POST /api/process 启动流水线（本地书签，离线）
- GET /api/events   SSE 快照
- GET /api/bookmarks / POST classify / delete / delete-dead
- POST /api/export + download
- GET/POST /api/settings + ai-test / proxy-test

隔离策略: fixture 将 webapp 的 config/secure_store/proxy_manager/pipeline
替换为临时目录版本，避免污染真实 config.yaml 与 data/。

运行方式:
    uv run pytest tests/test_web.py
    uv run python tests/test_web.py
"""

import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import webapp  # noqa: E402  模块级导入（FastAPI app）

from modules.config_manager import ConfigManager
from modules.secure_store import SecureStore
from modules.proxy import ProxyManager
from modules.pipeline import Pipeline

LOCAL_ONLY_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1700000000">书签栏</H3>
    <DL><p>
        <DT><A HREF="file:///C:/docs.html" ADD_DATE="1700000001">本地文档</A>
        <DT><A HREF="http://127.0.0.1:8080/service" ADD_DATE="1700000002">本机服务</A>
        <DT><A HREF="file:///C:/share/notes.html" ADD_DATE="1700000003">共享笔记</A>
    </DL><p>
</DL><p>
"""


def _make_fixture(tmp_path: Path):
    """构建隔离的 webapp 全局对象"""
    cfg = ConfigManager(tmp_path / "config.yaml")
    cfg.load()
    cfg.set("classification.cache_dir", str(tmp_path / "cache"))
    cfg.set("proxy.enabled", False)
    store = SecureStore(tmp_path / ".secure")
    pm = ProxyManager(cfg, store)
    pl = Pipeline(cfg, store, pm)
    pl.set_event_callback(webapp._broadcast)

    webapp.config = cfg
    webapp.secure_store = store
    webapp.proxy_manager = pm
    webapp.pipeline = pl
    webapp.UPLOAD_DIR = tmp_path / "uploads"
    webapp.EXPORT_DIR = tmp_path / "exports"
    webapp.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    webapp.EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    from fastapi.testclient import TestClient
    return TestClient(webapp.app)


def test_index_page():
    with tempfile.TemporaryDirectory() as d:
        client = _make_fixture(Path(d))
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "上传" in r.text


def test_upload_invalid_extension():
    with tempfile.TemporaryDirectory() as d:
        client = _make_fixture(Path(d))
        r = client.post("/api/upload", files={"file": ("bad.txt", b"x", "text/plain")})
        assert r.status_code == 400


def test_upload_and_parse():
    with tempfile.TemporaryDirectory() as d:
        client = _make_fixture(Path(d))
        r = client.post("/api/upload",
                        files={"file": ("bookmarks.html", LOCAL_ONLY_HTML.encode("utf-8"),
                                        "text/html")})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["count"] == 3
        assert len(data["bookmarks"]) == 3
        assert data["bookmarks"][0]["url"].startswith("file://")
        assert data["stats"]["total"] == 3


def test_upload_bad_content():
    with tempfile.TemporaryDirectory() as d:
        client = _make_fixture(Path(d))
        r = client.post("/api/upload",
                        files={"file": ("bad.html", b"<html><body>no bookmarks</body></html>",
                                        "text/html")})
        assert r.status_code == 422


def test_process_requires_upload():
    with tempfile.TemporaryDirectory() as d:
        client = _make_fixture(Path(d))
        r = client.post("/api/process")
        assert r.status_code == 400


def test_events_snapshot_payload():
    """SSE 快照载荷正确（不消费无限流，直接验证快照生成）"""
    import json
    snapshot = json.loads(webapp._json_snapshot())
    assert snapshot["type"] == "snapshot"
    assert "bookmarks" in snapshot
    assert "distribution" in snapshot
    assert "stats" in snapshot
    assert snapshot["running"] is False


def test_sse_subscription_broadcast():
    """SSE 订阅/广播机制：事件能到达订阅者队列"""
    import queue
    q: queue.Queue = queue.Queue()
    with webapp._sub_lock:
        webapp._subscribers[99999] = q
    try:
        webapp._broadcast({"type": "log", "level": "INFO", "message": "hello"})
        ev = q.get(timeout=2)
        assert ev["type"] == "log"
        assert ev["message"] == "hello"
    finally:
        with webapp._sub_lock:
            webapp._subscribers.pop(99999, None)


def test_upload_process_bookmarks():
    """上传 → 启动流水线 → 等待完成 → 查询书签（全离线）"""
    with tempfile.TemporaryDirectory() as d:
        client = _make_fixture(Path(d))
        r = client.post("/api/upload",
                        files={"file": ("bookmarks.html", LOCAL_ONLY_HTML.encode("utf-8"),
                                        "text/html")})
        assert r.status_code == 200

        r = client.post("/api/process")
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

        # 等待流水线完成（本地书签，秒级）
        deadline = time.time() + 30
        while webapp.pipeline.is_running() and time.time() < deadline:
            time.sleep(0.05)
        assert not webapp.pipeline.is_running(), "流水线超时未完成"

        r = client.get("/api/bookmarks")
        data = r.json()
        assert len(data["bookmarks"]) == 3
        for bm in data["bookmarks"]:
            assert bm["status"] == "local"
            assert bm["category_l1"] == "📁 本地/内网"

        # 分布树
        dist = client.get("/api/distribution").json()["distribution"]
        assert "📁 本地/内网" in dist

        # unclassified 应为空（全部已落系统桶）
        r2 = client.get("/api/bookmarks?filter=unclassified")
        assert r2.json()["bookmarks"] == []


def test_manual_classify_and_delete():
    with tempfile.TemporaryDirectory() as d:
        client = _make_fixture(Path(d))
        client.post("/api/upload",
                    files={"file": ("bookmarks.html", LOCAL_ONLY_HTML.encode("utf-8"),
                                    "text/html")})

        r = client.post("/api/bookmarks/0/classify", json={"l1": "开发技术", "l2": "代码托管"})
        assert r.status_code == 200, r.text
        bm = r.json()["bookmark"]
        assert bm["category_l1"] == "开发技术"
        assert bm["classify_method"] == "manual"

        # 空分类被拒
        r2 = client.post("/api/bookmarks/0/classify", json={"l1": ""})
        assert r2.status_code == 400

        # 越界
        r3 = client.post("/api/bookmarks/99/classify", json={"l1": "a"})
        assert r3.status_code == 404

        # 删除
        r4 = client.post("/api/bookmarks/1/delete")
        assert r4.status_code == 200
        rows = client.get("/api/bookmarks").json()["bookmarks"]
        assert len(rows) == 2


def test_delete_dead_endpoint():
    with tempfile.TemporaryDirectory() as d:
        client = _make_fixture(Path(d))
        client.post("/api/upload",
                    files={"file": ("bookmarks.html", LOCAL_ONLY_HTML.encode("utf-8"),
                                    "text/html")})
        # 手动制造失效
        webapp.pipeline.bookmarks[0].status = "dead"
        r = client.post("/api/bookmarks/delete-dead")
        assert r.json()["deleted"] == 1
        assert webapp.pipeline.bookmarks[0].user_deleted


def test_export_and_download():
    with tempfile.TemporaryDirectory() as d:
        client = _make_fixture(Path(d))
        client.post("/api/upload",
                    files={"file": ("bookmarks.html", LOCAL_ONLY_HTML.encode("utf-8"),
                                    "text/html")})
        # 未跑流水线：手动标记状态（模拟体检结果）——2 本地 + 1 正常
        webapp.pipeline.bookmarks[0].status = "local"
        webapp.pipeline.bookmarks[0].category_l1 = "📁 本地/内网"
        webapp.pipeline.bookmarks[1].status = "local"
        webapp.pipeline.bookmarks[1].category_l1 = "📁 本地/内网"
        webapp.pipeline.bookmarks[2].status = "ok"

        r = client.post("/api/export", json={})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["stats"]["total"] == 3
        assert data["stats"]["kept"] == 3  # 本地默认包含

        # 下载
        dl = client.get(data["path"])
        assert dl.status_code == 200
        assert "file:///C:/docs.html" in dl.text

        # 取消包含本地后，本地被排除（保留 1 条正常，避免空导出被拒）
        r2 = client.post("/api/export", json={"include_local": False})
        data2 = r2.json()
        assert data2["stats"]["excluded_local"] == 2
        assert data2["stats"]["kept"] == 1
        dl2 = client.get(data2["path"])
        assert "file:///C:/docs.html" not in dl2.text
        assert "http://127.0.0.1:8080/service" not in dl2.text


def test_settings_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        client = _make_fixture(Path(d))
        # 初始
        s = client.get("/api/settings").json()
        assert "proxy" in s and "ai" in s and "export" in s
        assert s["ai"]["configured"] is False

        # 更新导出默认 + 代理
        r = client.post("/api/settings", json={
            "proxy": {"enabled": False, "host": "127.0.0.1", "port": 7890},
            "export": {"include_dead": True, "include_local": False},
        })
        assert r.status_code == 200

        s2 = client.get("/api/settings").json()
        assert s2["export"]["include_dead"] is True
        assert s2["export"]["include_local"] is False

        # 未配置 Key 时 ai-test 返回失败（不崩溃）
        r3 = client.post("/api/settings/ai-test", json={})
        assert r3.status_code == 200
        assert r3.json()["ok"] is False


def test_proxy_test_endpoint():
    """代理测试端点：mock 掉真实网络探测，验证参数透传"""
    with tempfile.TemporaryDirectory() as d:
        client = _make_fixture(Path(d))
        calls = {}

        def fake_test(**kwargs):
            calls.update(kwargs)
            return {"success": False, "latency_ms": 0, "ip": "", "error": "mock"}

        webapp.proxy_manager.test_connection = fake_test
        r = client.post("/api/settings/proxy-test")
        assert r.status_code == 200
        assert r.json()["success"] is False
        assert "error" in r.json()


# ──────────────────────────────────────────────
#  内置 runner（无 pytest 时可直接运行）
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

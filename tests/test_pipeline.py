"""
test_pipeline.py - 纯 Python 流水线编排测试（Web 版核心）

验证 Pipeline 类:
- parse_file 解析去重
- run() 全流程（离线：仅本地/内网书签，零网络）
- 审核操作: set_classification / delete_bookmark / delete_dead
- 查询: get_distribution / bookmarks_to_dict
- 模块级工具: apply_filter / status_text

运行方式:
    uv run pytest tests/test_pipeline.py
    uv run python tests/test_pipeline.py
"""

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.config_manager import ConfigManager
from modules.secure_store import SecureStore
from modules.proxy import ProxyManager
from modules.pipeline import Pipeline, apply_filter, status_text

LOCAL_ONLY_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1700000000">书签栏</H3>
    <DL><p>
        <DT><A HREF="file:///C:/docs.html" ADD_DATE="1700000001">本地文档</A>
        <DT><A HREF="http://127.0.0.1:8080/service" ADD_DATE="1700000002">本机服务</A>
        <DT><A HREF="file:///C:/docs.html" ADD_DATE="1700000003">重复本地文档</A>
        <DT><A HREF="file:///C:/share/notes.html" ADD_DATE="1700000004">共享笔记</A>
    </DL><p>
</DL><p>
"""


def _make_pipeline(tmp_path: Path):
    cfg = ConfigManager(tmp_path / "config.yaml")
    cfg.load()
    cfg.set("classification.cache_dir", str(tmp_path / "cache"))
    cfg.set("proxy.enabled", False)
    store = SecureStore(tmp_path / ".secure")
    pm = ProxyManager(cfg, store)
    pl = Pipeline(cfg, store, pm)
    return pl, cfg


def _write_sample(tmp_path: Path, html: str = LOCAL_ONLY_HTML) -> Path:
    p = tmp_path / "bookmarks.html"
    p.write_text(html, encoding="utf-8")
    return p


def test_parse_file_and_dedup(tmp_path):
    pl, _ = _make_pipeline(tmp_path)
    src = _write_sample(tmp_path)
    bms = pl.parse_file(str(src))
    # 4 条原始，1 条重复 → 去重后 3 条
    assert len(bms) == 3
    assert pl.source_file == str(src)
    assert len(pl.bookmarks) == 3


def test_run_full_pipeline_offline(tmp_path):
    """全流程离线运行：本地书签零网络，最终全部落系统桶"""
    pl, _ = _make_pipeline(tmp_path)
    pl.parse_file(str(_write_sample(tmp_path)))

    events = []
    pl.set_event_callback(events.append)
    pl.run()  # 同步执行（线程中也是调这个）

    types = [e["type"] for e in events]
    assert "done" in types, f"未完成: {types}"
    assert "error" not in types, f"发生错误: {[e for e in events if e['type'] == 'error']}"

    stats = pl._collect_stats()
    assert stats["total"] == 3
    assert stats["active"] == 3
    assert stats["local"] == 3

    # 所有书签状态为 local，落 📁 本地/内网 系统桶
    for bm in pl.bookmarks:
        assert bm.status == "local"
        assert bm.category_l1 == "📁 本地/内网"
        assert bm.classify_method == "local"


def test_manual_classification_and_delete(tmp_path):
    pl, _ = _make_pipeline(tmp_path)
    pl.parse_file(str(_write_sample(tmp_path)))
    bm = pl.bookmarks[0]

    # 手动分类
    assert pl.set_classification(bm.url, "开发技术", "代码托管")
    assert bm.category_l1 == "开发技术"
    assert bm.category_l2 == "代码托管"
    assert bm.classify_method == "manual"
    assert bm.user_confirmed

    # 不存在的 URL 返回 False
    assert not pl.set_classification("https://nope.example.com", "a", "b")

    # 标记删除
    assert pl.delete_bookmark(bm.url)
    assert bm.user_deleted


def test_delete_dead(tmp_path):
    pl, _ = _make_pipeline(tmp_path)
    pl.parse_file(str(_write_sample(tmp_path)))
    # 手动制造 2 条失效
    pl.bookmarks[0].status = "dead"
    pl.bookmarks[1].status = "dead"
    assert pl.delete_dead() == 2
    assert all(b.user_deleted for b in pl.bookmarks[:2])
    # 再次调用无失效可删
    assert pl.delete_dead() == 0


def test_get_distribution_and_bookmarks_to_dict(tmp_path):
    pl, _ = _make_pipeline(tmp_path)
    pl.parse_file(str(_write_sample(tmp_path)))

    pl.set_classification(pl.bookmarks[0].url, "开发技术", "代码托管")
    pl.delete_bookmark(pl.bookmarks[1].url)

    dist = pl.get_distribution()
    # 已删除的不进分布；未分类的进兜底桶
    assert dist == {
        "开发技术": {"代码托管": 1},
        "📁 其他": {"未分类": 1},
    }

    rows = pl.bookmarks_to_dict()
    assert len(rows) == 2  # 排除已删除
    assert rows[0]["category_l1"] == "开发技术"
    assert rows[0]["status"] == pl.bookmarks[0].status
    assert "page_summary" in rows[0]

    # filter 参数
    dead_rows = pl.bookmarks_to_dict(filter_status="dead")
    local_rows = pl.bookmarks_to_dict(filter_status="local")
    assert all(r["status"] == "dead" for r in dead_rows)
    assert all(r["status"] == "local" for r in local_rows)


def test_run_requires_bookmarks(tmp_path):
    pl, _ = _make_pipeline(tmp_path)
    events = []
    pl.set_event_callback(events.append)
    pl.run()
    assert any(e["type"] == "error" for e in events)


def test_apply_filter_module(tmp_path):
    pl, _ = _make_pipeline(tmp_path)
    pl.parse_file(str(_write_sample(tmp_path)))
    bms = pl.bookmarks

    bms[0].status = "dead"
    assert len(apply_filter(bms, "全部")) == 3
    assert len(apply_filter(bms, "失效链接")) == 1
    assert apply_filter(bms, "失效链接")[0] is bms[0]
    assert len(apply_filter(bms, "已抓取", fetch_results={bms[0].url: "x"})) == 1
    assert len(apply_filter(bms, "已分类")) == 0

    bms[1].user_deleted = True
    assert len(apply_filter(bms, "已删除")) == 1


def test_status_text_module():
    from modules.bookmark import Bookmark

    def mk(status: str):
        return Bookmark(id=0, title="t", url="https://a.com", folder="f",
                        root_folder="f", status=status)

    assert status_text(mk("ok")) == "✅正常"
    assert status_text(mk("dead")) == "⚠️失效"
    assert status_text(mk("local")) == "📁本地"
    assert status_text(mk("pending")) == "🕐待定"
    assert status_text(mk("ok"), fetched=True) == "✅正常·已抓"


def test_fetch_many_parallel():
    """fetch_many_parallel: 结果完整、进度回调次数正确、真正并行加速"""
    import time
    from modules.fetcher import WebFetcher, FetchResult

    with tempfile.TemporaryDirectory() as d:
        fetcher = WebFetcher(
            config={
                "fetch": {"timeout": 5, "concurrency": 6, "max_retries": 0},
                "classification": {"cache_dir": d},
            },
            proxy_adapter=None,
        )

        def fake_fetch(url):
            time.sleep(0.15)
            r = FetchResult(url, success=True)
            r.title = f"title-{url}"
            return r

        fetcher.fetch = fake_fetch
        urls = [f"https://x{i}.com/" for i in range(30)]

        done_list = []
        t0 = time.time()
        results = fetcher.fetch_many_parallel(
            urls, progress_cb=lambda n, t, r: done_list.append((n, t, r.url))
        )
        elapsed = time.time() - t0

        assert len(results) == 30, "结果数量不完整"
        assert len(done_list) == 30, "进度回调次数不足"
        assert done_list[-1][0] == 30 and done_list[-1][1] == 30
        # 30 × 0.15s 串行需 4.5s；6 并发应 < 2s
        assert elapsed < 2.0, f"并行未生效: {elapsed:.2f}s"


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
            if "tmp_path" in fn.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"  PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{'=' * 50}\n{len(tests)} tests, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())

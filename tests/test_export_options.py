"""
test_export_options.py - T5.3 导出包含选项测试

验证 BookmarkHTMLBuilder / build_and_save 按状态过滤:
- 默认: 排除失效(dead)、包含本地/内网(local)
- 勾选后可包含失效; 取消勾选可排除本地
- stats 计数正确; 生成结果 validate 通过

运行方式:
    uv run pytest tests/test_export_options.py
    uv run python tests/test_export_options.py
"""

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.bookmark import Bookmark
from modules.html_builder import (
    BookmarkHTMLBuilder, build_and_save, validate_html,
)


def _mk(url: str, title: str = "", status: str = "ok") -> Bookmark:
    return Bookmark(
        id=0, title=title or url, url=url, folder="书签栏", root_folder="书签栏",
        category_l1="开发技术", category_l2="代码托管",
        status=status,
    )


SAMPLE = [
    _mk("https://ok.example.com", "正常站", "ok"),
    _mk("https://dead.example.com", "死链站", "dead"),
    _mk("file:///C:/local.html", "本地文件", "local"),
    _mk("https://pending.example.com", "待定站", "pending"),
]


def _count(html: str, url: str) -> int:
    return html.count(f'"{url}"')


def test_default_excludes_dead_includes_local():
    """默认: 排除失效、包含本地/内网"""
    html = BookmarkHTMLBuilder(SAMPLE).build()
    assert _count(html, "https://ok.example.com") == 1
    assert _count(html, "https://dead.example.com") == 0
    assert _count(html, "file:///C:/local.html") == 1
    assert _count(html, "https://pending.example.com") == 1
    assert validate_html(html)["valid"]


def test_include_dead_flag():
    """勾选包含失效后，失效链接也写入"""
    html = BookmarkHTMLBuilder(SAMPLE, include_dead=True).build()
    assert _count(html, "https://dead.example.com") == 1
    assert _count(html, "https://ok.example.com") == 1


def test_exclude_local_flag():
    """取消勾选本地后，本地书签被排除"""
    html = BookmarkHTMLBuilder(SAMPLE, include_local=False).build()
    assert _count(html, "file:///C:/local.html") == 0
    assert _count(html, "https://ok.example.com") == 1


def test_stats_counts_excluded():
    """stats 记录排除数量"""
    builder = BookmarkHTMLBuilder(SAMPLE)
    builder.build()
    s = builder.stats
    assert s["total"] == 4
    assert s["kept"] == 3          # dead 被排除
    assert s["excluded_dead"] == 1
    assert s["excluded_local"] == 0

    builder2 = BookmarkHTMLBuilder(SAMPLE, include_local=False)
    builder2.build()
    assert builder2.stats["excluded_local"] == 1
    assert builder2.stats["excluded_dead"] == 1
    assert builder2.stats["kept"] == 2


def test_deleted_bookmarks_always_excluded():
    """user_deleted 优先于状态过滤（原有语义保留）"""
    bms = [SAMPLE[0], _mk("https://del.example.com", "已删", "ok")]
    bms[1].user_deleted = True
    html = BookmarkHTMLBuilder(bms).build()
    assert _count(html, "https://del.example.com") == 0
    assert _count(html, "https://ok.example.com") == 1


def test_build_and_save_passthrough():
    """build_and_save 转发 include 参数"""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.html"
        r = build_and_save(SAMPLE, str(out))  # 默认
        assert r["success"], r["validation"]
        html = Path(out).read_text(encoding="utf-8")
        assert _count(html, "https://dead.example.com") == 0
        assert _count(html, "file:///C:/local.html") == 1

        out2 = Path(d) / "out2.html"
        r2 = build_and_save(SAMPLE, str(out2), include_dead=True, include_local=False)
        assert r2["success"], r2["validation"]
        html2 = Path(out2).read_text(encoding="utf-8")
        assert _count(html2, "https://dead.example.com") == 1
        assert _count(html2, "file:///C:/local.html") == 0


def test_config_defaults_match_builder():
    """config.yaml 默认值与 builder 默认值一致（决策 #1/#2）"""
    import yaml
    cfg = yaml.safe_load(open(PROJECT_ROOT / "config.yaml", encoding="utf-8"))
    assert cfg["output"]["export_include_dead"] is False
    assert cfg["output"]["export_include_local"] is True


def test_dead_filter_logic():
    """T5.2: 「失效链接」筛选只返回 status==dead 的书签"""
    from modules.pipeline import apply_filter

    filtered = apply_filter(SAMPLE, "失效链接", fetch_results={})
    assert [b.url for b in filtered] == ["https://dead.example.com"]

    # 其他筛选不受影响
    assert len(apply_filter(SAMPLE, "全部")) == 4
    assert apply_filter(SAMPLE, "已删除") == []


def test_status_column_text():
    """T5.1: 状态列文案（探活三态 + 抓取标记 + pending 兜底）"""
    from modules.pipeline import status_text

    assert status_text(_mk("https://a.com", "", "ok")) == "✅正常"
    assert status_text(_mk("https://a.com", "", "dead")) == "⚠️失效"
    assert status_text(_mk("https://a.com", "", "local")) == "📁本地"
    assert status_text(_mk("https://a.com", "", "pending")) == "🕐待定"
    # 抓取标记
    assert status_text(_mk("https://a.com", "", "ok"), fetched=True) == "✅正常·已抓"


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

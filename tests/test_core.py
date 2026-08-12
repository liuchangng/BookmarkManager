"""
test_core.py - 核心链路测试（手动导入 → 解析 → 两级分类 → HTML 生成）

运行方式:
    uv run pytest tests/test_core.py          # pytest
    uv run python tests/test_core.py          # 直接运行（内置 runner）
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# 保证项目根目录在 sys.path 中（直接运行时）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.bookmark import Bookmark
from modules.parser import BookmarkParser
from modules.classifier import Classifier
from modules.html_builder import (
    BookmarkHTMLBuilder, build_and_save, validate_html,
)

CONFIG_PATH = PROJECT_ROOT / "config.yaml"

SAMPLE_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1700000000" LAST_MODIFIED="1700000001">书签栏</H3>
    <DL><p>
        <DT><H3 ADD_DATE="1700000002">开发</H3>
        <DL><p>
            <DT><H3 ADD_DATE="1700000003">代码托管</H3>
            <DL><p>
                <DT><A HREF="https://github.com" ADD_DATE="1700000004">GitHub &amp; Friends</A>
                <DT><A HREF="https://gist.github.com" ADD_DATE="1700000005">Gist &#39;Snippets&#39;</A>
            </DL><p>
            <DT><H3 ADD_DATE="1700000006">文档教程</H3>
            <DL><p>
                <DT><A HREF="https://developer.mozilla.org" ADD_DATE="1700000007">MDN Web Docs</A>
            </DL><p>
        </DL><p>
        <DT><A HREF="https://example.com" ADD_DATE="1700000008">根级书签</A>
        <DT><A HREF="javascript:void(0)" ADD_DATE="1700000009">应被忽略</A>
    </DL><p>
</DL><p>
"""


def _make_json_bookmarks():
    return {
        "roots": {
            "bookmark_bar": {
                "name": "书签栏",
                "children": [
                    {
                        "type": "folder",
                        "name": "娱乐",
                        "children": [
                            {"type": "url", "name": "哔哩哔哩", "url": "https://bilibili.com",
                             "date_added": "13300000000000000"},
                            {"type": "url", "name": "油管", "url": "https://youtube.com",
                             "date_added": "13300000000000001"},
                        ],
                    },
                    {"type": "url", "name": "博客", "url": "https://example.org",
                     "date_added": "13300000000000002"},
                    {"type": "url", "name": "空链接", "url": "javascript:void(0)",
                     "date_added": "0"},
                ],
            },
            "other": {"name": "其他书签", "children": []},
        },
        "version": 1,
    }


# ──────────────────────────────────────────────
#  Parser
# ──────────────────────────────────────────────

def test_parse_html_nested_folders_and_entities():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "bookmarks.html"
        path.write_text(SAMPLE_HTML, encoding="utf-8")
        bms = BookmarkParser().parse(str(path))

    assert len(bms) == 4, f"应解析出 4 条书签, 实际 {len(bms)}"
    by_url = {b.url: b for b in bms}

    # javascript: 被忽略
    assert "javascript:void(0)" not in by_url

    # 实体解码
    assert by_url["https://github.com"].title == "GitHub & Friends"
    assert by_url["https://gist.github.com"].title == "Gist 'Snippets'"

    # 文件夹层级
    gh = by_url["https://github.com"]
    assert gh.folder == "书签栏 / 开发 / 代码托管"
    assert gh.root_folder == "书签栏"

    # 根级书签 folder 只有根目录
    assert by_url["https://example.com"].folder == "书签栏"
    assert by_url["https://example.com"].root_folder == "书签栏"

    # 日期解析（微秒 → 秒）
    assert by_url["https://github.com"].add_date_raw == "1700000004"


def test_parse_json_with_bom_and_folders():
    data = _make_json_bookmarks()
    raw = "\ufeff" + json.dumps(data, ensure_ascii=False)  # 带 BOM

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "Bookmarks"
        path.write_text(raw, encoding="utf-8")
        bms = BookmarkParser().parse(str(path))

    assert len(bms) == 3, f"应解析出 3 条书签, 实际 {len(bms)}"
    by_url = {b.url: b for b in bms}

    assert by_url["https://bilibili.com"].folder == "书签栏 / 娱乐"
    assert by_url["https://bilibili.com"].root_folder == "书签栏"
    # FILETIME(1601起) → Unix 秒: (13300000000000000 - 11644473600000000) // 1e6
    assert by_url["https://bilibili.com"].add_date_raw == "1655526400"
    assert by_url["https://example.org"].folder == "书签栏"


def test_parse_empty_file_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "empty.html"
        path.write_text("<html><body>no bookmarks</body></html>", encoding="utf-8")
        bms = BookmarkParser().parse(str(path))
    assert bms == []


def test_merge_duplicates():
    b1 = Bookmark(id=1, title="A", url="https://a.com/", folder="书签栏")
    b2 = Bookmark(id=2, title="A2", url="https://a.com", folder="其他书签")
    b3 = Bookmark(id=3, title="B", url="https://b.com")
    merged = BookmarkParser().merge_duplicates([b1, b2, b3])
    assert len(merged) == 2
    assert merged[0].folder == "书签栏 | 其他书签"  # 重复书签合并来源文件夹


# ──────────────────────────────────────────────
#  Classifier
# ──────────────────────────────────────────────

def _mk(url, title="", folder=""):
    return Bookmark(id=0, title=title or url, url=url, folder=folder,
                    domain=BookmarkParser._extract_domain(url))


def test_classifier_loads_sub_keywords():
    clf = Classifier(str(CONFIG_PATH))
    rules = clf.get_all_rules()
    sub_rules = [r for r in rules if r["description"].startswith("sub:")]
    assert sub_rules, "config.yaml 应包含 sub_keywords 生成的小类规则"
    # 小类关键词规则优先级低于大类域名规则、高于大类关键词规则（数值越小越先匹配）
    github = [r for r in sub_rules if r["pattern"] == "github"]
    assert github and github[0]["l2"] == "代码托管"


def test_classify_domain_and_subdomain():
    clf = Classifier(str(CONFIG_PATH))
    bms = clf.classify([
        _mk("https://github.com/"),
        _mk("https://gist.github.com/"),   # 子域名 → 主域规则命中
        _mk("https://www.taobao.com/"),
    ])
    by_url = {b.url: b for b in bms}
    assert by_url["https://github.com/"].category_l1 == "开发技术"
    assert by_url["https://github.com/"].category_l2 == "代码托管"
    assert by_url["https://gist.github.com/"].category_l1 == "开发技术"
    assert by_url["https://www.taobao.com/"].category_l1 == "购物消费"
    assert by_url["https://www.taobao.com/"].category_l2 == "综合电商"


def test_classify_keyword_to_subcategory():
    """小类关键词应把书签分到更精确的二级小类"""
    clf = Classifier(str(CONFIG_PATH))
    bms = clf.classify([
        _mk("https://www.mozilla.org/", title="MDN Web Docs"),
        _mk("https://www.youtube.com/", title="YouTube"),
    ])
    by_url = {b.url: b for b in bms}
    assert by_url["https://www.mozilla.org/"].category_l2 == "文档教程"
    assert by_url["https://www.youtube.com/"].category_l2 == "在线视频"


def test_classify_unmatched_falls_to_other():
    clf = Classifier(str(CONFIG_PATH))
    bms = clf.classify([_mk("https://totally-random-unknown-site-xyz.com/")])
    assert bms[0].category_l1 == "其他"
    assert bms[0].category_l2 == "待分类"
    assert bms[0].classify_method == "unmatched"


def test_new_categories_reference_and_home():
    """T4: DMOZ 补类——参考工具 / 居家生活 及 sub_keywords 命中"""
    clf = Classifier(str(CONFIG_PATH))
    bms = clf.classify([
        _mk("https://dict.com/", "在线词典"),
        _mk("https://www.ikea.com/cn/zh/", "宜家中国"),
        _mk("https://www.weather.com.cn/", "中国天气网"),
        _mk("https://www.xiachufang.com/", "下厨房"),
    ])
    by_url = {b.url: b for b in bms}

    assert by_url["https://dict.com/"].category_l1 == "参考工具"
    assert by_url["https://dict.com/"].category_l2 == "字典/翻译"

    assert by_url["https://www.ikea.com/cn/zh/"].category_l1 == "居家生活"
    assert by_url["https://www.ikea.com/cn/zh/"].category_l2 == "装修/家居"

    assert by_url["https://www.weather.com.cn/"].category_l1 == "参考工具"
    assert by_url["https://www.weather.com.cn/"].category_l2 == "天气/日历"

    assert by_url["https://www.xiachufang.com/"].category_l1 == "居家生活"
    assert by_url["https://www.xiachufang.com/"].category_l2 == "食谱/美食"


def test_category_list_contains_new_categories():
    """T4: get_category_list 输出包含新类"""
    clf = Classifier(str(CONFIG_PATH))
    l1s = {c["l1"] for c in clf.get_category_list()}
    assert "参考工具" in l1s
    assert "居家生活" in l1s


def test_explicit_rules_override_categories():
    cfg = {
        "categories": [
            {"name": "开发", "keywords": ["github"], "sub_categories": ["代码"]},
        ],
        "classify_rules": [
            {"l1": "特殊", "l2": "私有", "type": "domain", "pattern": "github.com"},
        ],
    }
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "cfg.yaml"
        path.write_text(__import__("yaml").safe_dump(cfg, allow_unicode=True),
                        encoding="utf-8")
        clf = Classifier(str(path))
    bms = clf.classify([_mk("https://github.com/")])
    assert bms[0].category_l1 == "特殊"
    assert bms[0].category_l2 == "私有"


# ──────────────────────────────────────────────
#  HTML Builder
# ──────────────────────────────────────────────

def test_builder_two_level_structure():
    bms = [
        Bookmark(id=1, title="GitHub", url="https://github.com", folder="书签栏",
                 root_folder="书签栏", category_l1="开发技术", category_l2="代码托管",
                 classify_method="rule", confidence=0.95),
        Bookmark(id=2, title="MDN", url="https://developer.mozilla.org", folder="书签栏",
                 root_folder="书签栏", category_l1="开发技术", category_l2="文档教程",
                 classify_method="rule", confidence=0.95),
        Bookmark(id=3, title="未分类站", url="https://unknown-xyz.com", folder="书签栏",
                 root_folder="书签栏", category_l1="其他", category_l2="待分类",
                 classify_method="unmatched"),
    ]
    html = BookmarkHTMLBuilder(bms).build()

    assert ">开发技术</H3>" in html
    assert ">代码托管</H3>" in html
    assert ">文档教程</H3>" in html
    # 「其他」也保持两级：📁 其他 / 待分类
    assert ">📁 其他</H3>" in html
    assert ">待分类</H3>" in html

    validation = validate_html(html)
    assert validation["valid"], validation["errors"]
    assert validation["stats"]["bookmarks"] == 3


def test_builder_skips_empty_root():
    bms = [
        Bookmark(id=1, title="GitHub", url="https://github.com", folder="书签栏",
                 root_folder="书签栏", category_l1="开发技术", category_l2="代码托管"),
    ]
    html = BookmarkHTMLBuilder(bms).build()
    assert ">书签栏</H3>" in html
    assert ">已同步</H3>" not in html   # 空根目录不输出


def test_build_and_save_roundtrip():
    bms = [
        Bookmark(id=1, title="GitHub", url="https://github.com", folder="书签栏",
                 root_folder="书签栏", category_l1="开发技术", category_l2="代码托管",
                 add_date="2026-07-01 10:00"),
        Bookmark(id=2, title="哔哩哔哩", url="https://bilibili.com", folder="书签栏",
                 root_folder="书签栏", category_l1="视频娱乐", category_l2="在线视频",
                 add_date="2026-07-02 10:00"),
    ]
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "classified.html"
        result = build_and_save(bms, str(out), add_favicon=False)
        assert result["success"], result["validation"]
        # 生成文件可被 parser 重新解析，数量一致
        reparsed = BookmarkParser().parse(str(out))
        assert len(reparsed) == 2


def test_generate_preview_tree_shows_two_levels():
    bms = [
        Bookmark(id=1, title="GitHub", url="https://github.com", folder="书签栏",
                 root_folder="书签栏", category_l1="开发技术", category_l2="代码托管"),
    ]
    tree = __import__("modules.html_builder", fromlist=["generate_preview_tree"]).generate_preview_tree(bms)
    assert "开发技术" in tree
    assert "代码托管" in tree


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

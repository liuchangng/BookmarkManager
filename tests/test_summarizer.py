"""
test_summarizer.py - 本地摘要提取 + 二阶段规则测试（T2）

运行:
    uv run pytest tests/test_summarizer.py
    uv run python tests/test_summarizer.py
"""

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from modules.bookmark import Bookmark
from modules.classifier import Classifier
from modules.summarizer import extract_summary, summarize_bookmarks


# ──────────────────────────────────────────────
#  T2.1 本地摘要提取
# ──────────────────────────────────────────────

class _FakeFetch:
    """模拟 FetchResult（对象形态）"""

    def __init__(self, description="", text="", title="", keywords=None, success=True):
        self.description = description
        self.text = text
        self.title = title
        self.keywords = keywords or []
        self.success = success


def test_extract_summary_from_description_object():
    result = _FakeFetch(description="  Docker 容器与 Kubernetes 入门教程，面向开发者的实践指南。  ")
    s = extract_summary(result)
    assert s.startswith("Docker 容器与 Kubernetes")
    assert len(s) <= 200
    assert s == s.strip()


def test_extract_summary_from_description_dict():
    result = {"description": "Python 标准库参考文档，权威教程。", "text": "正文内容忽略"}
    s = extract_summary(result)
    assert "Python 标准库" in s


def test_extract_summary_fallback_to_sentences():
    """无 description → 从正文按高频句提取"""
    text = (
        "这个网站讲的是家庭烘焙。今天分享戚风蛋糕的做法。"
        "烘焙需要准确的烤箱温度。家庭烘焙工具清单。戚风蛋糕是最受欢迎的。"
    )
    s = extract_summary(_FakeFetch(description="", text=text))
    assert s
    assert len(s) <= 200
    # 高频词「烘焙」/「戚风蛋糕」所在的句子应入选
    assert "烘焙" in s


def test_extract_summary_empty_and_short():
    assert extract_summary(None) == ""
    assert extract_summary({}) == ""
    assert extract_summary(_FakeFetch(description="", text="")) == ""
    # 过短的 description（< 8 字）视为无信息，回退正文
    assert extract_summary(_FakeFetch(description="标题", text="这里有足够长的正文内容用于回退。")) != ""


def test_summarize_bookmarks_skips_empty():
    results = {
        "https://a.com": _FakeFetch(description="这是一个足够长的有效描述文本。"),
        "https://b.com": _FakeFetch(description="", text=""),
        "https://c.com": {"description": "", "text": "另一个有效正文摘要，长度足够。", "title": "t"},
    }
    out = summarize_bookmarks(results)
    assert "https://a.com" in out
    assert "https://b.com" not in out
    assert "https://c.com" in out


# ──────────────────────────────────────────────
#  T2.2/T2.3 二阶段规则
# ──────────────────────────────────────────────

def _make_classifier(threshold=0.6, enabled=True):
    cfg = {
        "classification": {
            "summary_rule_enabled": enabled,
            "rule_confidence_threshold": threshold,
        },
        "categories": [
            {
                "name": "💻 开发",
                "keywords": [],
                "sub_categories": ["工具"],
                "sub_keywords": {"工具": ["docker", "jenkins"]},
            },
        ],
    }
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "cfg.yaml"
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
        return Classifier(str(path))


def _mk(title, url, summary=""):
    return Bookmark(id=0, title=title, url=url, page_summary=summary)


def test_classify_with_summary_hits_when_threshold_low():
    clf = _make_classifier(threshold=0.6)   # 0.7 >= 0.6 → 落地
    bm = _mk("某容器教程站", "https://example.com/x", summary="docker 容器化部署实践教程")
    assert clf.classify_with_summary(bm)
    assert bm.category_l1 == "开发"
    assert bm.category_l2 == "工具"
    assert bm.classify_method == "summary_rule"
    assert bm.confidence == 0.7


def test_classify_with_summary_defers_when_threshold_high():
    clf = _make_classifier(threshold=0.8)   # 0.7 < 0.8 → 不落地（交给 AI）
    bm = _mk("某容器教程站", "https://example.com/x", summary="docker 容器化部署实践教程")
    assert not clf.classify_with_summary(bm)
    assert bm.category_l1 == ""


def test_classify_with_summary_disabled_by_toggle():
    clf = _make_classifier(threshold=0.0, enabled=False)
    bm = _mk("某容器教程站", "https://example.com/x", summary="docker 容器化部署实践教程")
    assert not clf.classify_with_summary(bm)


def test_classify_with_summary_skips_title_url_matches():
    """一阶段职责: 标题/URL 已含关键词的，二阶段不重复处理"""
    clf = _make_classifier(threshold=0.0)
    bm = _mk("Docker 教程", "https://example.com/x", summary="docker 部署")
    assert not clf.classify_with_summary(bm)


def test_stage1_keyword_method_is_rule_not_summary():
    clf = _make_classifier(threshold=0.0)
    bms = clf.classify([_mk("Docker 入门", "https://example.com/x")])
    assert bms[0].category_l1 == "开发"
    assert bms[0].classify_method == "rule"


def test_rule_match_includes_page_summary():
    """ClassifyRule.match 的 keyword 维度包含 page_summary（增量，向后兼容）"""
    clf = _make_classifier(threshold=0.0)
    bm = _mk("某站", "https://example.com/x", summary="jenkins 持续集成配置")
    # 一阶段 classify 时摘要已就绪 → 直接命中且标记 summary_rule
    bms = clf.classify([bm])
    assert bms[0].category_l1 == "开发"
    assert bms[0].classify_method == "summary_rule"


def test_real_config_ai_mode_no_rules():
    """方案 A: 真实配置无分类规则，二阶段规则退化为空操作（摘要仍喂给 AI）"""
    clf = Classifier(str(PROJECT_ROOT / "config.yaml"))
    assert clf.get_all_rules() == []
    assert clf.summary_rule_enabled is True   # 默认值（配置中已无该键）
    bm = _mk("某容器教程站", "https://example.com/x", summary="docker 容器化部署实践教程")
    assert not clf.classify_with_summary(bm)  # 无规则 → 永不落地，全部交 AI


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

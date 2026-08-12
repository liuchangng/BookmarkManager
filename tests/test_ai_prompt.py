"""
test_ai_prompt.py - AI prompt 摘要化 + summary 字段测试（T3）

运行:
    uv run pytest tests/test_ai_prompt.py
    uv run python tests/test_ai_prompt.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.ai_client import (
    AIResult, L1_TAXONOMY, build_classify_prompt, extract_summary_from_response,
    parse_ai_response, _normalize_l2,
)

CATEGORIES = [
    {"name": "💻 开发技术", "sub_categories": ["代码托管", "文档教程"]},
    {"name": "📚 学习知识", "sub_categories": ["百科"]},
]


# ──────────────────────────────────────────────
#  T3.1 prompt 摘要化
# ──────────────────────────────────────────────

def test_prompt_uses_summary_not_raw_text():
    long_text = "这是一段很长的原始正文。" * 200   # 远超摘要长度
    info = {
        "title": "测试页",
        "url": "https://example.com/x",
        "domain": "example.com",
        "description": "描述",
        "keywords": ["docker"],
        "summary": "Docker 容器化部署教程",
        "text": long_text,
    }
    system, user = build_classify_prompt(info, CATEGORIES)
    assert "页面摘要: Docker 容器化部署教程" in user
    assert "这是一段很长的原始正文" not in user, "不应再塞长正文"
    assert "summary" in system, "system prompt 应要求输出 summary 字段"


def test_prompt_falls_back_to_text_when_no_summary():
    info = {
        "title": "测试页", "url": "https://example.com/x", "domain": "example.com",
        "description": "", "keywords": [], "text": "没有摘要时的兜底文本片段",
    }
    system, user = build_classify_prompt(info, CATEGORIES)
    assert "没有摘要时的兜底文本片段" in user


# ──────────────────────────────────────────────
#  方案 A: 无固定分类配置（AI 自由生成）
# ──────────────────────────────────────────────

def test_freeform_prompt_when_no_categories():
    """方案 A: 空 categories → 固定 8 类体系，l1/l2 必须从清单选择"""
    info = {"title": "测试页", "url": "https://example.com/x", "domain": "example.com",
            "description": "", "keywords": [], "summary": "Docker 容器化部署教程"}
    system, user = build_classify_prompt(info, [])
    assert "为书签选择两级分类" in system
    assert "8 个固定分类" in system
    assert "开发技术" in system and "娱乐休闲" in system and "其他" in system
    assert "可选分类体系" not in user
    assert "8 个固定分类" in user
    assert "页面摘要: Docker 容器化部署教程" in user


def test_parse_freeform_ai_labels_validated():
    """方案 A: l1/l2 硬校验到固定 8 类体系（合法保留、非法收敛、空值兜底）"""
    # 合法 l1 + 推荐清单内 l2 → 保留
    resp = ('{"l1": "开发技术", "l2": "代码托管", "confidence": 0.82, '
            '"reason": "docker教程", "summary": "x"}')
    l1, l2, conf, reason = parse_ai_response(resp, [])
    assert l1 == "开发技术"
    assert l2 == "代码托管"
    assert conf == 0.82
    assert reason == "docker教程"

    # 合法 l1 但 l2 不在推荐清单 → 收敛到「未分类」
    l1c, l2c, _, _ = parse_ai_response('{"l1": "开发技术", "l2": "容器编排", "confidence": 0.8}', [])
    assert l1c == "开发技术"
    assert l2c == "未分类"

    # 非法 l1（AI 自造）→ 收敛到「其他」；emoji 被清洗
    l1e, l2e, _, _ = parse_ai_response('{"l1": "💻 我的自造分类", "l2": "🚀 部署工具", "confidence": 0.8}', [])
    assert l1e == "其他"
    assert l2e == "未分类"

    # 缺 l1/l2 → 其他/未分类 兜底
    l1m, l2m, _, _ = parse_ai_response('{"l1": "", "l2": "", "confidence": 0.1}', [])
    assert l1m == "其他"
    assert l2m == "未分类"

    # 8 类内的模糊匹配（AI 返回带前后缀的 l1）→ 归一
    l1f, _, _, _ = parse_ai_response('{"l1": "工具软件类", "l2": "效率工具", "confidence": 0.8}', [])
    assert l1f == "工具软件"
    assert _normalize_l2("工具软件", "效率工具") == "效率工具"


# ──────────────────────────────────────────────
#  T3.1 响应解析兼容
# ──────────────────────────────────────────────

def test_parse_old_format_without_summary():
    """旧格式响应（无 summary 字段）仍可解析"""
    resp = '{"l1": "💻 开发技术", "l2": "文档教程", "confidence": 0.85, "reason": "官方文档"}'
    l1, l2, conf, reason = parse_ai_response(resp, CATEGORIES)
    assert l1 == "💻 开发技术"
    assert l2 == "文档教程"
    assert conf == 0.85
    assert reason == "官方文档"


def test_parse_new_format_with_summary():
    resp = ('{"l1": "📚 学习知识", "l2": "百科", "confidence": 0.9, '
            '"reason": "百科类", "summary": "维基百科词条"}')
    l1, l2, conf, reason = parse_ai_response(resp, CATEGORIES)
    assert l1 == "📚 学习知识"
    assert l2 == "百科"


def test_parse_code_fenced_response():
    resp = '```json\n{"l1": "💻 开发技术", "l2": "代码托管", "confidence": 0.8, "reason": "代码托管"}\n```'
    l1, l2, conf, reason = parse_ai_response(resp, CATEGORIES)
    assert l1 == "💻 开发技术"
    assert l2 == "代码托管"


# ──────────────────────────────────────────────
#  T3.1 摘要提取
# ──────────────────────────────────────────────

def test_extract_summary_from_json():
    resp = '{"l1": "开发", "l2": "工具", "summary": "Docker 部署教程", "reason": "x"}'
    assert extract_summary_from_response(resp) == "Docker 部署教程"


def test_extract_summary_code_fenced():
    resp = '```json\n{"l1": "开发", "summary": "容器编排入门"}\n```'
    assert extract_summary_from_response(resp) == "容器编排入门"


def test_extract_summary_missing_or_garbage():
    assert extract_summary_from_response("") == ""
    assert extract_summary_from_response("no json here") == ""
    # 旧格式无 summary → 空串（兼容）
    assert extract_summary_from_response('{"l1": "开发", "confidence": 0.8}') == ""


# ──────────────────────────────────────────────
#  T3.2 summary 数据流
# ──────────────────────────────────────────────

def test_ai_result_to_dict_includes_summary():
    r = AIResult("https://a.com")
    r.success = True
    r.category_l1 = "开发"
    r.summary = "测试摘要"
    d = r.to_dict()
    assert d["summary"] == "测试摘要"
    assert d["url"] == "https://a.com"


def test_ai_skip_logic_invariant():
    """
    _chain_ai 的跳过条件（本地/失效/summary_rule/高置信度 不进入 AI 队列）
    与 main_window 实现保持一致的不变量
    """
    from modules.bookmark import Bookmark

    def should_skip(bm):
        if bm.user_deleted:
            return True
        if bm.status in ("local", "dead"):
            return True
        if bm.classify_method == "summary_rule":
            return True
        if bm.category_l1 and bm.category_l1 != "其他" and bm.confidence >= 0.8:
            return True
        return False

    cases = [
        Bookmark(id=1, status="local", classify_method="local", category_l1="📁 本地/内网", confidence=1.0),
        Bookmark(id=2, status="dead", classify_method="dead", category_l1="⚠️ 失效链接", confidence=1.0),
        Bookmark(id=3, classify_method="summary_rule", category_l1="开发", confidence=0.7),
        Bookmark(id=4, classify_method="rule", category_l1="开发", confidence=0.95),
        Bookmark(id=5, classify_method="rule", category_l1="其他", confidence=0.0),   # 待分类 → 需 AI
        Bookmark(id=6, user_deleted=True, classify_method="rule"),
    ]
    skipped = [b.id for b in cases if should_skip(b)]
    need_ai = [b.id for b in cases if not should_skip(b)]
    assert skipped == [1, 2, 3, 4, 6]
    assert need_ai == [5]


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

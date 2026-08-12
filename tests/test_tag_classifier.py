"""
test_tag_classifier.py - 标签频率聚类测试（T3/T4 标签模式核心）

验证 classify_by_tag_frequency:
- 一级 = 全局标签频率 Top N
- 二级 = 每个一级子集内频率 Top M
- 确定性 / 幂等 / min_count 阈值 / 无标签书签跳过
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.bookmark import Bookmark
from modules.tag_classifier import classify_by_tag_frequency, FALLBACK_L1


def _mk(url, tags):
    bm = Bookmark()
    bm.url = url
    bm.title = url
    bm.tags = list(tags)
    return bm


def test_top_tags_become_l1():
    """全局频率最高的标签成为一级分类，书签归入其标签中频率最高者"""
    bms = [
        _mk("a", ["docker", "容器"]),
        _mk("b", ["docker", "部署"]),
        _mk("c", ["docker", "教程"]),
        _mk("d", ["java", "教程"]),
        _mk("e", ["java", "框架"]),
        _mk("f", ["java", "框架"]),
    ]
    dist = classify_by_tag_frequency(bms, top_l1=8, top_l2=3, min_count=2)
    l1s = {bm.category_l1 for bm in bms}
    # docker(3) java(3) 进入一级；容器/部署/教程/框架 频率不足 2 且非 Top
    assert "docker" in l1s and "java" in l1s
    # 每条书签归入它最热的标签
    assert bms[0].category_l1 == "docker"
    assert bms[5].category_l1 == "java"
    # 分布统计：docker 子集内次标签都不足 2 次 → 全「其他」；java 子集内框架(2) → l2
    assert dist["docker"]["其他"] == 3
    assert dist["java"]["框架"] == 2


def test_secondary_tag_becomes_l2():
    """一级子集内次高频标签成为二级分类"""
    bms = [
        _mk("a", ["docker", "容器", "部署"]),
        _mk("b", ["docker", "容器", "部署"]),
        _mk("c", ["docker", "容器"]),
        _mk("d", ["docker", "网络"]),
    ]
    classify_by_tag_frequency(bms, top_l1=8, top_l2=3, min_count=2)
    # docker 子集内：容器(3) 最热 → 大部分 l2=容器；网络(1)<2 → 其他
    assert all(bm.category_l1 == "docker" for bm in bms)
    assert bms[0].category_l2 == "容器"
    assert bms[3].category_l2 == "其他"


def test_rare_tags_fallback_to_other():
    """频率不足 min_count 的标签不成为分类，书签归「其他」"""
    bms = [
        _mk("a", ["很冷门的标签"]),
        _mk("b", ["另一个冷门"]),
    ]
    classify_by_tag_frequency(bms, top_l1=8, top_l2=3, min_count=2)
    assert bms[0].category_l1 == FALLBACK_L1
    assert bms[1].category_l1 == FALLBACK_L1


def test_no_tags_untouched():
    """无标签书签不参与聚类，保持原分类不变"""
    bm = _mk("x", [])
    bm.category_l1 = "手动分类"
    classify_by_tag_frequency([bm], top_l1=8, top_l2=3, min_count=2)
    assert bm.category_l1 == "手动分类"


def test_deterministic_and_idempotent():
    """确定性：同样输入两次聚类结果一致（不因已有分类改变）"""
    bms = [
        _mk("a", ["docker", "容器"]),
        _mk("b", ["docker", "部署"]),
        _mk("c", ["java", "框架"]),
    ]
    classify_by_tag_frequency(bms, top_l1=8, top_l2=3, min_count=2)
    first = [(b.category_l1, b.category_l2) for b in bms]
    classify_by_tag_frequency(bms, top_l1=8, top_l2=3, min_count=2)
    second = [(b.category_l1, b.category_l2) for b in bms]
    assert first == second


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

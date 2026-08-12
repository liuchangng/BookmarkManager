"""
tag_classifier.py - 标签频率聚类（两级分类）

AI 为每条书签生成约 10 个规范标签后，服务端按标签频率聚类：

  一级分类: 全局标签频率 Top N（默认 8，且出现 ≥ min_count 次）
  二级分类: 每个一级子集内，除该一级标签外的标签频率 Top M（默认 5）

优点（对比 AI 直接输出分类）:
  - 确定性: 同样输入永远同样输出，可复现
  - 可解释: 每条书签的分类 = "它的标签里出现最多的那个"，用户看得懂
  - 天然收敛: 一级 = 书签里最热门的 8 个主题，不会碎片化
  - 省 token: AI 只做低风险的"打标签"，不做高风险的"编分类"
"""

from collections import Counter
from typing import Optional

# 一级/二级兜底名称
FALLBACK_L1 = "其他"
FALLBACK_L2 = "其他"


def classify_by_tag_frequency(
    bookmarks: list,
    top_l1: int = 8,
    top_l2: int = 5,
    min_count: int = 2,
) -> dict:
    """
    对已有 tags 的书签聚类，写回 category_l1 / category_l2。

    bookmarks: 含 .tags（list[str]）的 Bookmark 列表
    top_l1: 一级分类数量上限
    top_l2: 每个一级下的二级分类数量上限
    min_count: 标签至少出现几次才够格成为分类（1 = 不设门槛）

    返回: {l1: {l2: count}} 分布统计
    """
    tagged = [bm for bm in bookmarks if getattr(bm, "tags", None)]

    # 1. 全局标签频率
    freq: Counter = Counter()
    for bm in tagged:
        freq.update(bm.tags)

    # 2. 一级分类 = 频率 Top N（须 ≥ min_count 次）
    l1_list = [tag for tag, c in freq.most_common(top_l1 * 4)
               if c >= min_count][:top_l1]
    l1_set = set(l1_list)

    # 3. 每条书签的一级 = 其标签中全局频率最高的 l1 候选；无命中 → 其他
    for bm in tagged:
        best: Optional[str] = None
        for tag in bm.tags:
            if tag in l1_set and (best is None or freq[tag] > freq[best]):
                best = tag
        bm.category_l1 = best or FALLBACK_L1
        bm.category_l2 = FALLBACK_L2

    # 4. 二级分类：每个一级子集内，除一级标签外按频率取 Top M
    for l1 in l1_list + [FALLBACK_L1]:
        sub = [bm for bm in tagged if bm.category_l1 == l1]
        if not sub:
            continue
        sub_freq: Counter = Counter()
        for bm in sub:
            for tag in bm.tags:
                if tag != l1:
                    sub_freq[tag] += 1
        l2_list = [tag for tag, c in sub_freq.most_common(top_l2 * 4)
                   if c >= min_count][:top_l2]
        l2_set = set(l2_list)
        for bm in sub:
            best: Optional[str] = None
            for tag in bm.tags:
                if tag in l2_set and (best is None or sub_freq[tag] > sub_freq[best]):
                    best = tag
            bm.category_l2 = best or FALLBACK_L2

    # 分布统计
    dist: dict = {}
    for bm in tagged:
        l1 = bm.category_l1 or FALLBACK_L1
        l2 = bm.category_l2 or FALLBACK_L2
        dist.setdefault(l1, {})
        dist[l1][l2] = dist[l1].get(l2, 0) + 1
    return dist

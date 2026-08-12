"""
summarizer.py - 本地摘要提取器（T2，design §5 B3）
功能: 从抓取结果提取 ≤200 字摘要，零网络、纯本地
优先级: description(meta/og/twitter) → 正文高频句首句
消费对象: modules.fetcher.FetchResult 对象 或 to_dict() 的 dict（兼容 fetch_worker 两种形态）
"""

import re
import logging
from collections import Counter

logger = logging.getLogger("summarizer")

MAX_SUMMARY_LEN = 200
MIN_SENTENCE_LEN = 8     # 过短句子无信息量
TOP_SENTENCES = 3        # 高频句取前 N 句
_WORD_RE = re.compile(r"[a-zA-Z]{3,}|[\u4e00-\u9fff]{2,}")


def _clean(text: str) -> str:
    """折叠空白、去掉常见摘要前缀"""
    text = re.sub(r"\s+", " ", text or "")
    text = re.sub(r"^(摘要|简介|描述|summary|description)[:：]\s*", "", text, flags=re.I)
    return text.strip()


def extract_summary(result) -> str:
    """
    从抓取结果提取摘要（≤200 字）

    优先级:
      1. description（fetcher 已合并 meta/og/twitter:description）
      2. 正文高频句（按关键词密度取前 3 句）
    """
    if result is None:
        return ""
    if isinstance(result, dict):
        description = result.get("description") or ""
        text = result.get("text") or ""
    else:
        description = getattr(result, "description", "") or ""
        text = getattr(result, "text", "") or ""

    description = _clean(description)
    if len(description) >= MIN_SENTENCE_LEN:
        return description[:MAX_SUMMARY_LEN]

    text = _clean(text)
    if not text:
        return ""

    sentences = [
        s.strip() for s in re.split(r"[。！？!?；;\n]+", text)
        if len(s.strip()) >= MIN_SENTENCE_LEN
    ]
    if not sentences:
        return text[:MAX_SUMMARY_LEN]

    # 词频统计（英文单词 + 中文双字以上词组）
    freq: Counter = Counter()
    for s in sentences:
        freq.update(_WORD_RE.findall(s.lower()))

    scored = sorted(
        ((sum(freq[w] for w in _WORD_RE.findall(s.lower())), s) for s in sentences),
        key=lambda x: x[0], reverse=True,
    )
    top = "。".join(s for _, s in scored[:TOP_SENTENCES])
    return top[:MAX_SUMMARY_LEN]


def summarize_bookmarks(fetch_results: dict) -> dict[str, str]:
    """
    批量提取: {url: summary}
    无内容/失败的抓取结果不返回（其书签不参与二阶段规则）
    """
    out: dict[str, str] = {}
    for url, result in (fetch_results or {}).items():
        summary = extract_summary(result)
        if summary:
            out[url] = summary
    return out

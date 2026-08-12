"""
ai_client.py - DeepSeek AI 分类客户端
功能: 调用 DeepSeek API 对书签内容进行智能分类
特性: 批量并发 / 重试 / 成本控制 / 流式解析 / 代理支持
"""

import json
import time
import hashlib
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

import requests

from modules.fetcher import ProxyAdapter

logger = logging.getLogger("ai_client")


# ──────────────────────────────────────────────
#  常量
# ──────────────────────────────────────────────

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
MAX_PROMPT_CHARS = 2000  # 单次请求最大上下文（T3: AI 输入改为页面摘要，不再塞长正文）
ESTIMATED_PRICE_PER_1K = 0.0014  # deepseek-chat 输入约 $0.0014/1K tokens (约 ¥0.01)
AI_CACHE_VERSION = "3"  # v3: 方案 A——移除固定分类配置，AI 自由生成标签


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

class AIResult:
    """单条 AI 分类结果"""

    def __init__(self, url: str):
        self.url = url
        self.success: bool = False
        self.category_l1: str = ""
        self.category_l2: str = ""
        self.confidence: float = 0.0
        self.reason: str = ""
        self.summary: str = ""   # T3: AI 生成的一句话摘要（回写 Bookmark.page_summary）
        self.raw_response: str = ""
        self.tokens_used: int = 0
        self.elapsed_ms: int = 0
        self.error: str = ""
        self.model: str = ""

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "success": self.success,
            "category_l1": self.category_l1,
            "category_l2": self.category_l2,
            "confidence": self.confidence,
            "reason": self.reason,
            "summary": self.summary,
            "tokens_used": self.tokens_used,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "model": self.model,
        }


# ──────────────────────────────────────────────
#  AI 缓存
# ──────────────────────────────────────────────

class AICache:
    """AI 分类结果缓存"""

    def __init__(self, cache_dir: str = "data/cache/ai"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "ai_cache.json"
        self._data: dict = {"version": AI_CACHE_VERSION, "entries": {}}
        self._hits: int = 0
        self._misses: int = 0
        self.load()

    def load(self):
        if not self.cache_file.exists():
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            if self._data.get("version") != AI_CACHE_VERSION:
                self._data = {"version": AI_CACHE_VERSION, "entries": {}}
        except (json.JSONDecodeError, OSError):
            self._data = {"version": AI_CACHE_VERSION, "entries": {}}

    def save(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"AI缓存写入失败: {e}")

    def get(self, url: str) -> Optional[dict]:
        key = self._hash(url)
        entry = self._data.get("entries", {}).get(key)
        if entry:
            self._hits += 1
            return entry
        self._misses += 1
        return None

    def set(self, url: str, result: AIResult):
        key = self._hash(url)
        self._data.setdefault("entries", {})[key] = result.to_dict()

    def stats(self) -> dict:
        total = len(self._data.get("entries", {}))
        return {
            "total": total,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / (self._hits + self._misses) if (self._hits + self._misses) > 0 else 0,
        }

    def clear(self):
        count = len(self._data.get("entries", {}))
        self._data = {"version": AI_CACHE_VERSION, "entries": {}}
        self.save()
        logger.info(f"AI缓存已清空 ({count} 条)")

    @staticmethod
    def _hash(url: str) -> str:
        normalized = url.strip().rstrip("/").lower()
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]


# ──────────────────────────────────────────────
#  Prompt 构建
# ──────────────────────────────────────────────

def build_classify_prompt(bookmark_info: dict, categories: list[dict]) -> tuple[str, str]:
    """
    构建分类 prompt (system + user)
    bookmark_info: {title, url, domain, description, keywords, text}
    categories: config 中的 categories 列表；为空时 → 方案 A：AI 自由生成两级分类
    """
    if not categories:
        # ── 方案 A: 无固定分类配置，AI 自动生成标签（全程自动化）──
        system = (
            "你是一个专业的书签分类助手。\n"
            "任务: 根据用户提供的网页信息，自动为书签生成两级分类。\n"
            "要求:\n"
            "1. 一级分类(l1): 2-6 字中文领域名（例如: 开发技术、购物消费、视频娱乐）\n"
            "2. 二级分类(l2): 2-8 字贴切小类（例如: 代码托管、在线视频、优惠券/比价）\n"
            "3. 相同主题的书签必须使用完全相同的分类名称，禁止同义反复，保持整体一致性\n"
            "4. 分类名称不要带 emoji、符号或编号\n"
            "5. 给出置信度 (0-1 之间的小数) 与简短理由 (≤20字)\n"
            "6. 用一句话概括该网页内容作为 summary (≤50字)\n"
            "7. 严格输出 JSON 格式，不要输出其他内容\n\n"
            "输出格式示例:\n"
            '{"l1": "开发技术", "l2": "文档教程", "confidence": 0.85, "reason": "Python官方文档", "summary": "Python 标准库官方文档"}\n'
        )
    else:
        # ── 有固定分类体系：AI 从给定体系中选择（约束模式，保留兼容）──
        system = (
            "你是一个专业的书签分类助手。\n"
            "任务: 根据用户提供的网页信息，将其分类到给定的分类体系中。\n"
            "要求:\n"
            "1. 必须选择分类体系中最匹配的 一级分类 和 二级分类\n"
            "2. 给出置信度 (0-1 之间的小数)\n"
            "3. 给出简短分类理由 (≤20字)\n"
            "4. 用一句话概括该网页内容作为 summary (≤50字)\n"
            "5. 严格输出 JSON 格式，不要输出其他内容\n\n"
            "输出格式示例:\n"
            '{"l1": "💻 开发技术", "l2": "文档教程", "confidence": 0.85, "reason": "Python官方文档教程", "summary": "Python 标准库官方文档"}\n'
        )

    # 构建分类体系描述（仅约束模式）
    cat_desc = []
    for cat in categories:
        name = cat.get("name", "")
        subs = cat.get("sub_categories", [])
        subs_str = "、".join(subs) if subs else "未分类"
        cat_desc.append(f"  {name}: [{subs_str}]")

    cat_text = "\n".join(cat_desc)

    # User prompt
    title = bookmark_info.get("title", "")[:200]
    url = bookmark_info.get("url", "")
    domain = bookmark_info.get("domain", "")
    desc = bookmark_info.get("description", "")[:300]
    keywords = bookmark_info.get("keywords", [])
    # T3: 页面摘要（本地摘要或 AI 摘要），替代原 500 字长正文 → 省 token
    summary = (bookmark_info.get("summary") or bookmark_info.get("text") or "")[:300]

    kw_str = "、".join(keywords[:10]) if keywords else "无"

    if not categories:
        user = (
            f"网页信息:\n"
            f"  标题: {title}\n"
            f"  URL: {url}\n"
            f"  域名: {domain}\n"
            f"  描述: {desc}\n"
            f"  关键词: {kw_str}\n"
            f"  页面摘要: {summary}\n\n"
            f"分类由你自动生成（无需受限于固定清单），请保持与同类书签一致的命名。\n"
            f'请直接输出 JSON: {{"l1": "...", "l2": "...", "confidence": 0.x, "reason": "...", "summary": "..."}}'
        )
    else:
        user = (
            f"网页信息:\n"
            f"  标题: {title}\n"
            f"  URL: {url}\n"
            f"  域名: {domain}\n"
            f"  描述: {desc}\n"
            f"  关键词: {kw_str}\n"
            f"  页面摘要: {summary}\n\n"
            f"可选分类体系:\n"
            f"{cat_text}\n\n"
            f'请直接输出 JSON: {{"l1": "...", "l2": "...", "confidence": 0.x, "reason": "...", "summary": "..."}}'
        )

    return system, user


def extract_summary_from_response(response_text: str) -> str:
    """容错提取 AI 响应中的 summary 字段（无则返回空串，兼容旧格式响应）"""
    if not response_text:
        return ""
    text = response_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        import re
        m = re.search(r'"summary"\s*:\s*"([^"]*)"', response_text or "")
        return m.group(1).strip()[:100] if m else ""
    return str(data.get("summary", "")).strip()[:100]


# ──────────────────────────────────────────────
#  响应解析
# ──────────────────────────────────────────────

def parse_ai_response(response_text: str, categories: list[dict]) -> tuple[str, str, float, str]:
    """
    解析 AI 返回的 JSON
    返回: (l1, l2, confidence, reason)
    """
    # 提取 JSON (兼容 ```json 包裹)
    text = response_text.strip()
    if text.startswith("```"):
        # 去掉代码块
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    # 尝试找第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 尝试宽松提取
        import re
        m = re.search(r'\{[^{}]*"l1"[^{}]*\}', text)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                raise ValueError(f"无法解析AI响应: {response_text[:200]}")
        else:
            raise ValueError(f"无法解析AI响应: {response_text[:200]}")

    l1 = str(data.get("l1", "")).strip()
    l2 = str(data.get("l2", "")).strip()
    confidence = float(data.get("confidence", 0))
    reason = str(data.get("reason", "")).strip()[:50]

    if not categories:
        # ── 方案 A: 无固定分类配置，AI 标签直接采用（仅做基本清洗）──
        import re
        l1 = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", l1).strip()[:20]
        l2 = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", l2).strip()[:20]
        if not l1:
            l1 = "📁 其他"
        if not l2:
            l2 = "未分类"
    else:
        # 验证 l1 是否在分类体系中
        valid_l1 = {c.get("name", "") for c in categories}
        if l1 not in valid_l1:
            # 尝试模糊匹配
            for valid in valid_l1:
                if valid in l1 or l1 in valid:
                    l1 = valid
                    break
            else:
                l1 = "📁 其他"

        # 验证 l2 是否在该 l1 的子分类中
        valid_l2 = set()
        for c in categories:
            if c.get("name", "") == l1:
                valid_l2 = set(c.get("sub_categories", []))
                break

        if l2 not in valid_l2:
            # 取第一个子分类或留空
            l2 = list(valid_l2)[0] if valid_l2 else "未分类"

    # 置信度裁剪
    confidence = max(0.0, min(1.0, confidence))

    return l1, l2, confidence, reason


# ──────────────────────────────────────────────
#  主客户端
# ──────────────────────────────────────────────

class OpenAIClient:
    """
    OpenAI 兼容 API 客户端

    功能:
    - 单条/批量分类
    - 并发控制
    - 重试 + 指数退避
    - 成本预估 + 上限控制
    - 缓存
    - 代理支持
    """

    def __init__(self, config: dict, categories: list[dict],
                 proxy_adapter: Optional[ProxyAdapter] = None,
                 api_key: str = ""):
        self.config = config
        self.categories = categories

        ai_cfg = config.get("ai", {})
        self.base_url = ai_cfg.get("base_url", DEFAULT_BASE_URL).rstrip("/")
        self.model = ai_cfg.get("model", DEFAULT_MODEL)
        self.timeout = ai_cfg.get("timeout", 30)
        self.max_retries = ai_cfg.get("max_retries", 3)
        self.concurrency = ai_cfg.get("concurrency", 3)
        self.batch_size = ai_cfg.get("batch_size", 5)
        self.max_cost_yuan = ai_cfg.get("max_cost_yuan", 5.0)
        # 优先使用显式传入的 api_key（pipeline 从 SecureStore 读取后传入），
        # 否则回退到 config（兼容旧调用方式）
        self.api_key = api_key or ai_cfg.get("api_key")

        # 代理
        self.proxy = proxy_adapter

        # 缓存
        cache_dir = config.get("classification", {}).get("cache_dir", "data/cache")
        self.cache = AICache(cache_dir=f"{cache_dir}/ai")

        # 统计
        self._stats = {
            "total": 0, "success": 0, "failed": 0,
            "cached": 0, "retries": 0,
            "tokens_used": 0, "estimated_cost_yuan": 0.0,
        }

    # ──────────────────────────────────────────────
    #  配置更新
    # ──────────────────────────────────────────────

    def set_api_key(self, key: str):
        self.api_key = key

    def update_config(self, config: dict):
        ai_cfg = config.get("ai", {})
        self.base_url = ai_cfg.get("base_url", self.base_url).rstrip("/")
        self.model = ai_cfg.get("model", self.model)
        self.timeout = ai_cfg.get("timeout", self.timeout)
        self.max_retries = ai_cfg.get("max_retries", self.max_retries)
        self.concurrency = ai_cfg.get("concurrency", self.concurrency)
        self.batch_size = ai_cfg.get("batch_size", self.batch_size)
        self.max_cost_yuan = ai_cfg.get("max_cost_yuan", self.max_cost_yuan)

    def set_categories(self, categories: list[dict]):
        self.categories = categories

    # ──────────────────────────────────────────────
    #  单条分类
    # ──────────────────────────────────────────────

    def classify_one(self, bookmark_info: dict) -> AIResult:
        """
        对单条书签进行分类
        bookmark_info: {title, url, domain, description, keywords, text}
        """
        url = bookmark_info.get("url", "")
        self._stats["total"] += 1
        result = AIResult(url)

        # 1. 缓存查询
        cached = self.cache.get(url)
        if cached:
            self._stats["cached"] += 1
            result.success = cached.get("success", False)
            result.category_l1 = cached.get("category_l1", "")
            result.category_l2 = cached.get("category_l2", "")
            result.confidence = cached.get("confidence", 0)
            result.reason = cached.get("reason", "")
            result.summary = cached.get("summary", "")
            result.model = cached.get("model", self.model)
            return result

        # 2. 成本检查
        if self._stats["estimated_cost_yuan"] >= self.max_cost_yuan:
            result.error = f"达到成本上限 ¥{self.max_cost_yuan}"
            self._stats["failed"] += 1
            return result

        # 3. 构建 prompt
        system, user = build_classify_prompt(bookmark_info, self.categories)

        # 4. 调用 API (带重试)
        start = time.time()
        for attempt in range(self.max_retries):
            try:
                response = self._call_api(system, user)
                result.raw_response = response

                # 解析
                l1, l2, conf, reason = parse_ai_response(response, self.categories)
                result.category_l1 = l1
                result.category_l2 = l2
                result.confidence = conf
                result.reason = reason
                result.summary = extract_summary_from_response(response)
                result.success = True
                result.model = self.model

                # 估算 token (粗略: 中文字符数/1.5 + 英文词数)
                text_all = system + user + response
                tokens = self._estimate_tokens(text_all)
                result.tokens_used = tokens
                self._stats["tokens_used"] += tokens
                self._stats["estimated_cost_yuan"] += tokens / 1000 * ESTIMATED_PRICE_PER_1K * 7.2  # USD→CNY

                break

            except Exception as e:
                self._stats["retries"] += 1
                if attempt < self.max_retries - 1:
                    backoff = min(2 ** (attempt + 1), 8)
                    logger.debug(f"  AI 重试 {attempt+1}/{self.max_retries} (等待 {backoff}s): {e}")
                    time.sleep(backoff)
                else:
                    result.error = f"AI 调用失败: {type(e).__name__}: {str(e)[:100]}"
                    self._stats["failed"] += 1
                    logger.error(f"  AI 分类失败 [{url}]: {result.error}")

        result.elapsed_ms = int((time.time() - start) * 1000)

        # 5. 缓存
        if result.success:
            self.cache.set(url, result)
            self._stats["success"] += 1

        # 每 20 条保存缓存
        if self._stats["total"] % 20 == 0:
            self.cache.save()

        return result

    # ──────────────────────────────────────────────
    #  API 调用
    # ──────────────────────────────────────────────

    def _call_api(self, system: str, user: str) -> str:
        """
        调用 Chat Completions API

        代理策略（先直连，失败走代理）:
          1. 先直接请求（不走代理）——国内/白名单 API 直连更快更稳
          2. 直连失败 → 用配置的代理再请求一次
          3. 仍失败 → 抛出异常，由 classify_one 外层重试（默认 3 次）
          4. 全部失败 → result.success=False，书签归为未分类
        """
        if not self.api_key:
            raise ValueError("API Key 未配置")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,   # 低温度，稳定输出
            "max_tokens": 200,    # 只需要短 JSON
            "response_format": {"type": "json_object"},  # DeepSeek 支持
        }

        # 候选通道: 先直连，再代理（若配置了代理且该 URL 不绕过）
        candidates = [None]  # 直连
        if self.proxy:
            px = self.proxy.get_proxies(url)
            if px:
                candidates.append(px)

        last_error: Optional[Exception] = None
        for i, proxies in enumerate(candidates):
            mode = "直连" if proxies is None else f"代理 {proxies.get('http', '')}"
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                    proxies=proxies,
                )

                if resp.status_code != 200:
                    last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    logger.warning(f"  AI 请求[{mode}]失败: {last_error}")
                    continue

                data = resp.json()
                choices = data.get("choices", [])
                if not choices:
                    last_error = RuntimeError(f"API 返回空 choices: {data}")
                    logger.warning(f"  AI 请求[{mode}]返回空 choices")
                    continue

                content = choices[0].get("message", {}).get("content", "")
                if not content:
                    last_error = RuntimeError(f"API 返回空内容: {data}")
                    logger.warning(f"  AI 请求[{mode}]返回空内容")
                    continue

                return content

            except Exception as e:
                last_error = e
                logger.warning(f"  AI 请求[{mode}]异常: {type(e).__name__}: {str(e)[:120]}")
                continue

        raise last_error or RuntimeError("AI 请求失败")

    # ──────────────────────────────────────────────
    #  批量分类 (串行，并发版由 worker 实现)
    # ──────────────────────────────────────────────

    def classify_many(self, bookmarks_info: list[dict],
                      progress_cb=None) -> list[AIResult]:
        """
        批量分类 (串行)
        bookmarks_info: [{title, url, domain, ...}, ...]
        progress_cb: callback(current, total, result)
        """
        results: list[AIResult] = []
        total = len(bookmarks_info)

        for i, info in enumerate(bookmarks_info):
            result = self.classify_one(info)
            results.append(result)

            if progress_cb:
                progress_cb(i + 1, total, result)

            # 成本检查
            if self._stats["estimated_cost_yuan"] >= self.max_cost_yuan:
                logger.warning(f"⚠️ 达到成本上限 ¥{self.max_cost_yuan}，停止分类")
                break

        self.cache.save()
        return results

    # ──────────────────────────────────────────────
    #  成本估算
    # ──────────────────────────────────────────────

    def estimate_cost(self, count: int) -> dict:
        """预估 N 条分类的成本"""
        # 每条约 1500 字符输入 + 100 字符输出 ≈ 1100 tokens
        avg_tokens_per_item = 1100
        total_tokens = count * avg_tokens_per_item
        cost_usd = total_tokens / 1000 * ESTIMATED_PRICE_PER_1K
        cost_cny = cost_usd * 7.2
        return {
            "count": count,
            "estimated_tokens": total_tokens,
            "estimated_cost_usd": round(cost_usd, 4),
            "estimated_cost_yuan": round(cost_cny, 4),
            "max_cost_yuan": self.max_cost_yuan,
            "within_budget": cost_cny <= self.max_cost_yuan,
        }

    # ──────────────────────────────────────────────
    #  工具
    # ──────────────────────────────────────────────

    def _estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数"""
        # 中文: ~1.5 字符/token; 英文: ~4 字符/token
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        tokens = chinese_chars / 1.5 + other_chars / 4
        return int(tokens)

    def get_stats(self) -> dict:
        s = dict(self._stats)
        s["cache"] = self.cache.stats()
        s["remaining_budget_yuan"] = round(
            self.max_cost_yuan - s["estimated_cost_yuan"], 4
        )
        return s

    def print_stats(self):
        s = self.get_stats()
        logger.info("=" * 50)
        logger.info("🤖 AI 分类统计")
        logger.info("=" * 50)
        logger.info(f"  总计: {s['total']} | 成功: {s['success']} | 失败: {s['failed']} | 缓存: {s['cached']}")
        logger.info(f"  重试: {s['retries']} | Tokens: {s['tokens_used']}")
        logger.info(f"  预估费用: ¥{s['estimated_cost_yuan']:.4f} / ¥{self.max_cost_yuan:.2f}")
        logger.info(f"  缓存: {s['cache']['total']}条 | 命中率: {s['cache']['hit_rate']*100:.0f}%")
        logger.info("=" * 50)

    def reset_stats(self):
        self._stats = {
            "total": 0, "success": 0, "failed": 0,
            "cached": 0, "retries": 0,
            "tokens_used": 0, "estimated_cost_yuan": 0.0,
        }

    def save_cache(self):
        self.cache.save()

    def clear_cache(self):
        self.cache.clear()
        self.reset_stats()


# ──────────────────────────────────────────────
#  便捷函数
# ──────────────────────────────────────────────

def quick_classify(url: str, title: str, api_key: str, categories: list[dict],
                   config: dict = None) -> AIResult:
    """快速分类单个 URL (需先抓取内容)"""
    from modules.fetcher import quick_fetch
    cfg = config or {}
    fetcher = None  # 不需要完整 fetcher
    page = quick_fetch(url, config=cfg) if cfg else None

    from modules.summarizer import extract_summary
    info = {
        "url": url,
        "title": title,
        "domain": urlparse(url).hostname or "",
        "description": page.description if page else "",
        "keywords": page.keywords if page else [],
        "summary": extract_summary(page) if page else "",
    }

    client = OpenAIClient(config=cfg, categories=categories, api_key=api_key)
    return client.classify_one(info)


def test_api_key(api_key: str, base_url: str = DEFAULT_BASE_URL,
                 model: str = DEFAULT_MODEL) -> dict:
    """测试 API Key 是否有效"""
    result = {"success": False, "model": model, "error": "", "elapsed_ms": 0}
    start = time.time()
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": '回复 "ok"'}],
            "max_tokens": 10,
            "temperature": 0,
        }
        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            json=payload, headers=headers, timeout=15,
        )
        result["elapsed_ms"] = int((time.time() - start) * 1000)

        if resp.status_code == 200:
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            result["success"] = True
            result["test_response"] = content[:50]
        else:
            result["error"] = f"HTTP {resp.status_code}: {resp.text[:100]}"

    except Exception as e:
        result["elapsed_ms"] = int((time.time() - start) * 1000)
        result["error"] = f"{type(e).__name__}: {str(e)[:80]}"

    return result


# 延迟导入避免循环
from urllib.parse import urlparse  # noqa: E402

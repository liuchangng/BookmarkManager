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
AI_CACHE_VERSION = "4"  # v4: 标签模式——AI 生成规范标签，分类由服务端按频率聚类


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
        self.tags: list = []     # 标签模式: AI 生成的规范标签（服务端按频率聚类）
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
            "tags": self.tags,
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
#  固定分类体系（方案 A 用）
#  8 个一级分类 + 每类推荐二级分类清单：AI 必须从清单选择，禁止自造新名称
# ──────────────────────────────────────────────

L1_TAXONOMY: dict[str, list[str]] = {
    "开发技术": ["代码托管", "编程语言", "开发框架", "开发工具", "数据库", "运维部署", "云原生", "测试"],
    "人工智能": ["AI 工具", "大模型", "机器学习", "提示词工程", "AI 教程", "AIGC"],
    "工具软件": ["在线工具", "效率工具", "设计工具", "办公软件", "系统工具", "浏览器插件"],
    "学习资源": ["技术教程", "在线课程", "技术文档", "技术博客", "面试求职", "社区论坛"],
    "新闻资讯": ["科技新闻", "行业动态", "产品发布", "技术资讯"],
    "生活服务": ["购物消费", "出行交通", "本地生活", "健康养生", "家居生活", "美食"],
    "娱乐休闲": ["视频", "音乐", "游戏", "动漫", "社交", "阅读"],
    "其他": ["未分类"],
}


def _taxonomy_text() -> str:
    """把 8 类体系渲染成 prompt 文本"""
    lines = []
    for l1, l2s in L1_TAXONOMY.items():
        lines.append(f"{l1}: {'、'.join(l2s)}")
    return "\n".join(lines)


def _normalize_l1(l1: str) -> str:
    """硬校验：l1 必须属于 8 类体系，模糊匹配后仍不匹配则归「其他」"""
    l1 = l1.strip()
    if not l1:
        return "其他"
    if l1 in L1_TAXONOMY:
        return l1
    # 模糊匹配（包含关系）——注意空串是任意字符串子串，已在上面排除
    for valid in L1_TAXONOMY:
        if valid in l1 or l1 in valid:
            return valid
    return "其他"


def _normalize_l2(l1: str, l2: str) -> str:
    """硬校验：l2 必须属于该 l1 的推荐清单，模糊匹配后仍不匹配则归「未分类」"""
    l2 = l2.strip()
    if not l2:
        return "未分类"
    valid = L1_TAXONOMY.get(l1, ["未分类"])
    if l2 in valid:
        return l2
    for v in valid:
        if v in l2 or l2 in v:
            return v
    return "未分类"


# ──────────────────────────────────────────────
#  Prompt 构建
# ──────────────────────────────────────────────

def build_classify_prompt(bookmark_info: dict, categories: list[dict] | None = None) -> tuple[str, str]:
    """
    构建标签生成 prompt (system + user)。

    AI 只生成 10 个规范标签 + 一句话摘要，**不直接输出分类**。
    两级分类由服务端按标签频率聚类（见 modules/tag_classifier.py）——
    确定性、可解释、不会碎片化。

    bookmark_info: {title, url, domain, description, keywords, text}
    categories: 保留参数（兼容），不再使用
    """
    system = (
        "你是一个专业的网页内容分析助手。\n"
        "任务: 根据用户提供的网页信息，为书签生成 10 个关键词标签和一句话摘要。\n"
        "要求:\n"
        "1. 标签必须准确概括网页的主题、内容类型、技术栈或用途，用 2-6 字中文词或常见英文技术词\n"
        "2. 相同主题必须使用完全相同的标签词，禁止同义变体（例如「教程」和「学习教程」只能选一个）\n"
        "3. 标签不要带 emoji、标点或编号，每个标签独立\n"
        "4. 摘要用一句话概括网页内容（≤50字）\n"
        "5. 严格输出 JSON 格式，不要输出其他内容\n\n"
        "输出格式示例:\n"
        '{"tags": ["docker", "容器", "部署", "教程", "运维"], "summary": "Docker 容器化部署入门教程"}\n'
    )

    # User prompt
    title = bookmark_info.get("title", "")[:200]
    url = bookmark_info.get("url", "")
    domain = bookmark_info.get("domain", "")
    desc = bookmark_info.get("description", "")[:300]
    keywords = bookmark_info.get("keywords", [])
    summary = (bookmark_info.get("summary") or bookmark_info.get("text") or "")[:300]
    kw_str = "、".join(keywords[:10]) if keywords else "无"

    user = (
        f"网页信息:\n"
        f"  标题: {title}\n"
        f"  URL: {url}\n"
        f"  域名: {domain}\n"
        f"  描述: {desc}\n"
        f"  关键词: {kw_str}\n"
        f"  页面摘要: {summary}\n\n"
        f'请直接输出 JSON: {{"tags": ["标签1", "标签2", ...], "summary": "..."}}'
    )

    return system, user


def parse_tags_response(response_text: str) -> tuple[list[str], str]:
    """解析标签生成响应: (tags, summary)。容错处理 ```json 包裹，tags 去 emoji/空值"""
    import re
    text = (response_text or "").strip()
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
        raise ValueError(f"无法解析AI响应: {(response_text or '')[:200]}")
    tags = [re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", str(t)).strip()[:20]
            for t in (data.get("tags") or [])]
    tags = [t for t in tags if t][:20]
    summary = str(data.get("summary", "")).strip()[:100]
    return tags, summary


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
        # ── 方案 A: 固定 8 类体系，l1/l2 硬校验（模糊匹配 → 兜底）──
        import re
        l1 = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", l1).strip()[:20]
        l2 = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", l2).strip()[:20]
        l1 = _normalize_l1(l1)
        l2 = _normalize_l2(l1, l2)
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
            result.tags = list(cached.get("tags", []) or [])
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

                # 解析标签（分类由服务端按标签频率聚类）
                tags, summary = parse_tags_response(response)
                result.tags = tags
                result.summary = summary
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

"""
fetcher.py - 网页抓取模块
引擎: Scrapling (主) + Firecrawl (兜底)
功能: 抓取网页标题/描述/正文/关键词，用于辅助分类
特性: 代理支持 / 重试 / 超时 / 并发 / UA轮换 / 绕过规则
"""

import re
import json
import time
import threading
import logging
import hashlib
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime
from urllib.parse import urlparse

import requests

logger = logging.getLogger("fetcher")

# ──────────────────────────────────────────────
#  常量
# ──────────────────────────────────────────────

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

UA_POOL = [
    DEFAULT_UA,
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

# 不抓取的内容类型
SKIP_CONTENT_TYPES = ["application/pdf", "image/", "video/", "audio/", "application/zip"]

# 抓取结果缓存版本
FETCH_CACHE_VERSION = "1"


# ──────────────────────────────────────────────
#  数据类
# ──────────────────────────────────────────────

class FetchResult:
    """单次抓取结果"""

    def __init__(self, url: str, success: bool = False):
        self.url = url
        self.success = success
        self.status_code: int = 0
        self.title: str = ""
        self.description: str = ""
        self.keywords: list[str] = []
        self.text: str = ""          # 正文文本（截断）
        self.content_type: str = ""
        self.final_url: str = ""     # 重定向后的 URL
        self.engine: str = ""        # scrapling / firecrawl / requests
        self.error: str = ""
        self.elapsed_ms: int = 0
        self.timestamp: int = int(time.time())

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "success": self.success,
            "status_code": self.status_code,
            "title": self.title,
            "description": self.description,
            "keywords": self.keywords,
            "text": self.text[:500] if self.text else "",
            "content_type": self.content_type,
            "final_url": self.final_url,
            "engine": self.engine,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "timestamp": self.timestamp,
        }

    def get_search_text(self) -> str:
        """获取用于分类搜索的聚合文本"""
        parts = [self.title, self.description, " ".join(self.keywords), self.text[:300]]
        return " ".join(p for p in parts if p).strip()[:800]


# ──────────────────────────────────────────────
#  抓取缓存
# ──────────────────────────────────────────────

class FetchCache:
    """抓取结果缓存（避免重复请求同一 URL）"""

    def __init__(self, cache_dir: str = "data/cache/fetch"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "fetch_cache.json"
        self._data: dict = {"version": FETCH_CACHE_VERSION, "entries": {}}
        self._hits: int = 0
        self._misses: int = 0
        self.load()

    def load(self):
        if not self.cache_file.exists():
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            if self._data.get("version") != FETCH_CACHE_VERSION:
                self._data = {"version": FETCH_CACHE_VERSION, "entries": {}}
        except (json.JSONDecodeError, OSError):
            self._data = {"version": FETCH_CACHE_VERSION, "entries": {}}

    def save(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"抓取缓存写入失败: {e}")

    def get(self, url: str) -> Optional[dict]:
        key = self._hash(url)
        entry = self._data.get("entries", {}).get(key)
        if entry:
            self._hits += 1
            return entry
        self._misses += 1
        return None

    def set(self, url: str, result: FetchResult):
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
        self._data = {"version": FETCH_CACHE_VERSION, "entries": {}}
        self.save()
        logger.info(f"抓取缓存已清空 ({count} 条)")

    @staticmethod
    def _hash(url: str) -> str:
        normalized = url.strip().rstrip("/").lower()
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]


# ──────────────────────────────────────────────
#  代理适配器
# ──────────────────────────────────────────────

class ProxyAdapter:
    """将 ProxyManager 的配置适配为 requests 可用的格式"""

    def __init__(self, proxy_manager=None, config: dict = None):
        self.proxy_manager = proxy_manager
        self.config = config or {}
        self._proxies: Optional[dict] = None
        self._enabled: bool = False
        self._bypass_domains: list[str] = []
        self.refresh()

    def refresh(self):
        """从 proxy_manager 或 config 刷新代理设置"""
        if self.proxy_manager:
            self._enabled = self.proxy_manager.is_enabled()
            self._proxies = self.proxy_manager.get_proxies()

            # 绕过域名：从 ProxyManager 的 config 读取
            self._bypass_domains = []
            # 尝试从 proxy_manager 的 config 获取
            cfg = getattr(self.proxy_manager, 'config', None)
            if cfg:
                bd = cfg.get("proxy.bypass_domains", [])
                self._bypass_domains.extend(bd)

            # 抓取专用绕过
            fetch_cfg = self.config.get("fetch", {}) if self.config else {}
            if fetch_cfg.get("bypass_domains"):
                self._bypass_domains.extend(fetch_cfg["bypass_domains"])
        else:
            # 从 config 直接读取
            proxy_cfg = self.config.get("proxy", {}) if self.config else {}
            self._enabled = proxy_cfg.get("enabled", False)
            if self._enabled:
                custom = proxy_cfg.get("custom", {})
                if custom.get("enabled"):
                    ptype = custom.get("type", "http")
                    host = custom.get("host", "127.0.0.1")
                    port = custom.get("port", 7890)
                    self._proxies = {
                        "http": f"{ptype}://{host}:{port}",
                        "https": f"{ptype}://{host}:{port}",
                    }
            self._bypass_domains = proxy_cfg.get("bypass_domains", [])

        # 去重
        self._bypass_domains = list(set(self._bypass_domains))
        logger.info(f"代理适配: enabled={self._enabled}, bypass={len(self._bypass_domains)}个域名")

    def should_bypass(self, url: str) -> bool:
        """判断 URL 是否应绕过代理"""
        try:
            host = urlparse(url).hostname or ""
            for domain in self._bypass_domains:
                if domain in host:
                    return True
        except Exception:
            pass
        return False

    def get_proxies(self, url: str) -> Optional[dict]:
        """获取该 URL 应使用的代理（None = 直连）"""
        if not self._enabled:
            return None
        if self.should_bypass(url):
            return None
        return self._proxies


# ──────────────────────────────────────────────
#  HTML 解析工具
# ──────────────────────────────────────────────

def _extract_title(html: str) -> str:
    """从 HTML 提取标题"""
    # <title> 标签
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        title = m.group(1).strip()
        # 清理空白
        title = re.sub(r"\s+", " ", title)
        # 去除常见后缀
        title = re.sub(r"[\s\-_|·]+$", "", title)
        return title[:200]
    return ""

def _extract_description(html: str) -> str:
    """提取 meta description"""
    # name="description"
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        return m.group(1).strip()[:500]
    # property="og:description"
    m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        return m.group(1).strip()[:500]
    # name="twitter:description"
    m = re.search(r'<meta[^>]+name=["\']twitter:description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        return m.group(1).strip()[:500]
    return ""

def _extract_keywords(html: str) -> list[str]:
    """提取关键词（去重保序）"""
    # name="keywords"
    m = re.search(r'<meta[^>]+name=["\']keywords["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        raw = m.group(1).strip()
        seen = set()
        result = []
        for kw in re.split(r"[,，;；|]", raw):
            kw = kw.strip()
            if kw and kw.lower() not in seen:
                seen.add(kw.lower())
                result.append(kw)
        return result[:20]
    # property="og:keywords"
    m = re.search(r'<meta[^>]+property=["\']og:keywords["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        raw = m.group(1).strip()
        seen = set()
        result = []
        for kw in re.split(r"[,，;；|]", raw):
            kw = kw.strip()
            if kw and kw.lower() not in seen:
                seen.add(kw.lower())
                result.append(kw)
        return result[:20]
    return []

def _extract_text(html: str, max_len: int = 1000) -> str:
    """提取正文文本（简单启发式）"""
    # 去除 script/style
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<noscript[^>]*>.*?</noscript>", " ", html, flags=re.I | re.S)
    # 去除所有标签
    text = re.sub(r"<[^>]+>", " ", html)
    # 解码 HTML 实体
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
    text = text.replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    text = text.replace("&hellip;", "...").replace("&mdash;", "—")
    # 清理空白
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    text = text.strip()
    return text[:max_len]


# ──────────────────────────────────────────────
#  主抓取器
# ──────────────────────────────────────────────

class WebFetcher:
    """
    网页抓取器

    策略:
    1. 缓存查询 → 命中直接返回
    2. Scrapling 引擎抓取（如果可用）
    3. 失败 → requests 兜底
    4. 仍失败 → Firecrawl API 兜底（如果配置）
    """

    def __init__(self, config: dict = None, proxy_adapter: Optional[ProxyAdapter] = None):
        self.config = config or {}
        self.proxy = proxy_adapter or ProxyAdapter(config=config)

        fetch_cfg = self.config.get("fetch", {})
        self.timeout = fetch_cfg.get("timeout", 10)
        self.max_retries = fetch_cfg.get("max_retries", 2)
        self.concurrency = fetch_cfg.get("concurrency", 5)
        self.user_agent = fetch_cfg.get("user_agent", DEFAULT_UA)
        self.fallback_to_firecrawl = fetch_cfg.get("fallback_to_firecrawl", True)

        # Firecrawl 配置
        fc_cfg = self.config.get("firecrawl", {})
        self.firecrawl_enabled = fc_cfg.get("enabled", False)
        self.firecrawl_api_url = fc_cfg.get("api_url", "")
        self.firecrawl_api_key = ""  # 从 SecureStore 获取
        self.firecrawl_timeout = fc_cfg.get("timeout", 30)

        # 缓存
        cache_dir = self.config.get("classification", {}).get("cache_dir", "data/cache")
        self.cache = FetchCache(cache_dir=f"{cache_dir}/fetch")

        # 统计
        self._stats = {"total": 0, "success": 0, "failed": 0, "cached": 0,
                       "scrapling": 0, "requests": 0, "firecrawl": 0}
        # 并行安全锁（保护 stats / cache 共享状态）
        self._lock = threading.Lock()

        # 检查 Scrapling 可用性
        self._scrapling_available = self._check_scrapling()
        if self._scrapling_available:
            logger.info("✅ Scrapling 可用，作为首选引擎")
        else:
            logger.info("⚠️ Scrapling 未安装，使用 requests 作为主引擎")

    def _check_scrapling(self) -> bool:
        try:
            import scrapling
            return True
        except ImportError:
            return False

    def set_firecrawl_key(self, api_key: str):
        """设置 Firecrawl API Key"""
        self.firecrawl_api_key = api_key

    # ──────────────────────────────────────────────
    #  单条抓取
    # ──────────────────────────────────────────────

    def fetch(self, url: str) -> FetchResult:
        """抓取单个 URL，返回 FetchResult（线程安全，可并行调用）"""
        with self._lock:
            self._stats["total"] += 1
            # 1. 缓存查询
            cached = self.cache.get(url)
        if cached:
            with self._lock:
                self._stats["cached"] += 1
            result = FetchResult(url, success=cached.get("success", False))
            result.__dict__.update(cached)
            return result

        # 2. 检查内容类型（跳过明显不需要抓取的）
        if self._should_skip(url):
            result = FetchResult(url, success=False)
            result.error = "跳过: 非HTML内容或已知不可抓取域名"
            with self._lock:
                self._stats["failed"] += 1
            return result

        # 3. 尝试抓取
        result = self._try_fetch(url)

        # 4. 缓存结果（写盘串行化，避免并行写竞争）
        with self._lock:
            self.cache.set(url, result)
            # 每 20 条落盘一次（按计数而非字典长度——len(dict) 恒为键数，永远不等于 0）
            if self._stats["total"] % 20 == 0:
                self.cache.save()

        return result

    def _try_fetch(self, url: str) -> FetchResult:
        """尝试抓取，含重试和引擎降级"""
        last_error = ""

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                # 退避
                backoff = min(2 ** attempt, 5)
                logger.debug(f"  重试 {attempt}/{self.max_retries} (等待 {backoff}s)")
                time.sleep(backoff)

            # 方法1: Scrapling
            if self._scrapling_available:
                result = self._fetch_scrapling(url)
                if result.success:
                    self._stats["scrapling"] += 1
                    self._stats["success"] += 1
                    return result
                last_error = result.error

            # 方法2: requests 直接抓取
            result = self._fetch_requests(url)
            if result.success:
                self._stats["requests"] += 1
                self._stats["success"] += 1
                return result
            last_error = result.error

            # 方法3: Firecrawl API
            if self.fallback_to_firecrawl and self.firecrawl_enabled and self.firecrawl_api_key:
                result = self._fetch_firecrawl(url)
                if result.success:
                    self._stats["firecrawl"] += 1
                    self._stats["success"] += 1
                    return result
                last_error = result.error

        # 全部失败
        self._stats["failed"] += 1
        result = FetchResult(url, success=False)
        result.error = f"全部引擎失败: {last_error}"
        return result

    def _should_skip(self, url: str) -> bool:
        """判断是否应跳过"""
        skip_patterns = [
            "youtube.com/watch", "youtube.com/shorts",  # 视频页无有意义文本
            "twitter.com/", "x.com/",                    # SPA + 反爬
            "facebook.com/",                              # 反爬
            "instagram.com/",                             # 反爬
            "tiktok.com/",                                # SPA
            ".pdf", ".zip", ".rar", ".7z",               # 二进制
            ".mp4", ".mp3", ".wav", ".avi",              # 媒体
            ".png", ".jpg", ".jpeg", ".gif", ".webp",    # 图片
            "chrome://", "edge://", "about:",             # 浏览器内部页
            "file://",                                    # 本地文件
        ]
        url_lower = url.lower()
        return any(p in url_lower for p in skip_patterns)

    # ──────────────────────────────────────────────
    #  引擎: Scrapling
    # ──────────────────────────────────────────────

    def _fetch_scrapling(self, url: str) -> FetchResult:
        """使用 Scrapling 抓取"""
        result = FetchResult(url)
        start = time.time()
        try:
            from scrapling import ScraplingFetcher

            fetcher = ScraplingFetcher(
                url=url,
                timeout=self.timeout,
                headers={"User-Agent": self._random_ua()},
                proxies=self.proxy.get_proxies(url),
            )
            response = fetcher.fetch()

            html = response.text if hasattr(response, 'text') else str(response)
            result.status_code = getattr(response, 'status_code', 200)
            result.final_url = getattr(response, 'url', url)
            result.content_type = "text/html"
            result.engine = "scrapling"

            # 解析
            result.title = _extract_title(html)
            result.description = _extract_description(html)
            result.keywords = _extract_keywords(html)
            result.text = _extract_text(html)

            if result.title or result.text:
                result.success = True
            else:
                result.success = False
                result.error = "Scrapling 返回空内容"

        except ImportError:
            result.error = "Scrapling 未安装"
            result.success = False
        except Exception as e:
            result.error = f"Scrapling 异常: {type(e).__name__}: {str(e)[:100]}"
            result.success = False

        result.elapsed_ms = int((time.time() - start) * 1000)
        return result

    # ──────────────────────────────────────────────
    #  引擎: requests (兜底)
    # ──────────────────────────────────────────────

    def _fetch_requests(self, url: str) -> FetchResult:
        """使用 requests 直接抓取"""
        result = FetchResult(url)
        start = time.time()
        try:
            proxies = self.proxy.get_proxies(url)
            headers = {
                "User-Agent": self._random_ua(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }

            resp = requests.get(
                url,
                timeout=self.timeout,
                headers=headers,
                proxies=proxies,
                allow_redirects=True,
                verify=True,
            )
            result.status_code = resp.status_code
            result.final_url = resp.url
            result.elapsed_ms = int((time.time() - start) * 1000)

            # 检查内容类型
            content_type = resp.headers.get("Content-Type", "").lower()
            result.content_type = content_type
            if any(ct in content_type for ct in SKIP_CONTENT_TYPES):
                result.success = False
                result.error = f"非HTML内容: {content_type}"
                return result

            if resp.status_code != 200:
                result.success = False
                result.error = f"HTTP {resp.status_code}"
                return result

            # 编码处理
            if resp.encoding is None or resp.encoding == "ISO-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"

            html = resp.text
            result.engine = "requests"

            # 解析
            result.title = _extract_title(html)
            result.description = _extract_description(html)
            result.keywords = _extract_keywords(html)
            result.text = _extract_text(html)

            if result.title or len(result.text) > 50:
                result.success = True
            else:
                result.success = False
                result.error = "内容为空或过短"

        except requests.exceptions.Timeout:
            result.error = f"超时 ({self.timeout}s)"
            result.success = False
        except requests.exceptions.ConnectionError as e:
            result.error = f"连接失败: {str(e)[:80]}"
            result.success = False
        except requests.exceptions.SSLError as e:
            result.error = f"SSL错误: {str(e)[:80]}"
            result.success = False
        except Exception as e:
            result.error = f"requests 异常: {type(e).__name__}: {str(e)[:80]}"
            result.success = False

        if not result.elapsed_ms:
            result.elapsed_ms = int((time.time() - start) * 1000)
        return result

    # ──────────────────────────────────────────────
    #  引擎: Firecrawl API (终极兜底)
    # ──────────────────────────────────────────────

    def _fetch_firecrawl(self, url: str) -> FetchResult:
        """使用 Firecrawl API 抓取"""
        result = FetchResult(url)
        start = time.time()
        try:
            api_url = f"{self.firecrawl_api_url.rstrip('/')}/scrape"
            headers = {
                "Authorization": f"Bearer {self.firecrawl_api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "url": url,
                "formats": ["markdown", "html"],
                "onlyMainContent": True,
                "timeout": self.firecrawl_timeout * 1000,
            }

            # Firecrawl 也走代理（如果配置了）
            proxies = self.proxy.get_proxies(self.firecrawl_api_url)

            resp = requests.post(
                api_url,
                json=payload,
                headers=headers,
                timeout=self.firecrawl_timeout,
                proxies=proxies,
            )

            result.elapsed_ms = int((time.time() - start) * 1000)
            result.engine = "firecrawl"

            if resp.status_code != 200:
                result.error = f"Firecrawl HTTP {resp.status_code}: {resp.text[:100]}"
                result.success = False
                return result

            data = resp.json()
            if data.get("success") and data.get("data"):
                d = data["data"]
                result.title = d.get("metadata", {}).get("title", "") or d.get("title", "")
                result.description = d.get("metadata", {}).get("description", "") or ""
                result.keywords = d.get("metadata", {}).get("keywords", []) or []
                # markdown 转纯文本
                md = d.get("markdown", "") or ""
                text = re.sub(r"[#*_\[\]\(\)`\-\n\r]", " ", md)
                result.text = re.sub(r"\s+", " ", text).strip()[:1000]
                result.content_type = "text/markdown"
                result.status_code = 200
                result.success = True
            else:
                result.error = f"Firecrawl 返回失败: {data.get('error', 'unknown')}"
                result.success = False

        except Exception as e:
            result.error = f"Firecrawl 异常: {type(e).__name__}: {str(e)[:80]}"
            result.success = False

        if not result.elapsed_ms:
            result.elapsed_ms = int((time.time() - start) * 1000)
        return result

    # ──────────────────────────────────────────────
    #  批量抓取
    # ──────────────────────────────────────────────

    def fetch_many(self, urls: list[str], progress_cb: Optional[Callable] = None) -> list[FetchResult]:
        """
        批量抓取（串行，带进度回调）
        大量 URL 请用 fetch_many_parallel
        """
        results: list[FetchResult] = []
        total = len(urls)

        for i, url in enumerate(urls):
            result = self.fetch(url)
            results.append(result)

            if progress_cb:
                progress_cb(i + 1, total, result)

            # 每 50 条保存一次缓存
            if (i + 1) % 50 == 0:
                self.cache.save()

        self.cache.save()
        return results

    def fetch_many_parallel(self, urls: list[str], progress_cb: Optional[Callable] = None,
                            max_workers: Optional[int] = None) -> list[FetchResult]:
        """
        批量并行抓取（ThreadPoolExecutor，线程安全）。
        进度回调在调用线程串行触发（done_count, total, result）。
        """
        import concurrent.futures
        workers = max_workers or self.concurrency or 5
        total = len(urls)
        results: list[FetchResult] = []
        done = 0
        results_lock = threading.Lock()

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="fetch") as executor:
            future_map = {executor.submit(self.fetch, u): u for u in urls}
            for fut in concurrent.futures.as_completed(future_map):
                url = future_map[fut]
                try:
                    result = fut.result()
                except Exception as e:
                    result = FetchResult(url, success=False)
                    result.error = f"抓取异常: {type(e).__name__}: {str(e)[:80]}"
                with results_lock:
                    results.append(result)
                    done += 1
                if progress_cb:
                    try:
                        progress_cb(done, total, result)
                    except Exception:
                        pass

        self.cache.save()
        return results

    def fetch_for_bookmarks(self, bookmarks: list, progress_cb: Optional[Callable] = None) -> dict[str, FetchResult]:
        """
        对书签列表抓取（仅抓取未分类或分类为"其他"的）
        返回: {url: FetchResult}
        """
        # 筛选需要抓取的
        to_fetch = []
        for bm in bookmarks:
            if bm.user_deleted:
                continue
            # 已分类且置信度高的跳过
            if bm.category_l1 and bm.category_l1 != "其他" and bm.confidence >= 0.8:
                continue
            to_fetch.append(bm.url)

        # 去重
        seen = set()
        unique_urls = []
        for url in to_fetch:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        logger.info(f"待抓取: {len(unique_urls)} 个唯一 URL (从 {len(bookmarks)} 条书签中筛选)")
        self.append_log = progress_cb  # type: ignore

        results = self.fetch_many(unique_urls, progress_cb)
        return {r.url: r for r in results}

    # ──────────────────────────────────────────────
    #  工具
    # ──────────────────────────────────────────────

    def _random_ua(self) -> str:
        """随机 UA"""
        import random
        return random.choice(UA_POOL)

    def get_stats(self) -> dict:
        """获取统计"""
        s = dict(self._stats)
        s["cache"] = self.cache.stats()
        return s

    def print_stats(self):
        """打印统计"""
        s = self.get_stats()
        logger.info("=" * 50)
        logger.info("📊 抓取统计")
        logger.info("=" * 50)
        logger.info(f"  总计: {s['total']} | 成功: {s['success']} | 失败: {s['failed']} | 缓存命中: {s['cached']}")
        logger.info(f"  引擎: scrapling={s['scrapling']} requests={s['requests']} firecrawl={s['firecrawl']}")
        if s.get("cache"):
            cs = s["cache"]
            logger.info(f"  缓存: {cs['total']}条 | 命中率: {cs['hit_rate']*100:.0f}%")
        logger.info("=" * 50)

    def reset_stats(self):
        self._stats = {"total": 0, "success": 0, "failed": 0, "cached": 0,
                       "scrapling": 0, "requests": 0, "firecrawl": 0}

    def save_cache(self):
        self.cache.save()

    def clear_cache(self):
        self.cache.clear()
        self.reset_stats()


# ──────────────────────────────────────────────
#  便捷函数
# ──────────────────────────────────────────────

def quick_fetch(url: str, config: dict = None, use_proxy: bool = False) -> FetchResult:
    """快速抓取单个 URL（不缓存）"""
    fetcher = WebFetcher(config=config)
    if not use_proxy:
        fetcher.proxy = ProxyAdapter(config={"proxy": {"enabled": False}})
    return fetcher.fetch(url)


def test_connectivity(url: str = "https://www.google.com", proxy_url: str = "") -> dict:
    """测试代理连通性"""
    result = {"url": url, "proxy": proxy_url or "direct", "success": False, "elapsed_ms": 0, "error": ""}
    start = time.time()
    try:
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        resp = requests.get(url, timeout=10, proxies=proxies, headers={"User-Agent": DEFAULT_UA})
        result["elapsed_ms"] = int((time.time() - start) * 1000)
        result["status_code"] = resp.status_code
        result["success"] = resp.status_code == 200
        if not result["success"]:
            result["error"] = f"HTTP {resp.status_code}"
    except Exception as e:
        result["elapsed_ms"] = int((time.time() - start) * 1000)
        result["error"] = f"{type(e).__name__}: {str(e)[:80]}"
    return result

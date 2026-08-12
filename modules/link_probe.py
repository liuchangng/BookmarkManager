"""
link_probe.py - URL 体检器（T1，design §6 C1）
功能:
  1. 本地/内网地址判定 is_local_url()（纯函数、零网络）
  2. 死链探活 probe_urls()：HEAD 优先 → GET 兜底；缓存复用；连续失败才标 dead（防误判）

设计约定:
  - 系统级桶判定（本地/失效），不参与规则引擎（classifier 不感知 status）
  - 状态: ok / local / dead / pending（pending = 失败一次待二次确认）
  - 404/410 为确定性死链（一次即 dead）；网络错误（DNS/超时/SSL/连接）需连续
    max_fail_confirm 次失败才标 dead
"""

import hashlib
import ipaddress
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger("link_probe")

PROBE_CACHE_VERSION = "1"

# 本地/浏览器内部协议（前缀匹配）
LOCAL_SCHEME_PREFIXES = (
    "file://", "chrome://", "edge://", "about:", "javascript:", "data:",
    "view-source:", "devtools://", "opera://", "vivaldi://", "brave://",
    "moz-extension://", "chrome-extension://", "resource://",
)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


# ──────────────────────────────────────────────
#  数据类
# ──────────────────────────────────────────────

@dataclass
class LinkProbeResult:
    """单条 URL 体检结果"""
    url: str
    status: str = "pending"   # ok / local / dead / pending
    http_status: int = 0      # 探活 HTTP 状态码
    error: str = ""           # 原因（DNS/404/超时/SSL/本地地址）
    checked_at: int = 0       # Unix 秒
    method: str = ""          # head / get / local
    attempts: int = 0         # 连续失败次数

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "status": self.status,
            "http_status": self.http_status,
            "error": self.error,
            "checked_at": self.checked_at,
            "method": self.method,
            "attempts": self.attempts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LinkProbeResult":
        return cls(
            url=d.get("url", ""),
            status=d.get("status", "pending"),
            http_status=d.get("http_status", 0),
            error=d.get("error", ""),
            checked_at=d.get("checked_at", 0),
            method=d.get("method", ""),
            attempts=d.get("attempts", 0),
        )


# ──────────────────────────────────────────────
#  本地/内网判定（纯函数）
# ──────────────────────────────────────────────

def is_local_url(url: str) -> bool:
    """
    判定 URL 是否为本地/内网地址（不发起任何网络请求）

    覆盖:
      - 本地协议: file:// chrome:// edge:// about: javascript: data: 等
      - UNC 路径: \\\\server\\share
      - 盘符路径: C:/... C:\\...
      - 主机名: localhost / *.localhost / *.local
      - IP: 回环(127.*, ::1) / 私网(10.*, 172.16-31.*, 192.168.*, 100.64/10 等)
            / 链路本地(169.254.*, fe80::)
    """
    if not url:
        return False
    low = url.strip().lower()
    if not low:
        return False

    # 本地协议前缀
    if low.startswith(LOCAL_SCHEME_PREFIXES):
        return True

    # UNC 路径 \\server\share
    if low.startswith("\\\\"):
        return True

    # 盘符路径 C:\... 或 C:/...
    if len(url) >= 3 and url[0].isalpha() and url[1] == ":" and url[2] in "/\\":
        return True

    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        # 无主机名（裸字符串/裸路径）：不是本地地址，交给探活判断
        return False

    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return True

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


# ──────────────────────────────────────────────
#  探活缓存
# ──────────────────────────────────────────────

class LinkProbeCache:
    """探活结果缓存（data/cache/probe/probe_cache.json），避免重复探测同一 URL"""

    def __init__(self, cache_dir: str = "data/cache/probe"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "probe_cache.json"
        self._data: dict = {"version": PROBE_CACHE_VERSION, "entries": {}}
        self._hits: int = 0
        self._misses: int = 0
        self.load()

    def load(self):
        if not self.cache_file.exists():
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            if self._data.get("version") != PROBE_CACHE_VERSION:
                self._data = {"version": PROBE_CACHE_VERSION, "entries": {}}
        except (json.JSONDecodeError, OSError):
            self._data = {"version": PROBE_CACHE_VERSION, "entries": {}}

    def save(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"探活缓存写入失败: {e}")

    def get(self, url: str) -> Optional[dict]:
        key = self._hash(url)
        entry = self._data.get("entries", {}).get(key)
        if entry:
            self._hits += 1
            return entry
        self._misses += 1
        return None

    def set(self, url: str, result: LinkProbeResult):
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
        self._data = {"version": PROBE_CACHE_VERSION, "entries": {}}
        self.save()
        logger.info(f"探活缓存已清空 ({count} 条)")

    @staticmethod
    def _hash(url: str) -> str:
        normalized = url.strip().rstrip("/").lower()
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]


# ──────────────────────────────────────────────
#  单次探测
# ──────────────────────────────────────────────

def _classify_status(code: int) -> tuple[str, str]:
    """按 HTTP 状态码分类"""
    if 200 <= code < 400:
        return "ok", ""
    if code in (404, 410):
        return "dead", f"HTTP {code}"          # 确定性死链
    if 400 <= code < 500:
        return "ok", f"HTTP {code}"            # 403/401 等: 站点存在(反爬/鉴权)，不算死链
    return "fail", f"HTTP {code}"              # 5xx: 服务端错误，可能瞬时


def _classify_exception(e: Exception) -> tuple[str, int, str]:
    if isinstance(e, requests.exceptions.SSLError):
        return "fail", 0, "SSL 错误"
    if isinstance(e, requests.exceptions.Timeout):
        return "fail", 0, "超时"
    if isinstance(e, requests.exceptions.ConnectionError):
        msg = str(e)
        if "getaddrinfo" in msg or "Name or service not known" in msg:
            return "fail", 0, "域名不存在"
        return "fail", 0, f"连接失败: {msg[:60]}"
    return "fail", 0, f"{type(e).__name__}: {str(e)[:60]}"


def _check_once(url: str, timeout: float) -> tuple[str, int, str, str]:
    """
    单次探测: 返回 (status: ok|dead|fail, http_status, error, method)
    HEAD 优先（405 → GET 兜底，GET 用 stream 不下载正文）
    """
    headers = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}

    # 1) HEAD
    code = 0
    try:
        with requests.Session() as s:
            resp = s.head(url, timeout=timeout, allow_redirects=True, headers=headers)
            code = resp.status_code
    except requests.exceptions.RequestException as e:
        status, hcode, error = _classify_exception(e)
        return status, hcode, error, "head"

    if code != 405:
        status, error = _classify_status(code)
        return status, code, error, "head"

    # 2) GET 兜底（不下载正文）
    try:
        with requests.Session() as s:
            resp = s.get(url, timeout=timeout, allow_redirects=True, headers=headers, stream=True)
            with resp:
                code = resp.status_code
    except requests.exceptions.RequestException as e:
        status, hcode, error = _classify_exception(e)
        return status, hcode, error, "get"

    status, error = _classify_status(code)
    return status, code, error, "get"


# ──────────────────────────────────────────────
#  批量探活（并发 + 防误判 + 缓存）
# ──────────────────────────────────────────────

def probe_urls(urls: list[str], *, timeout: float = 3.0, max_fail_confirm: int = 2,
               max_age_seconds: int = 7 * 24 * 3600, cache: Optional[LinkProbeCache] = None,
               progress_cb: Optional[Callable[[LinkProbeResult], None]] = None,
               max_workers: int = 8,
               is_local: Optional[Callable[[str], bool]] = None) -> dict[str, LinkProbeResult]:
    """
    批量探活
      - 本地/内网地址: 直接 local，不发起网络请求（判定函数可注入，便于测试）
      - 缓存命中(ok/dead 且未过期): 直接复用
      - 缓存中的 pending: 累计 attempts 重探（防误判）
      - 404/410: 一次即 dead；网络错误需连续 max_fail_confirm 次失败才标 dead

    返回: {url: LinkProbeResult}
    """
    is_local_fn = is_local or is_local_url
    results: dict[str, LinkProbeResult] = {}
    pending: list[tuple[str, int]] = []   # (url, 历史失败次数)
    now = int(time.time())

    seen = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)

        if is_local_fn(url):
            results[url] = LinkProbeResult(
                url, status="local", checked_at=now, method="local", error="本地/内网地址"
            )
            continue

        if cache:
            cached = cache.get(url)
            if cached:
                cr = LinkProbeResult.from_dict(cached)
                if cr.status in ("ok", "dead"):
                    # 过期则重探，避免永久陈旧（checked_at 与 now 同秒视为未过期）
                    if max_age_seconds and 0 <= (now - cr.checked_at) <= max_age_seconds:
                        results[url] = cr
                        continue
                else:
                    # pending: 之前失败过 → 累计失败次数继续探
                    pending.append((url, cr.attempts))
                    continue
        pending.append((url, 0))

    if pending:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_check_once, u, timeout): (u, prev) for u, prev in pending}
            for fut in as_completed(futures):
                url, prev_attempts = futures[fut]
                status, code, error, method = fut.result()

                if status == "ok":
                    result = LinkProbeResult(url, status="ok", http_status=code,
                                             checked_at=now, method=method)
                elif status == "dead":
                    result = LinkProbeResult(url, status="dead", http_status=code,
                                             error=error, checked_at=now, method=method)
                else:  # fail → 防误判
                    attempts = prev_attempts + 1
                    if attempts >= max_fail_confirm:
                        result = LinkProbeResult(url, status="dead", http_status=code,
                                                 error=error, checked_at=now,
                                                 method=method, attempts=attempts)
                    else:
                        result = LinkProbeResult(url, status="pending", http_status=code,
                                                 error=error, checked_at=now,
                                                 method=method, attempts=attempts)

                results[url] = result
                if cache:
                    cache.set(url, result)
                if progress_cb:
                    progress_cb(result)

    if cache and pending:
        cache.save()

    return results

"""
cache.py - 分类缓存模块
功能: 缓存已分类结果，避免重复处理相同 URL
格式: JSON 文件，key=URL hash, value=分类结果+时间戳
"""

import json
import hashlib
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger("cache")

# 缓存版本（修改分类逻辑时递增，触发全量刷新）
# v2: 二阶段规则（T2）——关键词规则匹配文本增加 page_summary 维度
CACHE_VERSION = "2"


class ClassifyCache:
    """
    分类结果缓存

    存储结构:
    {
        "version": "1",
        "updated": "2025-07-23T10:00:00",
        "entries": {
            "<url_hash>": {
                "url": "...",
                "domain": "...",
                "category_l1": "...",
                "category_l2": "...",
                "method": "rule|ai|manual",
                "confidence": 0.95,
                "timestamp": 1234567890,
            }
        }
    }
    """

    def __init__(self, cache_dir: str = "data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "classify_cache.json"
        self._data: dict = {"version": CACHE_VERSION, "entries": {}}
        self._dirty: bool = False
        self._hits: int = 0
        self._misses: int = 0
        self.load()

    # ──────────────────────────────────────────────
    #  持久化
    # ──────────────────────────────────────────────

    def load(self):
        """从磁盘加载缓存"""
        if not self.cache_file.exists():
            logger.debug("缓存文件不存在，使用空缓存")
            return

        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self._data = json.load(f)

            # 版本检查
            if self._data.get("version") != CACHE_VERSION:
                logger.info(f"缓存版本不匹配 ({self._data.get('version')} → {CACHE_VERSION})，清空重建")
                self._data = {"version": CACHE_VERSION, "entries": {}}
                self._dirty = True
                self.save()

            count = len(self._data.get("entries", {}))
            logger.info(f"加载缓存: {count} 条记录")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"缓存文件损坏，重建: {e}")
            self._data = {"version": CACHE_VERSION, "entries": {}}
            self._dirty = True

    def save(self):
        """写入磁盘"""
        self._data["updated"] = datetime.now().isoformat()
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            self._dirty = False
        except OSError as e:
            logger.error(f"缓存写入失败: {e}")

    # ──────────────────────────────────────────────
    #  查询与写入
    # ──────────────────────────────────────────────

    def get(self, url: str) -> Optional[dict]:
        """查询缓存，命中返回分类信息，未命中返回 None"""
        key = self._hash(url)
        entry = self._data.get("entries", {}).get(key)
        if entry:
            self._hits += 1
            return entry
        self._misses += 1
        return None

    def set(self, url: str, category_l1: str, category_l2: str,
            method: str = "rule", confidence: float = 0.0):
        """写入缓存"""
        key = self._hash(url)
        self._data.setdefault("entries", {})[key] = {
            "url": url,
            "domain": self._extract_domain_for_cache(url),
            "category_l1": category_l1,
            "category_l2": category_l2,
            "method": method,
            "confidence": confidence,
            "timestamp": int(time.time()),
        }
        self._dirty = True

    def get_many(self, urls: list[str]) -> dict[str, dict]:
        """批量查询，返回 {url: entry} 仅包含命中的"""
        results: dict[str, dict] = {}
        for url in urls:
            entry = self.get(url)
            if entry:
                results[url] = entry
        return results

    def set_many(self, entries: list[dict]):
        """批量写入 [{url, category_l1, category_l2, method, confidence}, ...]"""
        for e in entries:
            self.set(
                e["url"],
                e.get("category_l1", ""),
                e.get("category_l2", ""),
                e.get("method", "rule"),
                e.get("confidence", 0.0),
            )

    def fill_bookmarks(self, bookmarks: list) -> int:
        """
        用缓存填充书签的分类信息
        返回: 填充的条数
        """
        filled = 0
        for bm in bookmarks:
            entry = self.get(bm.url)
            if entry:
                bm.category_l1 = entry["category_l1"]
                bm.category_l2 = entry["category_l2"]
                bm.classify_method = f"cache:{entry.get('method', 'unknown')}"
                bm.confidence = entry.get("confidence", 0.0)
                filled += 1
        if filled:
            logger.info(f"缓存填充: {filled} 条书签")
        return filled

    # ──────────────────────────────────────────────
    #  管理
    # ──────────────────────────────────────────────

    def invalidate(self, url: str):
        """使单条缓存失效"""
        key = self._hash(url)
        if key in self._data.get("entries", {}):
            del self._data["entries"][key]
            self._dirty = True

    def invalidate_pattern(self, pattern: str) -> int:
        """使匹配 pattern 的缓存失效（支持子串匹配 domain）"""
        removed = 0
        entries = self._data.get("entries", {})
        to_remove = []
        for key, entry in entries.items():
            domain = entry.get("domain", "")
            url = entry.get("url", "")
            if pattern in domain or pattern in url:
                to_remove.append(key)
        for key in to_remove:
            del entries[key]
            removed += 1
        if removed:
            self._dirty = True
            logger.info(f"缓存失效: 移除 {removed} 条匹配 '{pattern}'")
        return removed

    def clear(self):
        """清空所有缓存"""
        count = len(self._data.get("entries", {}))
        self._data = {"version": CACHE_VERSION, "entries": {}}
        self._dirty = True
        self.save()
        logger.info(f"缓存已清空 ({count} 条)")

    def stats(self) -> dict:
        """缓存统计"""
        entries = self._data.get("entries", {})
        methods: dict[str, int] = {}
        ages: list[int] = []
        now = int(time.time())

        for entry in entries.values():
            method = entry.get("method", "unknown")
            # 去掉 cache: 前缀
            if method.startswith("cache:"):
                method = method[6:]
            methods[method] = methods.get(method, 0) + 1
            age = now - entry.get("timestamp", now)
            ages.append(age)

        avg_age_days = (sum(ages) / len(ages) / 86400) if ages else 0

        return {
            "total": len(entries),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / (self._hits + self._misses) if (self._hits + self._misses) > 0 else 0,
            "methods": methods,
            "avg_age_days": round(avg_age_days, 1),
            "file_size_kb": round(self.cache_file.stat().st_size / 1024, 1) if self.cache_file.exists() else 0,
        }

    def cleanup_old(self, max_age_days: int = 180) -> int:
        """清理超过指定天数的旧缓存"""
        max_age_sec = max_age_days * 86400
        now = int(time.time())
        entries = self._data.get("entries", {})
        to_remove = []

        for key, entry in entries.items():
            age = now - entry.get("timestamp", now)
            if age > max_age_sec:
                to_remove.append(key)

        for key in to_remove:
            del entries[key]

        if to_remove:
            self._dirty = True
            self.save()
            logger.info(f"清理旧缓存: 移除 {len(to_remove)} 条 (>={max_age_days}天)")

        return len(to_remove)

    # ──────────────────────────────────────────────
    #  工具
    # ──────────────────────────────────────────────

    @staticmethod
    def _hash(url: str) -> str:
        """URL → MD5 短哈希"""
        normalized = url.strip().rstrip("/").lower()
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _extract_domain_for_cache(url: str) -> str:
        """快速提取域名（不依赖 urllib，减少开销）"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = parsed.hostname or ""
            if host.startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return ""

    def auto_save(self, force: bool = False):
        """自动保存（如果脏且有足够数据）"""
        if self._dirty and (force or len(self._data.get("entries", {})) % 50 == 0):
            self.save()

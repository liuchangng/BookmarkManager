"""
classifier.py - 规则分类引擎
支持: 域名匹配 / 关键词匹配 / 路径匹配 / 正则匹配
功能: 对 Bookmark 列表进行自动分类，输出带分类结果的列表

规则来源: 自动从 config.yaml 的 categories 段生成
"""

import re
import logging
import yaml
from pathlib import Path
from typing import Optional

from modules.bookmark import Bookmark

logger = logging.getLogger("classifier")


class ClassifyRule:
    """单条分类规则"""

    def __init__(self, category_l1: str, category_l2: str, rule_type: str,
                 pattern: str, priority: int = 100, description: str = ""):
        self.category_l1 = category_l1
        self.category_l2 = category_l2
        self.rule_type = rule_type  # domain / keyword / path / regex
        self.pattern = pattern
        self.priority = priority
        self.description = description
        self._compiled: Optional[re.Pattern] = None

        if rule_type == "regex":
            try:
                self._compiled = re.compile(pattern, re.I)
            except re.error as e:
                logger.error(f"正则编译失败 [{pattern}]: {e}")

    def match(self, bookmark: Bookmark) -> bool:
        if self.rule_type == "domain":
            return self._match_domain(bookmark.domain)
        elif self.rule_type == "keyword":
            # 二阶段规则: 页面摘要也参与匹配（T2，空则与旧行为一致）
            parts = [bookmark.title, bookmark.url]
            summary = getattr(bookmark, "page_summary", "") or ""
            if summary:
                parts.append(summary)
            text = " ".join(parts).lower()
            return self.pattern.lower() in text
        elif self.rule_type == "path":
            return self.pattern.lower() in bookmark.folder.lower()
        elif self.rule_type == "regex":
            if not self._compiled:
                return False
            text = f"{bookmark.title} {bookmark.url}"
            return bool(self._compiled.search(text))
        return False

    def _match_domain(self, domain: str) -> bool:
        if not domain:
            return False
        pattern = self.pattern.lower().rstrip(".")
        if pattern.startswith("*."):
            suffix = pattern[2:]
            return domain == suffix or domain.endswith(f".{suffix}")
        if "." in pattern:
            # 主域规则同时匹配其子域名: github.com 命中 gist.github.com
            return domain == pattern or domain.endswith(f".{pattern}")
        return domain == pattern


class Classifier:
    """
    规则分类器

    支持两种规则来源:
    1. config.yaml 的 categories 段（关键词列表 → 自动生成规则）
    2. 独立的 classify_rules 段（显式 domain/keyword/path/regex 规则）
    """

    def __init__(self, config_path: str = ""):
        self.rules: list[ClassifyRule] = []
        self._stats: dict = {"total": 0, "matched": 0, "unmatched": 0}
        self._category_l2_default: dict[str, str] = {}
        # 二阶段规则（T2, design §5 B3）
        self.summary_rule_enabled: bool = True
        self.rule_confidence_threshold: float = 0.0
        if config_path:
            self.load_rules(config_path)

    def load_rules(self, config_path: str):
        """从 YAML 配置文件加载规则

        支持三种格式（可叠加）:
        1. categories: [{name, keywords: [...], sub_categories: [...]}]
           大类关键词 → 落到第一个小类（default_l2）
        2. categories[].sub_keywords: {小类名: [关键词, ...]}
           「二级智能分类」：小类专属关键词 → 直接落到指定小类
        3. classify_rules: [{l1, l2, type, body, priority}]
           显式规则默认最高优先级（priority=0 最先匹配），用于人工覆盖
        """
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"配置文件不存在: {path}")
            return

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self.rules = []
        self._category_l2_default = {}

        # 二阶段规则配置（T2）
        classification_cfg = data.get("classification", {}) or {}
        self.summary_rule_enabled = bool(classification_cfg.get("summary_rule_enabled", True))
        try:
            self.rule_confidence_threshold = float(classification_cfg.get("rule_confidence_threshold", 0.0) or 0.0)
        except (TypeError, ValueError):
            self.rule_confidence_threshold = 0.0

        # 方式1+2: 从 categories 段生成
        categories = data.get("categories", []) or []
        priority = 10
        for cat in categories:
            name = cat.get("name", "").strip()
            if not name:
                continue

            clean_name = re.sub(r'^[\U0001F300-\U0001FAFF\s]+', '', name).strip()
            subs = cat.get("sub_categories", []) or []
            default_l2 = subs[0] if subs else "其他"
            self._category_l2_default[clean_name] = default_l2

            # 方式2: 小类专属关键词（更精确 → 优先级更高，先匹配）
            sub_keywords = cat.get("sub_keywords", {}) or {}
            for sub_name, sub_kws in sub_keywords.items():
                sub_name = str(sub_name).strip()
                for kw in sub_kws or []:
                    kw = str(kw).strip()
                    if not kw or not sub_name:
                        continue
                    self.rules.append(ClassifyRule(
                        category_l1=clean_name, category_l2=sub_name,
                        rule_type="domain" if self._looks_like_domain(kw) else "keyword",
                        pattern=kw, priority=priority + 2,
                        description=f"sub: {name}/{sub_name} <- {kw}",
                    ))

            # 方式1: 大类关键词 → 默认小类
            keywords = cat.get("keywords", []) or []
            for kw in keywords:
                kw = str(kw).strip()
                if not kw:
                    continue
                if self._looks_like_domain(kw):
                    self.rules.append(ClassifyRule(
                        category_l1=clean_name, category_l2=default_l2,
                        rule_type="domain", pattern=kw, priority=priority,
                        description=f"auto: {name} <- {kw}",
                    ))
                else:
                    self.rules.append(ClassifyRule(
                        category_l1=clean_name, category_l2=default_l2,
                        rule_type="keyword", pattern=kw, priority=priority + 5,
                        description=f"auto: {name} <- {kw}",
                    ))
            priority += 10

        # 方式3: 显式规则（默认最高优先级，用于人工覆盖）
        explicit_rules = data.get("classify_rules", []) or []
        for rd in explicit_rules:
            self.rules.append(ClassifyRule(
                category_l1=rd.get("l1", ""),
                category_l2=rd.get("l2", ""),
                rule_type=rd.get("type", "domain"),
                pattern=rd.get("pattern", ""),
                priority=rd.get("priority", 0),
                description=rd.get("description", ""),
            ))

        self.rules.sort(key=lambda r: r.priority)

        type_count: dict = {}
        for r in self.rules:
            type_count[r.rule_type] = type_count.get(r.rule_type, 0) + 1
        logger.info(f"加载分类规则: {len(self.rules)} 条 (类型: {type_count})")

    def load_rules_from_dict(self, rules_data: list[dict]):
        self.rules = []
        for rd in rules_data:
            self.rules.append(ClassifyRule(
                category_l1=rd.get("l1", ""),
                category_l2=rd.get("l2", ""),
                rule_type=rd.get("type", "domain"),
                pattern=rd.get("pattern", ""),
                priority=rd.get("priority", 0),
            ))
        self.rules.sort(key=lambda r: r.priority)

    @staticmethod
    def _looks_like_domain(kw: str) -> bool:
        """判断关键词是否更像域名（含点且非 URL）"""
        return "." in kw and not kw.startswith("http")

    def get_category_list(self) -> list[dict]:
        result = []
        seen = set()
        for rule in self.rules:
            key = rule.category_l1
            if key not in seen:
                seen.add(key)
                result.append({
                    "l1": rule.category_l1,
                    "l2_default": self._category_l2_default.get(rule.category_l1, "其他"),
                })
        return result

    def classify(self, bookmarks: list[Bookmark]) -> list[Bookmark]:
        self._stats = {"total": len(bookmarks), "matched": 0, "unmatched": 0}

        for bm in bookmarks:
            if bm.user_deleted:
                continue
            matched = False
            for rule in self.rules:
                if rule.match(bm):
                    bm.category_l1 = rule.category_l1
                    bm.category_l2 = rule.category_l2
                    bm.classify_method = self._resolve_method(rule, bm)
                    bm.confidence = self._calc_confidence(rule, bm)
                    matched = True
                    self._stats["matched"] += 1
                    break

            if not matched:
                bm.category_l1 = "其他"
                bm.category_l2 = "待分类"
                bm.classify_method = "unmatched"
                bm.confidence = 0.0
                self._stats["unmatched"] += 1

        logger.info(
            f"分类完成: {self._stats['matched']}/{self._stats['total']} 已分类, "
            f"{self._stats['unmatched']} 条待 AI/人工"
        )
        return bookmarks

    def classify_single(self, bookmark: Bookmark) -> bool:
        for rule in self.rules:
            if rule.match(bookmark):
                bookmark.category_l1 = rule.category_l1
                bookmark.category_l2 = rule.category_l2
                bookmark.classify_method = self._resolve_method(rule, bookmark)
                bookmark.confidence = self._calc_confidence(rule, bookmark)
                return True
        return False

    def classify_with_summary(self, bookmark: Bookmark) -> bool:
        """
        二阶段规则: 仅用页面摘要匹配关键词规则（T2, design §5 B3）

        规则:
          - 需 summary_rule_enabled 且书签已有 page_summary
          - 仅 keyword 规则参与；标题/URL 已命中的词跳过（一阶段职责）
          - 置信度(0.7) >= rule_confidence_threshold 才落地（summary_rule）；
            低于阈值不落地，交给 AI/人工审核
        命中: classify_method="summary_rule"（AI 只兜底，不再重复分类）
        """
        if not self.summary_rule_enabled:
            return False
        summary = (bookmark.page_summary or "").strip()
        if not summary:
            return False
        summary_low = summary.lower()
        combined_low = f"{bookmark.title} {bookmark.url}".lower()

        for rule in self.rules:
            if rule.rule_type != "keyword":
                continue
            pattern = rule.pattern.lower()
            if pattern not in summary_low:
                continue
            if pattern in combined_low:
                continue  # 一阶段本可命中，跳过重复
            confidence = self._calc_confidence(rule, bookmark)  # keyword → 0.7
            if confidence < self.rule_confidence_threshold:
                continue  # 低于阈值不落地
            bookmark.category_l1 = rule.category_l1
            bookmark.category_l2 = rule.category_l2
            bookmark.classify_method = "summary_rule"
            bookmark.confidence = confidence
            return True
        return False

    @staticmethod
    def _resolve_method(rule: ClassifyRule, bm: Bookmark) -> str:
        """判定关键词命中的维度: 标题/URL → rule；仅摘要 → summary_rule"""
        if rule.rule_type != "keyword":
            return "rule"
        combined = f"{bm.title} {bm.url}".lower()
        if rule.pattern.lower() in combined:
            return "rule"
        summary = getattr(bm, "page_summary", "") or ""
        if summary and rule.pattern.lower() in summary.lower():
            return "summary_rule"
        return "rule"

    def _calc_confidence(self, rule: ClassifyRule, bm: Bookmark) -> float:
        if rule.rule_type == "domain":
            if bm.domain == rule.pattern:
                return 0.95
            elif rule.pattern.startswith("*.") or (
                "." in rule.pattern and bm.domain.endswith(f".{rule.pattern}")
            ):
                return 0.85
        elif rule.rule_type == "keyword":
            return 0.7
        elif rule.rule_type == "path":
            return 0.6
        elif rule.rule_type == "regex":
            return 0.75
        return 0.5

    def get_stats(self) -> dict:
        return dict(self._stats)

    def get_distribution(self, bookmarks: list[Bookmark]) -> dict:
        dist: dict[str, dict[str, int]] = {}
        for bm in bookmarks:
            l1 = bm.category_l1 or "其他"
            l2 = bm.category_l2 or "未分类"
            if l1 not in dist:
                dist[l1] = {}
            dist[l1][l2] = dist[l1].get(l2, 0) + 1
        return dist

    def print_report(self, bookmarks: list[Bookmark]):
        dist = self.get_distribution(bookmarks)
        logger.info("=" * 50)
        logger.info("分类报告")
        logger.info("=" * 50)
        for l1, l2s in sorted(dist.items(), key=lambda x: sum(x[1].values()), reverse=True):
            total = sum(l2s.values())
            logger.info(f"  {l1}: {total}")
            for l2, count in sorted(l2s.items(), key=lambda x: x[1], reverse=True):
                logger.info(f"    |- {l2}: {count}")
        logger.info("=" * 50)

    def add_rule(self, rule: ClassifyRule):
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority)

    def remove_rule(self, pattern: str, rule_type: str = "") -> int:
        before = len(self.rules)
        self.rules = [
            r for r in self.rules
            if not (r.pattern == pattern and (not rule_type or r.rule_type == rule_type))
        ]
        return before - len(self.rules)

    def get_all_rules(self) -> list[dict]:
        return [
            {
                "l1": r.category_l1, "l2": r.category_l2,
                "type": r.rule_type, "pattern": r.pattern,
                "priority": r.priority, "description": r.description,
            }
            for r in self.rules
        ]

    def test_rule(self, rule: ClassifyRule, bookmarks: list[Bookmark]) -> list[Bookmark]:
        return [bm for bm in bookmarks if rule.match(bm)]

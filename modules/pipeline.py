"""
pipeline.py - 纯 Python 流水线编排（Web 版核心，无 Qt 依赖）

流程: 解析 → URL 体检(本地/失效分流) → 规则分类(缓存填充) → 网页抓取
      → 本地摘要二阶段规则 → AI 分类(兜底) → 状态就绪

与旧桌面版 main_window 的 _chain_* 一一对应，但用事件回调替代 Qt 信号，
供 Web 后端 (FastAPI SSE) 消费。进度 0-100 映射:
    解析 0→5 | 体检 5→15 | 分类 15→30 | 抓取 30→70 | 摘要 70→72 | AI 72→95 | 完成 100
"""

import logging
import threading
from typing import Callable, Optional

from modules.config_manager import ConfigManager
from modules.secure_store import SecureStore
from modules.proxy import ProxyManager
from modules.parser import BookmarkParser
from modules.classifier import Classifier
from modules.cache import ClassifyCache
from modules.fetcher import WebFetcher, ProxyAdapter
from modules.ai_client import OpenAIClient
from modules.summarizer import summarize_bookmarks
from modules.link_probe import LinkProbeCache, probe_urls
from modules.bookmark import Bookmark

logger = logging.getLogger("pipeline")

# 阶段常量
STAGE_PARSE = "parse"
STAGE_PROBE = "probe"
STAGE_CLASSIFY = "classify"
STAGE_FETCH = "fetch"
STAGE_SUMMARY = "summary"
STAGE_AI = "ai"
STAGE_DONE = "done"

STAGE_LABELS = {
    STAGE_PARSE: "解析书签",
    STAGE_PROBE: "链接体检",
    STAGE_CLASSIFY: "规则分类",
    STAGE_FETCH: "网页抓取",
    STAGE_SUMMARY: "摘要归类",
    STAGE_AI: "AI 分类",
    STAGE_DONE: "完成",
}


class Pipeline:
    """书签处理流水线（纯 Python，线程安全）"""

    def __init__(self, config: ConfigManager, secure_store: SecureStore,
                 proxy_manager: ProxyManager):
        self.config = config
        self.secure_store = secure_store
        self.proxy_manager = proxy_manager

        # 数据
        self.bookmarks: list[Bookmark] = []
        self.fetch_results: dict = {}
        self.source_file: str = ""

        # 组件（惰性初始化）
        self.classifier = Classifier(str(config.config_path))
        cache_dir = config.get("classification.cache_dir", "data/cache")
        self.cache = ClassifyCache(cache_dir=cache_dir)
        self.fetcher = WebFetcher(
            config=self._build_fetcher_config(),
            proxy_adapter=ProxyAdapter(proxy_manager=proxy_manager,
                                       config=self._build_fetcher_config()),
        )
        fc_key = self.secure_store.load("firecrawl_api_key")
        if fc_key:
            self.fetcher.set_firecrawl_key(fc_key)

        # 运行状态
        self._cancelled = False
        self._thread: Optional[threading.Thread] = None
        self._event_cb: Optional[Callable[[dict], None]] = None

    # ──────────────────────────────────────────────
    #  事件
    # ──────────────────────────────────────────────

    def set_event_callback(self, cb: Callable[[dict], None]):
        """注册事件回调。事件 dict 直接透传给 SSE。"""
        self._event_cb = cb

    def _emit(self, event: dict):
        if self._event_cb:
            try:
                self._event_cb(event)
            except Exception as e:
                logger.warning(f"事件回调异常: {e}")

    def _log(self, level: str, message: str):
        self._emit({"type": "log", "level": level, "message": message})

    def _progress(self, stage: str, percent: int, detail: str = ""):
        self._emit({
            "type": "progress",
            "stage": stage,
            "stage_label": STAGE_LABELS.get(stage, stage),
            "percent": percent,
            "detail": detail,
        })

    def _stage(self, stage: str, index: int = 0):
        self._emit({
            "type": "stage",
            "stage": stage,
            "index": index,
            "label": STAGE_LABELS.get(stage, stage),
        })

    # ──────────────────────────────────────────────
    #  配置
    # ──────────────────────────────────────────────

    def _build_fetcher_config(self) -> dict:
        return {
            "proxy": {
                "enabled": self.config.get("proxy.enabled", False),
                "auto_detect_system": self.config.get("proxy.auto_detect_system", True),
                "custom": self.config.get("proxy.custom", {}),
                "bypass_domains": self.config.get("proxy.bypass_domains", []),
                "use_for": self.config.get("proxy.use_for", {}),
            },
            "firecrawl": self.config.get("firecrawl", {}),
            "fetch": self.config.get("fetch", {}),
            # 关键: OpenAIClient 从 config["ai"] 读 base_url/model，
            # 缺了会回退到默认 deepseek.com，导致用 agnes 的 Key 请求 401
            "ai": self.config.get("ai", {}),
            "classification": {"cache_dir": self.config.get("classification.cache_dir", "data/cache")},
        }

    # ──────────────────────────────────────────────
    #  生命周期
    # ──────────────────────────────────────────────

    def cancel(self):
        """请求取消（下一条循环前生效）"""
        self._cancelled = True

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """在线程中启动流水线"""
        if self.is_running():
            raise RuntimeError("流水线已在运行中")
        self._cancelled = False
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    # ──────────────────────────────────────────────
    #  流水线主体（同步，供线程运行）
    # ──────────────────────────────────────────────

    def run(self):
        try:
            if not self.bookmarks:
                raise RuntimeError("没有书签数据，请先上传书签文件")

            total = len(self.bookmarks)
            self._stage(STAGE_PROBE, 1)
            self._progress(STAGE_PROBE, 5, "正在体检链接...")
            self._run_probe()

            if self._cancelled:
                return

            self._stage(STAGE_CLASSIFY, 2)
            self._progress(STAGE_CLASSIFY, 15, "规则分类中...")
            self._run_classify()

            if self._cancelled:
                return

            self._stage(STAGE_FETCH, 3)
            self._run_fetch()

            if self._cancelled:
                return

            self._stage(STAGE_SUMMARY, 4)
            self._run_summary_rules()

            if self._cancelled:
                return

            self._stage(STAGE_AI, 5)
            self._run_ai()

            if self._cancelled:
                self._log("WARN", "⚠️ 流程已取消")
                self._emit({"type": "cancelled"})
                return

            self._emit({"type": "done", "stats": self._collect_stats()})
            self._progress(STAGE_DONE, 100, "全部完成")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._emit({"type": "error", "message": f"{type(e).__name__}: {e}"})

    # ── 解析 ──

    def parse_file(self, filepath: str) -> list[Bookmark]:
        """解析书签文件并去重（同步，供上传接口直接调用）"""
        parser = BookmarkParser()
        bookmarks = parser.parse(filepath)
        if not bookmarks:
            raise RuntimeError("解析结果为空，文件中没有书签")
        merged = parser.merge_duplicates(bookmarks)
        dup = len(bookmarks) - len(merged)
        self.bookmarks = merged
        self.source_file = filepath
        self.fetch_results = {}
        if dup > 0:
            self._log("SUCCESS", f"✅ 解析完成: {len(merged)} 条（去重移除 {dup} 条）")
        else:
            self._log("SUCCESS", f"✅ 解析完成: {len(merged)} 条书签")
        return merged

    # ── 体检 ──

    def _run_probe(self):
        """URL 体检：本地/死链三态分流，系统桶不参与规则引擎"""
        cache_dir = self.config.get("classification.cache_dir", "data/cache")
        probe_cache = LinkProbeCache(cache_dir=f"{cache_dir}/probe")
        urls = [b.url for b in self.bookmarks]
        probes = probe_urls(urls, cache=probe_cache)

        counts = {"ok": 0, "dead": 0, "local": 0, "pending": 0}
        for bm in self.bookmarks:
            r = probes.get(bm.url)
            if not r:
                continue
            bm.status = r.status
            bm.probe_error = r.error
            bm.http_status = r.http_status
            counts[r.status] = counts.get(r.status, 0) + 1

            if r.status == "local":
                bm.category_l1 = "📁 本地/内网"
                bm.category_l2 = "本地/内网"
                bm.classify_method = "local"
                bm.confidence = 1.0
            elif r.status == "dead":
                bm.category_l1 = "⚠️ 失效链接"
                bm.category_l2 = "失效链接"
                bm.classify_method = "dead"
                bm.confidence = 1.0

        self._log("SUCCESS",
                  f"✅ 体检完成: 正常{counts['ok']} 失效{counts['dead']} "
                  f"本地{counts['local']} 待定{counts['pending']}")
        self._progress(STAGE_PROBE, 15, "体检完成")
        self._emit({"type": "bookmarks_updated"})

    # ── 规则分类（方案 A 下规则为空，主要为缓存填充） ──

    def _run_classify(self):
        total = len(self.bookmarks)
        self._log("INFO", f"开始分类 {total} 条书签...")

        if not self.classifier.rules:
            self._log("INFO", "🤖 无分类规则：AI 自动分类模式，全部未分类书签将交给 AI")

        cache_hits = 0
        if self.cache:
            cache_hits = self.cache.fill_bookmarks(self.bookmarks)
            if cache_hits > 0:
                self._log("SUCCESS", f"✅ 缓存命中: {cache_hits}/{total}")

        pending = [bm for bm in self.bookmarks
                   if not bm.category_l1 and bm.status not in ("local", "dead")]
        if pending:
            self._log("INFO", f"🔄 规则分类: {len(pending)} 条待处理...")
            self.classifier.classify(pending)
            if self.cache:
                for bm in pending:
                    if bm.category_l1 and bm.classify_method == "rule":
                        self.cache.set(bm.url, bm.category_l1, bm.category_l2,
                                       "rule", bm.confidence)
                self.cache.save()

        classified = sum(1 for bm in self.bookmarks
                         if bm.category_l1 and bm.category_l1 not in ("其他", "📁 本地/内网", "⚠️ 失效链接"))
        unmatched = sum(1 for bm in self.bookmarks
                        if not bm.category_l1 or bm.category_l1 == "其他")
        self._log("INFO",
                  f"📊 已分类: {classified} | 待AI/人工: {unmatched} | 💾缓存: {cache_hits}命中")
        self._progress(STAGE_CLASSIFY, 30, f"已分类 {classified} / {total}")
        self._emit({"type": "bookmarks_updated"})

    # ── 抓取 ──

    def _run_fetch(self):
        to_fetch = []
        for bm in self.bookmarks:
            if bm.user_deleted:
                continue
            if bm.status in ("local", "dead"):
                continue
            if bm.category_l1 and bm.category_l1 not in ("其他", "📁 其他"):
                continue
            if bm.url in self.fetch_results:
                continue
            to_fetch.append(bm.url)

        if not to_fetch:
            self._log("INFO", "所有书签已分类或已抓取，无需抓取")
            self._progress(STAGE_FETCH, 70, "无需抓取")
            return

        seen, unique = set(), []
        for u in to_fetch:
            if u not in seen:
                seen.add(u)
                unique.append(u)

        total = len(unique)
        self._log("INFO", f"准备并行抓取 {total} 个 URL (并发 {self.fetcher.concurrency})...")
        self._progress(STAGE_FETCH, 30, f"抓取中... 0/{total}")
        self.fetcher.reset_stats()

        success = failed = 0

        def _on_item(done_count: int, total_count: int, result) -> None:
            nonlocal success, failed
            if result.success:
                success += 1
            else:
                failed += 1
            pct = min(int(done_count / total_count * 40) + 30, 70)
            self._progress(STAGE_FETCH, pct,
                           f"抓取: {done_count}/{total_count} | ✅{success} ❌{failed}")
            self._emit({
                "type": "item",
                "stage": STAGE_FETCH,
                "current": done_count,
                "total": total_count,
                "url": result.url,
                "success": result.success,
            })

        result_list = self.fetcher.fetch_many_parallel(unique, progress_cb=_on_item)
        results = {r.url: r for r in result_list}

        self.fetch_results.update(results)
        self.fetcher.save_cache()
        self._log("SUCCESS", f"🎉 抓取完成! 成功: {success}/{total} | 失败: {failed}")
        self._progress(STAGE_FETCH, 70, f"抓取完成 ✅{success} ❌{failed}")
        self._emit({"type": "bookmarks_updated"})

    # ── 摘要二阶段规则 ──

    def _run_summary_rules(self):
        try:
            summaries = summarize_bookmarks(self.fetch_results)
            if not summaries:
                self._log("INFO", "📝 摘要规则二阶段: 无可用摘要")
                self._progress(STAGE_SUMMARY, 72, "无摘要")
                return

            changed = 0
            for bm in self.bookmarks:
                if bm.user_deleted:
                    continue
                if bm.category_l1 and bm.category_l1 not in ("其他", "📁 其他"):
                    continue
                summary = summaries.get(bm.url)
                if not summary:
                    continue
                bm.page_summary = summary
                if self.classifier.classify_with_summary(bm):
                    changed += 1

            if changed:
                self._log("SUCCESS", f"📝 摘要规则二阶段: {changed} 条已归类 (summary_rule)")
            else:
                self._log("INFO", "📝 摘要规则二阶段: 无命中，交给 AI")
            self._progress(STAGE_SUMMARY, 72, f"摘要归类 {changed} 条")
            self._emit({"type": "bookmarks_updated"})
        except Exception as e:
            self._log("WARN", f"⚠️ 摘要规则二阶段失败: {type(e).__name__}: {e}")

    # ── AI 兜底 ──

    def _run_ai(self):
        to_classify = []
        for bm in self.bookmarks:
            if bm.user_deleted:
                continue
            if bm.status in ("local", "dead"):
                continue
            if bm.classify_method == "summary_rule":
                continue
            if bm.category_l1 and bm.category_l1 not in ("其他", "📁 其他") \
                    and bm.confidence >= 0.8:
                continue
            to_classify.append(bm)

        if not to_classify:
            self._log("INFO", "✅ 所有书签已分类完成，无需 AI 处理")
            self._progress(STAGE_AI, 95, "无需 AI")
            return

        api_key = self.secure_store.load("deepseek")
        if not api_key:
            self._log("WARN", "⚠️ 未配置 AI API Key，跳过 AI 分类（可在结果页手动分类）")
            self._progress(STAGE_AI, 95, "未配置 AI Key")
            return

        cfg = self._build_fetcher_config()
        client = OpenAIClient(
            config=cfg,
            categories=self.config.get("categories", []),
            proxy_adapter=ProxyAdapter(proxy_manager=self.proxy_manager, config=cfg),
            api_key=api_key,
        )

        estimate = client.estimate_cost(len(to_classify))
        max_cost = self.config.get("ai.max_cost_yuan", 5.0)
        self._log("INFO",
                  f"🤖 将对 {len(to_classify)} 条书签进行 AI 分类，"
                  f"预估 ¥{estimate['estimated_cost_yuan']:.4f} / 上限 ¥{max_cost:.2f}")
        self._emit({
            "type": "ai_estimate",
            "count": len(to_classify),
            "estimated_cost_yuan": estimate["estimated_cost_yuan"],
            "max_cost_yuan": max_cost,
        })
        self._progress(STAGE_AI, 72, f"AI 分类中... 0/{len(to_classify)}")

        client.reset_stats()
        total = len(to_classify)
        success = failed = cached = 0

        for i, bm in enumerate(to_classify):
            if self._cancelled:
                self._log("WARN", "⚠️ AI 分类已取消")
                break

            fetch = self.fetch_results.get(bm.url)
            info = {
                "url": bm.url,
                "title": bm.title,
                "domain": bm.domain,
                "description": fetch.description if fetch else "",
                "keywords": fetch.keywords if fetch else [],
                "summary": (bm.page_summary or (fetch.text[:200] if fetch else "")),
            }

            result = client.classify_one(info)
            if result.success:
                if result.reason == "" and result.confidence == 0:
                    cached += 1
                else:
                    success += 1
                    bm.category_l1 = result.category_l1
                    bm.category_l2 = result.category_l2
                    bm.confidence = result.confidence
                    bm.classify_method = "ai_deepseek"
                    if result.summary:
                        bm.page_summary = result.summary
            else:
                failed += 1

            if (i + 1) % 5 == 0 or i == total - 1:
                pct = min(int((i + 1) / total * 23) + 72, 95)
                self._progress(STAGE_AI, pct,
                               f"AI: {i+1}/{total} | ✅{success} ❌{failed} 💾{cached}")

            stats = client.get_stats()
            used = stats["estimated_cost_yuan"]
            if used >= max_cost * 0.8:
                self._log("WARN", f"⚠️ AI 预算即将耗尽: ¥{used:.4f} / ¥{max_cost:.2f}")
            if used >= max_cost:
                self._log("WARN", f"⚠️ 预算耗尽 (¥{max_cost:.2f})，停止 AI 分类")
                break

            self._emit({
                "type": "item",
                "stage": STAGE_AI,
                "current": i + 1,
                "total": total,
                "url": bm.url,
                "success": result.success,
                "category_l1": bm.category_l1,
                "category_l2": bm.category_l2,
            })

        client.save_cache()
        stats = client.get_stats()
        self._log("SUCCESS",
                  f"🎉 AI 分类完成! ✅{success} 💾{cached} ❌{failed}")
        self._log("INFO", f"💰 费用: ¥{stats['estimated_cost_yuan']:.4f} / ¥{max_cost:.2f}")
        self._progress(STAGE_AI, 95, "AI 分类完成")
        self._emit({"type": "bookmarks_updated"})

    # ── 统计 ──

    def _collect_stats(self) -> dict:
        total = len(self.bookmarks)
        active = [b for b in self.bookmarks if not b.user_deleted]
        classified = sum(1 for b in active
                         if b.category_l1 and b.category_l1 not in ("其他", "📁 其他"))
        unclassified = sum(1 for b in active
                           if not b.category_l1 or b.category_l1 in ("其他", "📁 其他"))
        dead = sum(1 for b in active if b.status == "dead")
        local = sum(1 for b in active if b.status == "local")
        return {
            "total": total,
            "active": len(active),
            "classified": classified,
            "unclassified": unclassified,
            "dead": dead,
            "local": local,
            "deleted": total - len(active),
            "ai_enabled": bool(self.secure_store.load("deepseek")),
        }

    # ── 对外查询 ──

    def get_distribution(self) -> dict:
        """分类分布树: {l1: {l2: count}}"""
        dist: dict[str, dict[str, int]] = {}
        for bm in self.bookmarks:
            if bm.user_deleted:
                continue
            l1 = bm.category_l1 or "📁 其他"
            l2 = bm.category_l2 or "未分类"
            dist.setdefault(l1, {})
            dist[l1][l2] = dist[l1].get(l2, 0) + 1
        return dist

    def bookmarks_to_dict(self, filter_status: str = "all") -> list[dict]:
        """书签列表 → dict（前端表格用）"""
        result = []
        for bm in self.bookmarks:
            if bm.user_deleted:
                continue
            if filter_status == "dead" and bm.status != "dead":
                continue
            if filter_status == "local" and bm.status != "local":
                continue
            if filter_status == "unclassified" and (
                    bm.category_l1 and bm.category_l1 not in ("其他", "📁 其他")):
                continue
            result.append({
                "id": bm.id,
                "title": bm.title,
                "url": bm.url,
                "domain": bm.domain,
                "folder": bm.folder,
                "category_l1": bm.category_l1 or "📁 其他",
                "category_l2": bm.category_l2 or "未分类",
                "classify_method": bm.classify_method or "",
                "confidence": bm.confidence,
                "status": bm.status,
                "http_status": bm.http_status,
                "probe_error": bm.probe_error,
                "page_summary": bm.page_summary,
                "add_date": bm.add_date,
            })
        return result

    def set_classification(self, url: str, l1: str, l2: str):
        """手动修改分类（审核用）"""
        for bm in self.bookmarks:
            if bm.url == url:
                bm.category_l1 = l1
                bm.category_l2 = l2
                bm.classify_method = "manual"
                bm.confidence = 1.0
                bm.user_confirmed = True
                return True
        return False

    def delete_bookmark(self, url: str):
        """标记删除（审核用）"""
        for bm in self.bookmarks:
            if bm.url == url:
                bm.user_deleted = True
                return True
        return False

    def delete_dead(self) -> int:
        """一键删除所有失效书签"""
        count = 0
        for bm in self.bookmarks:
            if not bm.user_deleted and bm.status == "dead":
                bm.user_deleted = True
                count += 1
        return count


# ──────────────────────────────────────────────
#  模块级工具函数（原桌面版 main_window 迁移，供 Web 前端与测试复用）
# ──────────────────────────────────────────────

def apply_filter(bookmarks: list, filter_text: str, fetch_results: dict | None = None) -> list:
    """书签筛选（结果页下拉：全部/已分类/待AI/已抓取/失效链接/已删除）"""
    if filter_text == "全部":
        return bookmarks
    if filter_text == "已分类":
        return [bm for bm in bookmarks
                if bm.category_l1 and bm.category_l1 not in ("其他", "📁 其他")]
    if filter_text == "待AI/人工":
        return [bm for bm in bookmarks
                if not bm.category_l1 or bm.category_l1 in ("其他", "📁 其他")]
    if filter_text == "已抓取":
        fr = fetch_results or {}
        return [bm for bm in bookmarks if bm.url in fr]
    if filter_text == "失效链接":
        return [bm for bm in bookmarks if bm.status == "dead"]
    if filter_text == "已删除":
        return [bm for bm in bookmarks if bm.user_deleted]
    return bookmarks


def status_text(bm, fetched: bool = False) -> str:
    """状态列文案（探活三态 + 抓取标记）"""
    status_map = {"ok": "✅正常", "dead": "⚠️失效", "local": "📁本地"}
    text = status_map.get(bm.status, "🕐待定")
    if fetched:
        text += "·已抓"
    return text

"""
classify_worker.py - 分类后台工作线程
整合: 缓存填充 → 规则分类 → 结果回写缓存
"""

import logging
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from modules.bookmark import Bookmark
from modules.classifier import Classifier
from modules.cache import ClassifyCache

logger = logging.getLogger("classify_worker")


class ClassifyWorker(QThread):
    """后台执行分类任务的 worker"""

    progress = pyqtSignal(str)           # 日志
    progress_detail = pyqtSignal(str)    # 进度详情
    finished_ok = pyqtSignal(list)       # 分类完成的书签列表
    finished_error = pyqtSignal(str)     # 错误
    cache_stats = pyqtSignal(dict)       # 缓存统计

    def __init__(self, bookmarks: list[Bookmark], classifier: Classifier,
                 cache: Optional[ClassifyCache] = None, parent=None):
        super().__init__(parent)
        self.bookmarks = bookmarks
        self.classifier = classifier
        self.cache = cache

    def run(self):
        try:
            total = len(self.bookmarks)
            self.progress.emit(f"开始分类 {total} 条书签...")
            self.progress_detail.emit(f"📊 总计: {total} | 规则分类中...")

            # Step 1: 尝试从缓存填充
            cache_hits = 0
            if self.cache:
                cache_hits = self.cache.fill_bookmarks(self.bookmarks)
                if cache_hits > 0:
                    self.progress.emit(f"✅ 缓存命中: {cache_hits}/{total}")
                    self.cache_stats.emit(self.cache.stats())

            # Step 2: 对未分类的书签执行规则分类（本地/失效书签不参与规则引擎）
            pending = [bm for bm in self.bookmarks
                       if not bm.category_l1 and bm.status not in ("local", "dead")]
            if pending:
                self.progress.emit(f"🔄 规则分类: {len(pending)} 条待处理...")
                self.classifier.classify(pending)

                # Step 3: 新分类结果写回缓存
                if self.cache:
                    for bm in pending:
                        if bm.category_l1 and bm.classify_method == "rule":
                            self.cache.set(
                                bm.url, bm.category_l1, bm.category_l2,
                                "rule", bm.confidence
                            )
                    self.cache.save()
                    self.cache_stats.emit(self.cache.stats())

            # Step 4: 统计
            classified = sum(1 for bm in self.bookmarks if bm.category_l1 and bm.category_l1 != "其他")
            unmatched = sum(1 for bm in self.bookmarks if bm.category_l1 == "其他" or not bm.category_l1)

            self.progress_detail.emit(
                f"📊 总计: {total} | 已分类: {classified} | 待AI/人工: {unmatched} | 💾缓存: {cache_hits}命中"
            )

            # 打印报告
            self.classifier.print_report(self.bookmarks)

            self.finished_ok.emit(self.bookmarks)

        except Exception as e:
            self.finished_error.emit(f"分类失败: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

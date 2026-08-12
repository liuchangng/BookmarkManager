"""
ai_worker.py - AI 分类后台工作线程
功能: 后台批量调用 DeepSeek API 对书签进行分类
"""

import logging
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from modules.ai_client import DeepSeekClient, AIResult

logger = logging.getLogger("ai_worker")


class AIWorker(QThread):
    """后台执行 AI 分类的 worker"""

    progress = pyqtSignal(str)                  # 日志
    progress_detail = pyqtSignal(str)           # 进度详情
    item_done = pyqtSignal(int, int, dict)      # (current, total, result_dict)
    finished_ok = pyqtSignal(list)              # [AIResult, ...]
    finished_error = pyqtSignal(str)            # 错误
    stats_update = pyqtSignal(dict)             # 统计
    budget_warning = pyqtSignal(float, float)   # (used, max)

    def __init__(self, client: DeepSeekClient, bookmarks_info: list[dict], parent=None):
        super().__init__(parent)
        self.client = client
        self.bookmarks_info = bookmarks_info
        self._cancelled = False
        self._results: list = []  # 供测试/外部同步访问

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            total = len(self.bookmarks_info)
            self.progress.emit(f"🤖 开始 AI 分类 {total} 条书签...")
            self.client.reset_stats()

            results: list[AIResult] = []
            self._results = results
            success = 0
            failed = 0
            cached = 0

            for i, info in enumerate(self.bookmarks_info):
                if self._cancelled:
                    self.progress.emit("⚠️ AI 分类已取消")
                    break

                result = self.client.classify_one(info)
                results.append(result)

                if result.success:
                    if result.reason == "" and result.confidence == 0:
                        cached += 1
                    else:
                        success += 1
                else:
                    failed += 1

                # 每 5 条更新
                if (i + 1) % 5 == 0 or i == total - 1:
                    self.progress_detail.emit(
                        f"🤖 AI: {i+1}/{total} | ✅{success} ❌{failed} 💾{cached}"
                    )
                    self.stats_update.emit(self.client.get_stats())

                # 预算警告
                stats = self.client.get_stats()
                used = stats["estimated_cost_yuan"]
                max_budget = self.client.max_cost_yuan
                if used >= max_budget * 0.8:
                    self.budget_warning.emit(used, max_budget)

                self.item_done.emit(i + 1, total, result.to_dict())

                # 预算耗尽
                if used >= max_budget:
                    self.progress.emit(f"⚠️ 预算耗尽 (¥{max_budget:.2f})，停止 AI 分类")
                    break

            self.client.save_cache()
            self.client.print_stats()
            self.stats_update.emit(self.client.get_stats())

            self.progress.emit(
                f"🎉 AI 分类完成! ✅{success} 💾{cached} ❌{failed}"
            )
            self.finished_ok.emit(results)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished_error.emit(f"AI 分类失败: {type(e).__name__}: {e}")

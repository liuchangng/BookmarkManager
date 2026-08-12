"""
fetch_worker.py - 抓取后台工作线程
功能: 在后台批量抓取书签网页内容，带进度和取消支持
"""

import logging
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from modules.fetcher import WebFetcher, FetchResult

logger = logging.getLogger("fetch_worker")


class FetchWorker(QThread):
    """后台执行网页抓取的 worker"""

    progress = pyqtSignal(str)                 # 日志消息
    progress_detail = pyqtSignal(str)          # 进度详情
    item_done = pyqtSignal(int, int, dict)     # (current, total, result_dict)
    finished_ok = pyqtSignal(dict)             # {url: FetchResult}
    finished_error = pyqtSignal(str)           # 错误
    stats_update = pyqtSignal(dict)            # 统计

    def __init__(self, fetcher: WebFetcher, urls: list[str], parent=None):
        super().__init__(parent)
        self.fetcher = fetcher
        self.urls = urls
        self._cancelled = False
        self._results: dict = {}  # 供测试/外部同步访问

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            total = len(self.urls)
            self.progress.emit(f"开始抓取 {total} 个 URL...")
            self.fetcher.reset_stats()

            results: dict[str, FetchResult] = {}
            self._results = results
            success_count = 0
            failed_count = 0

            for i, url in enumerate(self.urls):
                if self._cancelled:
                    self.progress.emit("⚠️ 抓取已取消")
                    break

                result = self.fetcher.fetch(url)
                results[url] = result

                if result.success:
                    success_count += 1
                else:
                    failed_count += 1

                # 每 10 条发一次进度
                if (i + 1) % 10 == 0 or i == total - 1:
                    self.progress_detail.emit(
                        f"📡 抓取: {i+1}/{total} | ✅{success_count} ❌{failed_count}"
                    )
                    self.stats_update.emit(self.fetcher.get_stats())

                # 发送单条结果
                self.item_done.emit(i + 1, total, result.to_dict())

            # 保存缓存
            self.fetcher.save_cache()

            # 最终统计
            self.fetcher.print_stats()
            self.stats_update.emit(self.fetcher.get_stats())

            self.progress.emit(
                f"🎉 抓取完成! 成功: {success_count}/{total} | 失败: {failed_count}"
            )

            self.finished_ok.emit(results)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished_error.emit(f"抓取失败: {type(e).__name__}: {e}")

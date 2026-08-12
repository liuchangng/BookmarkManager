"""
review_dialog.py - 审核确认对话框
功能: 内嵌表格审核界面，无需打开 Excel 即可逐条确认
"""

import logging
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QCheckBox, QComboBox, QLineEdit, QHeaderView,
    QDialogButtonBox, QMessageBox, QGroupBox, QTextEdit, QSplitter,
    QFileDialog, QProgressBar,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from modules.bookmark import Bookmark

logger = logging.getLogger("review_dialog")


class ReviewDialog(QDialog):
    """审核确认对话框"""

    review_completed = pyqtSignal(list)  # 审核完成，发送书签列表

    def __init__(self, bookmarks: list[Bookmark], categories: list[dict],
                 fetch_results: dict = None, ai_results: dict = None,
                 parent=None):
        super().__init__(parent)
        self.bookmarks = list(bookmarks)  # 副本
        self.categories = categories
        self.fetch_results = fetch_results or {}
        self.ai_results = ai_results or {}

        # 构建 L1/L2 映射
        self.l1_list = [c.get("name", "") for c in categories]
        self.l2_map = {}
        for c in categories:
            self.l2_map[c.get("name", "")] = c.get("sub_categories", [])

        self.setWindowTitle("📋 书签审核确认")
        self.setMinimumSize(1000, 600)
        self.resize(1200, 700)

        self._init_ui()
        self._populate_table()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 顶部统计
        stats_row = QHBoxLayout()
        self.stats_label = QLabel()
        self.stats_label.setObjectName("statsLabel")
        stats_row.addWidget(self.stats_label)

        stats_row.addStretch()

        lbl = QLabel("筛选:")
        stats_row.addWidget(lbl)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["全部", "待审核", "规则已分", "AI推测", "待人工", "已删除"])
        self.filter_combo.currentTextChanged.connect(self._on_filter)
        stats_row.addWidget(self.filter_combo)

        layout.addLayout(stats_row)

        # 分割器: 表格 + 详情
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(
            ["ID", "标题", "域名", "原分类", "当前L1", "当前L2", "建议L1", "建议L2", "确认", "删除"]
        )
        headers = self.table.horizontalHeader()
        headers.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        headers.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        headers.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for i in range(3, 10):
            headers.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.itemChanged.connect(self._on_item_changed)
        splitter.addWidget(self.table)

        # 详情面板
        detail_group = QGroupBox("📄 详情")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setMaximumHeight(150)
        self.detail_view.setStyleSheet("font-family: 'Consolas', monospace; font-size: 11px;")
        detail_layout.addWidget(self.detail_view)
        splitter.addWidget(detail_group)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        # 批量操作
        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel("批量操作:"))

        self.batch_confirm_btn = QPushButton("✅ 全部确认可见项")
        self.batch_confirm_btn.clicked.connect(self._batch_confirm)
        batch_row.addWidget(self.batch_confirm_btn)

        self.batch_l1_combo = QComboBox()
        self.batch_l1_combo.addItems([""] + self.l1_list)
        self.batch_l1_combo.setPlaceholderText("批量设置L1")
        batch_row.addWidget(self.batch_l1_combo)

        self.batch_apply_btn = QPushButton("🏷️ 应用L1")
        self.batch_apply_btn.clicked.connect(self._batch_apply_l1)
        batch_row.addWidget(self.batch_apply_btn)

        batch_row.addStretch()

        self.export_excel_btn = QPushButton("📊 导出Excel")
        self.export_excel_btn.clicked.connect(self._export_excel)
        batch_row.addWidget(self.export_excel_btn)

        layout.addLayout(batch_row)

        # 底部按钮
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText("✅ 确认完成")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._update_stats()

    def _populate_table(self):
        self.table.blockSignals(True)
        filter_text = self.filter_combo.currentText()

        # 筛选
        visible = []
        for bm in self.bookmarks:
            if filter_text == "全部" or self._match_filter(bm, filter_text):
                visible.append(bm)

        self.table.setRowCount(len(visible))

        for i, bm in enumerate(visible):
            self.table.setItem(i, 0, QTableWidgetItem(str(bm.id)))
            self.table.setItem(i, 1, QTableWidgetItem(bm.title))
            self.table.setItem(i, 2, QTableWidgetItem(bm.domain))
            self.table.setItem(i, 3, QTableWidgetItem(bm.folder))
            self.table.setItem(i, 4, QTableWidgetItem(bm.category_l1))
            self.table.setItem(i, 5, QTableWidgetItem(bm.category_l2))

            # 建议
            ai = self.ai_results.get(bm.url)
            if ai and ai.success:
                suggest_l1 = ai.category_l1
                suggest_l2 = ai.category_l2
            elif bm.category_l1:
                suggest_l1 = bm.category_l1
                suggest_l2 = bm.category_l2
            else:
                suggest_l1 = ""
                suggest_l2 = ""

            self.table.setItem(i, 6, QTableWidgetItem(suggest_l1))
            self.table.setItem(i, 7, QTableWidgetItem(suggest_l2))

            # 确认 (复选框)
            confirm_item = QTableWidgetItem("")
            confirm_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            confirm_item.setCheckState(Qt.CheckState.Checked if bm.user_confirmed else Qt.CheckState.Unchecked)
            self.table.setItem(i, 8, confirm_item)

            # 删除 (复选框)
            del_item = QTableWidgetItem("")
            del_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            del_item.setCheckState(Qt.CheckState.Checked if bm.user_deleted else Qt.CheckState.Unchecked)
            self.table.setItem(i, 9, del_item)

            # 颜色
            self._color_row(i, bm)

            # 存储引用
            self.table.item(i, 0).setData(Qt.ItemDataRole.UserRole, bm.url)

        self.table.blockSignals(False)
        self._update_stats()

    def _color_row(self, row: int, bm: Bookmark):
        if bm.user_deleted:
            color = QColor(255, 200, 200)
        elif bm.user_confirmed:
            color = QColor(200, 255, 200)
        elif bm.category_l1 == "其他" or not bm.category_l1:
            color = QColor(240, 240, 240)
        elif bm.classify_method and "rule" in bm.classify_method:
            color = QColor(220, 255, 220)
        elif bm.url in self.ai_results:
            color = QColor(255, 230, 180)
        else:
            color = QColor(240, 245, 255)

        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                item.setBackground(color)

    def _match_filter(self, bm: Bookmark, filter_text: str) -> bool:
        if filter_text == "待审核":
            return not bm.user_confirmed and not bm.user_deleted
        elif filter_text == "规则已分":
            return bm.classify_method and "rule" in bm.classify_method and bm.confidence >= 0.8
        elif filter_text == "AI推测":
            return bm.url in self.ai_results and not bm.user_confirmed
        elif filter_text == "待人工":
            return (not bm.category_l1 or bm.category_l1 == "其他") and not bm.user_deleted
        elif filter_text == "已删除":
            return bm.user_deleted
        return True

    def _on_filter(self, text: str):
        self._populate_table()

    def _on_item_changed(self, item: QTableWidgetItem):
        """用户修改表格项"""
        row = item.row()
        col = item.column()
        url_item = self.table.item(row, 0)
        if not url_item:
            return
        url = url_item.data(Qt.ItemDataRole.UserRole)
        if not url:
            return

        # 找到书签
        bm = next((b for b in self.bookmarks if b.url == url), None)
        if not bm:
            return

        if col == 4:  # 当前L1 被改
            bm.category_l1 = item.text()
        elif col == 5:  # 当前L2 被改
            bm.category_l2 = item.text()
        elif col == 8:  # 确认
            bm.user_confirmed = (item.checkState() == Qt.CheckState.Checked)
        elif col == 9:  # 删除
            bm.user_deleted = (item.checkState() == Qt.CheckState.Checked)

        self._update_stats()

    def _batch_confirm(self):
        """全部确认可见行"""
        reply = QMessageBox.question(
            self, "确认", "将标记当前筛选下的所有书签为「已确认」，继续？"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for row in range(self.table.rowCount()):
            item = self.table.item(row, 8)
            if item:
                item.setCheckState(Qt.CheckState.Checked)
                url = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                bm = next((b for b in self.bookmarks if b.url == url), None)
                if bm:
                    bm.user_confirmed = True

        self._update_stats()
        self._populate_table()

    def _batch_apply_l1(self):
        """批量设置 L1"""
        l1 = self.batch_l1_combo.currentText()
        if not l1:
            return

        count = 0
        for row in range(self.table.rowCount()):
            url = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            bm = next((b for b in self.bookmarks if b.url == url), None)
            if bm and not bm.user_deleted:
                bm.category_l1 = l1
                # 设置默认 L2
                subs = self.l2_map.get(l1, [])
                if subs and (not bm.category_l2 or bm.category_l2 == "未分类"):
                    bm.category_l2 = subs[0]
                count += 1

        self._populate_table()
        QMessageBox.information(self, "完成", f"已为 {count} 条书签设置分类: {l1}")

    def _export_excel(self):
        """导出审核 Excel"""
        from modules.excel_writer import generate_review_excel

        path, _ = QFileDialog.getSaveFileName(
            self, "保存审核表", "书签审核.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return

        # 构建 ai_results 格式
        ai_dict = {}
        for url, r in self.ai_results.items():
            ai_dict[url] = r

        output = generate_review_excel(
            bookmarks=self.bookmarks,
            fetch_results=self.fetch_results,
            ai_results=ai_dict,
            categories=self.categories,
            output_path=path,
        )
        QMessageBox.information(self, "导出成功", f"审核表已保存:\n{output}")

    def _update_stats(self):
        total = len(self.bookmarks)
        confirmed = sum(1 for b in self.bookmarks if b.user_confirmed)
        deleted = sum(1 for b in self.bookmarks if b.user_deleted)
        pending = sum(1 for b in self.bookmarks if not b.user_confirmed and not b.user_deleted)
        rule = sum(1 for b in self.bookmarks if b.classify_method and "rule" in b.classify_method)
        ai = sum(1 for b in self.bookmarks if b.url in self.ai_results)

        self.stats_label.setText(
            f"📊 共 {total} 条 | ✅已确认 {confirmed} | ⏳待审核 {pending} "
            f"| 🏷️规则 {rule} | 🤖AI {ai} | 🗑️删除 {deleted}"
        )

    def _on_accept(self):
        """确认完成"""
        deleted = sum(1 for b in self.bookmarks if b.user_deleted)
        pending = sum(1 for b in self.bookmarks if not b.user_confirmed and not b.user_deleted)

        msg = f"审核完成!\n\n"
        msg += f"  已确认: {sum(1 for b in self.bookmarks if b.user_confirmed)}\n"
        msg += f"  待审核: {pending}\n"
        msg += f"  已删除: {deleted}\n\n"
        if pending > 0:
            msg += f"⚠️ 仍有 {pending} 条未确认，将保留当前分类。\n"
        if deleted > 0:
            msg += f"🗑️ {deleted} 条将被删除。\n"
        msg += "\n确认应用以上结果？"

        reply = QMessageBox.question(self, "完成审核", msg)
        if reply == QMessageBox.StandardButton.Yes:
            self.review_completed.emit(self.bookmarks)
            self.accept()

    def show_detail(self, row: int):
        """显示选中行详情"""
        url = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        bm = next((b for b in self.bookmarks if b.url == url), None)
        if not bm:
            return

        text = f"标题: {bm.title}\n"
        text += f"URL: {bm.url}\n"
        text += f"域名: {bm.domain}\n"
        text += f"原文件夹: {bm.folder}\n"
        text += f"当前分类: {bm.category_l1} / {bm.category_l2}\n"
        text += f"方法: {bm.classify_method}\n"
        text += f"置信度: {bm.confidence:.2f}\n"

        fetch = self.fetch_results.get(bm.url)
        if fetch:
            text += f"\n--- 抓取内容 ---\n"
            text += f"引擎: {fetch.engine}\n"
            text += f"标题: {fetch.title}\n"
            text += f"描述: {fetch.description}\n"
            text += f"关键词: {', '.join(fetch.keywords)}\n"
            text += f"正文: {fetch.text[:300]}...\n"

        ai = self.ai_results.get(bm.url)
        if ai:
            text += f"\n--- AI 分类 ---\n"
            text += f"建议: {ai.category_l1} / {ai.category_l2}\n"
            text += f"置信度: {ai.confidence:.2f}\n"
            text += f"理由: {ai.reason}\n"

        self.detail_view.setText(text)

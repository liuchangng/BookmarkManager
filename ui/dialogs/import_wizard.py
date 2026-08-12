"""
import_wizard.py - 导入向导对话框
功能: 引导用户将生成的 HTML 导入浏览器
"""

import logging
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QGroupBox, QMessageBox, QCheckBox, QProgressBar,
    QFileDialog, QRadioButton, QButtonGroup,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from modules.importer import (
    detect_browsers, backup_bookmarks_file,
    open_import_page, create_import_instructions,
)
from modules.html_builder import generate_import_guide

logger = logging.getLogger("import_wizard")


class ImportWizard(QDialog):
    """导入向导 - 引导用户完成最后一步"""

    import_completed = pyqtSignal(str)  # 导入完成信号

    def __init__(self, html_path: str, bookmarks_count: int,
                 deleted_count: int = 0, parent=None):
        super().__init__(parent)
        self.html_path = html_path
        self.bookmarks_count = bookmarks_count
        self.deleted_count = deleted_count

        self.setWindowTitle("📥 导入向导 - 完成分类")
        self.setMinimumSize(650, 500)
        self.resize(700, 550)

        # 检测浏览器
        self.browsers = detect_browsers()
        self.selected_browser = "chrome"

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel("🎉 书签分类完成！")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            f"✅ {self.bookmarks_count} 条书签已分类 | "
            f"🗑️ {self.deleted_count} 条已移除"
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #6B7280;")
        layout.addWidget(subtitle)

        # 文件位置
        file_group = QGroupBox("📄 生成的文件")
        file_layout = QVBoxLayout(file_group)
        self.file_label = QLabel(self.html_path)
        self.file_label.setStyleSheet("font-family: 'Consolas', monospace; color: #2563EB;")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        file_layout.addWidget(self.file_label)

        btn_row = QHBoxLayout()
        open_btn = QPushButton("📂 打开所在文件夹")
        open_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(open_btn)

        copy_btn = QPushButton("📋 复制路径")
        copy_btn.clicked.connect(self._copy_path)
        btn_row.addWidget(copy_btn)

        btn_row.addStretch()
        file_layout.addLayout(btn_row)
        layout.addWidget(file_group)

        # 选择浏览器
        browser_group = QGroupBox("🌐 选择目标浏览器")
        browser_layout = QVBoxLayout(browser_group)

        self.browser_group = QButtonGroup(self)

        for key, info in self.browsers.items():
            row = QHBoxLayout()
            rb = QRadioButton(info.get("name", key))
            rb.setProperty("browser_key", key)
            self.browser_group.addButton(rb)

            if info.get("installed"):
                rb.setText(f"{info['name']} ✅ 已安装")
                rb.setChecked(key == "chrome" or (key == "edge" and not self.browsers.get("chrome", {}).get("installed")))
            else:
                rb.setText(f"{info['name']} ⚪ 未检测到")
                rb.setEnabled(False)

            row.addWidget(rb)
            if info.get("installed"):
                path_label = QLabel(f"📍 {info.get('profile_dir', '')[:50]}...")
                path_label.setStyleSheet("color: #9CA3AF; font-size: 10px;")
                row.addWidget(path_label)
            row.addStretch()
            browser_layout.addLayout(row)

        # 默认选中第一个可用的
        for btn in self.browser_group.buttons():
            if btn.isEnabled():
                btn.setChecked(True)
                self.selected_browser = btn.property("browser_key")
                break

        self.browser_group.buttonClicked.connect(self._on_browser_changed)
        layout.addWidget(browser_group)

        # 导入步骤
        steps_group = QGroupBox("📋 导入步骤")
        steps_layout = QVBoxLayout(steps_group)
        self.steps_view = QTextEdit()
        self.steps_view.setReadOnly(True)
        self.steps_view.setStyleSheet("font-family: 'Consolas', monospace; font-size: 11px;")
        self._update_steps()
        steps_layout.addWidget(self.steps_view)
        layout.addWidget(steps_group, 1)

        # 选项
        options_group = QGroupBox("⚙ 选项")
        opt_layout = QHBoxLayout(options_group)
        self.open_browser_cb = QCheckBox("完成后打开浏览器书签页")
        self.open_browser_cb.setChecked(True)
        opt_layout.addWidget(self.open_browser_cb)
        layout.addWidget(options_group)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.backup_btn = QPushButton("📦 备份原书签")
        self.backup_btn.setObjectName("secondaryBtn")
        self.backup_btn.clicked.connect(self._on_backup)
        btn_row.addWidget(self.backup_btn)

        btn_row.addSpacing(8)

        self.open_page_btn = QPushButton("🌐 打开导入页")
        self.open_page_btn.setObjectName("secondaryBtn")
        self.open_page_btn.clicked.connect(self._on_open_page)
        btn_row.addWidget(self.open_page_btn)

        btn_row.addSpacing(8)

        self.done_btn = QPushButton("✅ 完成")
        self.done_btn.setObjectName("primaryBtn")
        self.done_btn.clicked.connect(self._on_done)
        btn_row.addWidget(self.done_btn)

        layout.addLayout(btn_row)

    def _on_browser_changed(self, btn):
        self.selected_browser = btn.property("browser_key")
        self._update_steps()

    def _update_steps(self):
        instructions = create_import_instructions(self.html_path, self.selected_browser)
        guide = generate_import_guide(self.selected_browser)
        self.steps_view.setText(instructions + "\n" + guide)

    def _open_folder(self):
        import subprocess, platform
        path = str(Path(self.html_path).parent)
        system = platform.system().lower()
        try:
            if system == "windows":
                subprocess.Popen(f'explorer "{path}"')
            elif system == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(self, "提示", f"无法打开文件夹: {e}")

    def _copy_path(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.html_path)
        QMessageBox.information(self, "已复制", "文件路径已复制到剪贴板")

    def _on_backup(self):
        """备份原浏览器书签"""
        browser_info = self.browsers.get(self.selected_browser, {})
        bm_file = browser_info.get("bookmarks_file", "")

        if not bm_file or not Path(bm_file).exists():
            QMessageBox.warning(
                self, "无法备份",
                f"未找到 {self.selected_browser} 的书签文件\n\n"
                f"期望路径: {bm_file}\n\n"
                "你可以手动在浏览器中导出书签作为备份。"
            )
            return

        backup_path = backup_bookmarks_file(bm_file)
        if backup_path:
            QMessageBox.information(self, "备份完成", f"原书签已备份到:\n{backup_path}")
        else:
            QMessageBox.warning(self, "备份失败", "备份过程中出现错误")

    def _on_open_page(self):
        """打开浏览器导入页"""
        url_map = {
            "chrome": "chrome://bookmarks/",
            "edge": "edge://favorites/",
        }
        url = url_map.get(self.selected_browser, "")
        if not url:
            QMessageBox.information(
                self, "提示",
                f"请手动打开 {self.selected_browser} 的书签管理页面，\n"
                "然后选择「导入书签」并选择文件:\n\n"
                f"{self.html_path}"
            )
            return

        # 尝试用浏览器打开
        import subprocess, platform
        system = platform.system().lower()
        try:
            if system == "windows":
                subprocess.Popen(f'start "" "{url}"', shell=True)
            elif system == "darwin":
                subprocess.Popen(["open", url])
            else:
                subprocess.Popen(["xdg-open", url])
            self.steps_view.append(f"\n✅ 已打开: {url}")
        except Exception as e:
            self.steps_view.append(f"\n❌ 无法打开: {e}")
            self.steps_view.append(f"请手动访问: {url}")

    def _on_done(self):
        """完成"""
        if self.open_browser_cb.isChecked():
            self._on_open_page()

        self.import_completed.emit(self.html_path)
        self.accept()

"""
main_window.py - 主窗口
Phase 4: 集成网页抓取 (Scrapling + Firecrawl)
"""

import logging
import time
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QLineEdit, QComboBox, QCheckBox,
    QTextEdit, QProgressBar, QStatusBar, QToolBar, QSizePolicy,
    QFrame, QGroupBox, QSpacerItem, QMessageBox, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QTreeWidget, QTreeWidgetItem, QSplitter, QApplication,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QAction, QIcon, QFont, QColor

from modules.config_manager import ConfigManager
from modules.secure_store import SecureStore
from modules.proxy import ProxyManager
from modules.exporter import BookmarkExporter
from modules.parser import BookmarkParser
from modules.classifier import Classifier
from modules.cache import ClassifyCache
from modules.fetcher import WebFetcher, ProxyAdapter
from modules.fetch_worker import FetchWorker
from modules.classify_worker import ClassifyWorker
from modules.ai_client import DeepSeekClient, AIResult, test_api_key
from modules.ai_worker import AIWorker
from modules.excel_writer import generate_review_excel, apply_review
from modules.html_builder import BookmarkHTMLBuilder, build_and_save, validate_html, generate_preview_tree
from modules.importer import detect_browsers, backup_bookmarks_file, open_import_page
from modules.bookmark import Bookmark

from ui.dialogs.settings_dialog import SettingsDialog
from ui.dialogs.review_dialog import ReviewDialog
from ui.dialogs.import_wizard import ImportWizard
from ui.stats_dashboard import StatsDashboard

logger = logging.getLogger("ui.main")


class ExportWorker(QThread):
    """后台执行导出+解析的 worker 线程"""

    progress = pyqtSignal(str)
    progress_detail = pyqtSignal(str)
    finished_ok = pyqtSignal(list)
    finished_error = pyqtSignal(str)

    def __init__(self, exporter: BookmarkExporter, parser: BookmarkParser,
                 browser: str, profile: str, parent=None):
        super().__init__(parent)
        self.exporter = exporter
        self.parser = parser
        self.browser = browser
        self.profile = profile

    def run(self):
        try:
            self.progress.emit("正在导出收藏夹...")
            self.progress_detail.emit("导出中...")

            # force=True: 浏览器进程已在 UI 线程中处理，这里不再重复检查
            export_path = self.exporter.export(self.browser, self.profile, force=True)
            self.progress.emit(f"✅ 导出成功: {Path(export_path).name}")

            self.progress.emit("正在解析书签...")
            self.progress_detail.emit("解析中...")

            bookmarks = self.parser.parse(export_path)
            if not bookmarks:
                self.finished_error.emit("解析结果为空")
                return

            self.progress.emit(f"✅ 解析完成: {len(bookmarks)} 条书签")
            self.finished_ok.emit(bookmarks)

        except FileNotFoundError as e:
            self.finished_error.emit(str(e))
        except RuntimeError as e:
            self.finished_error.emit(str(e))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished_error.emit(f"{type(e).__name__}: {e}")


class FileImportWorker(QThread):
    """后台执行手动导入书签文件 + 解析的 worker（核心入口）"""

    progress = pyqtSignal(str)
    progress_detail = pyqtSignal(str)
    finished_ok = pyqtSignal(list)
    finished_error = pyqtSignal(str)

    def __init__(self, filepath: str, parser: BookmarkParser, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.parser = parser

    def run(self):
        try:
            self.progress.emit("正在解析书签文件...")
            self.progress_detail.emit("解析中...")

            bookmarks = self.parser.parse(self.filepath)
            if not bookmarks:
                self.finished_error.emit("解析结果为空，文件中没有书签")
                return

            # 手动导入文件常含重复书签，自动去重
            merged = self.parser.merge_duplicates(bookmarks)
            dup = len(bookmarks) - len(merged)
            self.progress.emit(
                f"✅ 解析完成: {len(merged)} 条书签" +
                (f"（去重移除 {dup} 条重复）" if dup > 0 else "")
            )
            self.finished_ok.emit(merged)

        except FileNotFoundError as e:
            self.finished_error.emit(f"文件不存在: {e}")
        except RuntimeError as e:
            self.finished_error.emit(str(e))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished_error.emit(f"{type(e).__name__}: {e}")


class ProbeWorker(QThread):
    """后台执行 URL 体检（本地/死链三态分流），不阻塞 UI"""

    progress = pyqtSignal(str)
    progress_detail = pyqtSignal(str)
    finished_ok = pyqtSignal(list)
    finished_error = pyqtSignal(str)

    def __init__(self, bookmarks: list, cache_dir: str, parent=None):
        super().__init__(parent)
        self.bookmarks = bookmarks
        self.cache_dir = cache_dir

    def run(self):
        try:
            from modules.link_probe import LinkProbeCache, probe_urls

            total = len(self.bookmarks)
            self.progress.emit(f"🔍 链接体检 {total} 条...")
            self.progress_detail.emit("体检中...")

            cache = LinkProbeCache(cache_dir=self.cache_dir)
            probes = probe_urls([b.url for b in self.bookmarks], cache=cache)

            counts = {"ok": 0, "dead": 0, "local": 0, "pending": 0}
            for bm in self.bookmarks:
                r = probes.get(bm.url)
                if not r:
                    continue
                bm.status = r.status
                bm.probe_error = r.error
                bm.http_status = r.http_status
                counts[r.status] = counts.get(r.status, 0) + 1

                # 系统级桶分流（不参与规则引擎）
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

            self.progress.emit(
                f"✅ 体检完成: 正常{counts.get('ok', 0)} 失效{counts.get('dead', 0)} "
                f"本地{counts.get('local', 0)} 待定{counts.get('pending', 0)}"
            )
            self.finished_ok.emit(self.bookmarks)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished_error.emit(f"链接体检失败: {type(e).__name__}: {e}")


def _status_text(bm, fetched: bool = False) -> str:
    """T5.1: 状态列文案（探活三态 + 抓取标记）"""
    status_map = {"ok": "✅正常", "dead": "⚠️失效", "local": "📁本地"}
    text = status_map.get(bm.status, "🕐待定")
    if fetched:
        text += "·已抓"
    return text


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self, config: ConfigManager, secure_store: SecureStore,
                 proxy_manager: ProxyManager):
        super().__init__()
        self.config = config
        self.secure_store = secure_store
        self.proxy_manager = proxy_manager

        self.setWindowTitle("🔖 收藏夹管理工具 v1.0")
        self.setMinimumSize(900, 600)
        w = config.get("ui.window_width", 1200)
        h = config.get("ui.window_height", 800)
        self.resize(w, h)

        # 数据
        self.bookmarks: list[Bookmark] = []
        self.fetch_results: dict = {}
        self.ai_results: dict = {}

        # Phase 3: 分类器 + 缓存
        self.classifier = Classifier(str(config.config_path))
        cache_dir = config.get("classification.cache_dir", "data/cache")
        self.cache = ClassifyCache(cache_dir=cache_dir)

        # Phase 4: 抓取器
        self.fetcher = WebFetcher(
            config=self._build_fetcher_config(),
            proxy_adapter=ProxyAdapter(proxy_manager=proxy_manager, config=self._build_fetcher_config()),
        )
        # Firecrawl API Key
        fc_key = self.secure_store.load("firecrawl_api_key")
        if fc_key:
            self.fetcher.set_firecrawl_key(fc_key)

        # Workers
        self.export_worker: Optional[ExportWorker] = None
        self.classify_worker: Optional[ClassifyWorker] = None
        self.fetch_worker: Optional[FetchWorker] = None

        self._init_ui()
        self._init_toolbar()
        self._init_statusbar()
        self._refresh_status()

    def _build_fetcher_config(self) -> dict:
        """构建 fetcher 所需的 config dict"""
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
            "classification": {"cache_dir": self.config.get("classification.cache_dir", "data/cache")},
        }

    # ──────────────────────────────────────────────
    #  UI 构建
    # ──────────────────────────────────────────────

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(10)

        # 配置警告栏
        root.addWidget(self._create_config_warning())

        # 步骤导航
        root.addWidget(self._create_step_nav())

        # 操作面板
        root.addWidget(self._create_action_panel())

        # 进度条 + 进度详情
        progress_card = QFrame()
        progress_card.setObjectName("progressCard")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(14, 10, 14, 10)
        progress_layout.setSpacing(6)

        progress_header = QHBoxLayout()
        progress_title = QLabel("⏱ 执行进度")
        progress_title.setObjectName("cardTitle")
        progress_header.addWidget(progress_title)
        progress_header.addStretch()
        self.progress_detail = QLabel("")
        self.progress_detail.setObjectName("progressDetail")
        progress_header.addWidget(self.progress_detail)
        progress_layout.addLayout(progress_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("就绪")
        self.progress_bar.setMinimumHeight(22)
        progress_layout.addWidget(self.progress_bar)

        root.addWidget(progress_card)

        # 分割器: 预览表 + 日志
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._create_preview_table())
        splitter.addWidget(self._create_log_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

    def _create_config_warning(self) -> QWidget:
        """配置警告栏 - 红色加粗显示缺失的配置"""
        bar = QFrame()
        bar.setObjectName("configWarning")
        bar.setVisible(False)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)

        self.warning_icon = QLabel("⚠️")
        self.warning_icon.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.warning_icon)

        self.warning_text = QLabel()
        self.warning_text.setObjectName("warningText")
        self.warning_text.setWordWrap(True)
        layout.addWidget(self.warning_text, 1)

        self.warning_dismiss = QPushButton("✕")
        self.warning_dismiss.setFixedSize(20, 20)
        self.warning_dismiss.setObjectName("warningDismiss")
        self.warning_dismiss.clicked.connect(lambda: bar.setVisible(False))
        layout.addWidget(self.warning_dismiss)

        self._update_config_warning()
        return bar

    def _update_config_warning(self):
        """更新配置警告内容"""
        warnings = []

        # 检查 AI API Key
        if not self.secure_store.exists("deepseek"):
            warnings.append("未配置 AI API Key — AI 分类功能不可用")

        # 检查代理
        if not self.config.get("proxy.enabled", False):
            # 代理不是强制的，仅提示
            pass

        if warnings:
            self.warning_text.setText("  ".join(warnings))
            bar = self.warning_text.parent() if self.warning_text else None
            if bar:
                bar.setVisible(True)

    def _create_step_nav(self) -> QWidget:
        """步骤导航条 - 显示各步骤状态，带圆点指示器"""
        bar = QFrame()
        bar.setObjectName("stepNav")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(6)

        # 左侧标题 (颜色由 QSS 控制，随主题切换)
        nav_title = QLabel("📋 处理流程")
        nav_title.setObjectName("navTitle")
        nav_title.setStyleSheet("font-size: 13px; font-weight: 700; margin-right: 8px;")
        layout.addWidget(nav_title)

        self.step_labels = []
        self.step_arrows = []
        self.step_dots = []
        steps = [
            ("获取", "解析"),
            ("规则", "分类"),
            ("网页", "抓取"),
            ("AI", "补充"),
            ("审核", "输出"),
            ("导入", "浏览器"),
        ]
        for i, (line1, line2) in enumerate(steps):
            # 圆点指示器
            dot = QLabel("●")
            dot.setObjectName("stepDot")
            dot.setFixedWidth(12)
            dot.setStyleSheet("")
            self.step_dots.append(dot)

            # 步骤标签
            lbl = QLabel(f"{line1}\n{line2}")
            lbl.setObjectName("stepPending")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setMinimumWidth(52)
            self.step_labels.append(lbl)

            # 用垂直容器组合 dot + label
            step_widget = QWidget()
            step_layout = QVBoxLayout(step_widget)
            step_layout.setContentsMargins(4, 0, 4, 0)
            step_layout.setSpacing(4)
            step_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignCenter)
            step_layout.addWidget(lbl, 0, Qt.AlignmentFlag.AlignCenter)

            layout.addWidget(step_widget)

            if i < len(steps) - 1:
                arrow = QLabel("→")
                arrow.setObjectName("stepArrow")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(arrow)
                self.step_arrows.append(arrow)

        layout.addStretch()

        # 初始设置 dots 状态
        self._update_step_dots()
        return bar

    def _update_step_dots(self):
        """同步 dots 颜色与 label 状态一致"""
        for i, lbl in enumerate(self.step_labels):
            name = lbl.objectName()
            dot = self.step_dots[i]
            colors = {
                "stepDone": "#16A34A",
                "stepCurrent": "#3B82F6",
                "stepError": "#DC2626",
                "stepPending": "#CBD5E1",
            }
            color = colors.get(name, "#CBD5E1")
            dot.setStyleSheet(f"color: {color}; font-size: 10px;")

    def _set_step_state(self, idx: int, state: str):
        """
        设置步骤状态
        state: 'done' / 'current' / 'error' / 'pending'
        """
        label_names = {
            "done": "stepDone",
            "current": "stepCurrent",
            "error": "stepError",
            "pending": "stepPending",
        }
        for i, lbl in enumerate(self.step_labels):
            if i == idx:
                lbl.setObjectName(label_names.get(state, "stepPending"))
            elif i < idx:
                lbl.setObjectName("stepDone")
            else:
                lbl.setObjectName("stepPending")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

        # 同步 dot 指示器颜色
        self._update_step_dots()

    def _set_step_active(self, idx: int):
        """将步骤 idx 设为执行中"""
        self._set_step_state(idx, "current")

    def _set_step_error(self, idx: int):
        """将步骤 idx 设为错误"""
        self._set_step_state(idx, "error")

    # ──────────── 中文对话框辅助 ────────────

    def _cn_question(self, title: str, text: str, default_yes: bool = True) -> bool:
        """中文确认对话框：返回 True=是, False=否"""
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(QMessageBox.Icon.Question)
        yes_btn = msg.addButton("是", QMessageBox.ButtonRole.YesRole)
        no_btn = msg.addButton("否", QMessageBox.ButtonRole.NoRole)
        if default_yes:
            msg.setDefaultButton(yes_btn)
        else:
            msg.setDefaultButton(no_btn)
        msg.exec()
        return msg.clickedButton() == yes_btn

    def _cn_ok(self, title: str, text: str, icon=QMessageBox.Icon.Information):
        """中文信息对话框"""
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(icon)
        ok_btn = msg.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
        msg.setDefaultButton(ok_btn)
        msg.exec()

    def _cn_warning(self, title: str, text: str):
        """中文警告对话框"""
        self._cn_ok(title, text, QMessageBox.Icon.Warning)

    def _cn_error(self, title: str, text: str):
        """中文错误对话框"""
        self._cn_ok(title, text, QMessageBox.Icon.Critical)

    def _create_action_panel(self) -> QWidget:
        """操作面板 - 浏览器选择 + 启动按钮，现代卡片式分组"""
        card = QFrame()
        card.setObjectName("actionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        # 标题
        title_row = QHBoxLayout()
        title = QLabel("🎯 书签获取")
        title.setObjectName("cardTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        # 浏览器选择区域
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        browser_group = QHBoxLayout()
        browser_group.setSpacing(6)
        lbl_browser = QLabel("浏览器")
        lbl_browser.setObjectName("fieldLabel")
        browser_group.addWidget(lbl_browser)

        self.browser_combo = QComboBox()
        self.browser_combo.addItems(["自动检测", "Chrome", "Edge"])
        self.browser_combo.setMinimumWidth(130)
        browser_group.addWidget(self.browser_combo)
        input_row.addLayout(browser_group)

        profile_group = QHBoxLayout()
        profile_group.setSpacing(6)
        lbl_profile = QLabel("用户配置")
        lbl_profile.setObjectName("fieldLabel")
        profile_group.addWidget(lbl_profile)

        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self.profile_combo.addItems(["Default", "Profile 1", "Profile 2"])
        self.profile_combo.setMinimumWidth(220)
        self.profile_combo.setPlaceholderText("输入自定义路径或选择配置")
        profile_group.addWidget(self.profile_combo)
        input_row.addLayout(profile_group)

        input_row.addStretch()

        self.start_btn = QPushButton("🚀 一键处理")
        self.start_btn.setObjectName("primaryBtn")
        self.start_btn.setMinimumHeight(42)
        self.start_btn.setMinimumWidth(140)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setToolTip("开始完整流程：导出→解析→分类→抓取→AI→审核→生成HTML")
        self.start_btn.clicked.connect(self._on_start)
        input_row.addWidget(self.start_btn)

        layout.addLayout(input_row)

        # 手动导入入口（核心功能：直接选择书签文件，免去浏览器检测/关闭）
        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        self.import_btn = QPushButton("📂 导入书签文件")
        self.import_btn.setObjectName("secondaryBtn")
        self.import_btn.setMinimumHeight(34)
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_btn.setToolTip("选择浏览器导出的 HTML/JSON 书签文件直接解析（无需关闭浏览器）")
        self.import_btn.clicked.connect(self._on_import_file)
        import_row.addWidget(self.import_btn)
        import_hint = QLabel("或选择已导出的书签文件 (HTML / JSON)，免去浏览器检测与关闭")
        import_hint.setStyleSheet("color: #94A3B8; font-size: 11.5px;")
        import_row.addWidget(import_hint)
        import_row.addStretch()
        layout.addLayout(import_row)

        # 状态摘要行
        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        self.export_status = QLabel("💾 未导出")
        self.export_status.setStyleSheet("color: #94A3B8; font-size: 11.5px;")
        status_row.addWidget(self.export_status)
        self.classify_status = QLabel("🏷️ 未分类")
        self.classify_status.setStyleSheet("color: #94A3B8; font-size: 11.5px;")
        status_row.addWidget(self.classify_status)
        status_row.addStretch()
        layout.addLayout(status_row)

        return card

    def _create_preview_table(self) -> QWidget:
        """书签预览表格 + 分类分布 - 现代表格样式"""
        card = QFrame()
        card.setObjectName("previewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        # 标题行
        title_row = QHBoxLayout()
        title = QLabel("📋 书签预览")
        title.setObjectName("cardTitle")
        title_row.addWidget(title)

        title_row.addSpacing(16)
        title_row.addWidget(QLabel("筛选"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["全部", "已分类", "待AI/人工", "已抓取", "失效链接", "已删除"])
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        self.filter_combo.setMinimumWidth(130)
        title_row.addWidget(self.filter_combo)

        # T5.2: 一键删除失效链接（二次确认）
        self.delete_dead_btn = QPushButton("🗑️ 删除失效")
        self.delete_dead_btn.setObjectName("dangerBtn")
        self.delete_dead_btn.setEnabled(False)
        self.delete_dead_btn.setToolTip("将所有状态为「失效」的书签标记为删除（可二次确认）")
        self.delete_dead_btn.clicked.connect(self._delete_dead_bookmarks)
        title_row.addWidget(self.delete_dead_btn)

        title_row.addStretch()
        self.preview_count = QLabel("尚未加载")
        self.preview_count.setObjectName("previewCount")
        title_row.addWidget(self.preview_count)
        layout.addLayout(title_row)

        # 统计仪表盘（初始隐藏）
        self.stats_dashboard = StatsDashboard()
        layout.addWidget(self.stats_dashboard)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            ["#", "标题", "域名", "原文件夹", "分类(一级)", "分类(二级)", "方法", "状态", "操作"]
        )
        headers = self.table.horizontalHeader()
        headers.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        headers.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        headers.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        headers.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        headers.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        headers.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        headers.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        headers.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        headers.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setMaximumHeight(260)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # 分类分布树
        self.dist_tree = QTreeWidget()
        self.dist_tree.setHeaderHidden(True)
        self.dist_tree.setMaximumHeight(80)
        self.dist_tree.setIndentation(16)
        layout.addWidget(self.dist_tree)

        return card

    def _create_log_panel(self) -> QWidget:
        """日志面板 - 暗色终端风格"""
        card = QFrame()
        card.setObjectName("logCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        lbl = QLabel("📜 运行日志")
        lbl.setObjectName("cardTitle")
        header.addWidget(lbl)
        header.addStretch()
        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("secondaryBtn")
        clear_btn.setFixedSize(50, 26)
        clear_btn.clicked.connect(lambda: self.log_view.clear())
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(130)
        self.log_view.setPlaceholderText("等待操作...")
        layout.addWidget(self.log_view)
        return card

    # ──────────────────────────────────────────────
    #  工具栏 & 状态栏
    # ──────────────────────────────────────────────

    def _init_toolbar(self):
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))

        settings_act = QAction("⚙️  设置", self)
        settings_act.triggered.connect(self._open_settings)
        settings_act.setToolTip("打开系统设置 (代理、API Key、分类规则)")
        tb.addAction(settings_act)

        tb.addSeparator()

        test_proxy_act = QAction("🌐  测试代理", self)
        test_proxy_act.triggered.connect(self._test_proxy)
        test_proxy_act.setToolTip("测试当前代理配置的连通性")
        tb.addAction(test_proxy_act)

        tb.addSeparator()

        refresh_act = QAction("🔄  刷新状态", self)
        refresh_act.triggered.connect(self._refresh_status)
        refresh_act.setToolTip("刷新状态栏信息")
        tb.addAction(refresh_act)

        # 右侧弹性空间
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        # 版本标签
        version_lbl = QLabel("v1.0")
        version_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; padding: 0 8px;")
        tb.addWidget(version_lbl)

        self.addToolBar(tb)

    def _init_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def _refresh_status(self):
        proxy_on = "🟢代理开" if self.proxy_manager.is_enabled() else "⚪代理关"
        fc_on = "🟢FC开" if self.fetcher.firecrawl_enabled else "⚪FC关"
        fc_key = "🔑已配置" if self.fetcher.firecrawl_api_key else "🔒未配置"
        cache_stats = self.cache.stats()

        # 更新操作面板状态行
        bm_count = len(self.bookmarks) if hasattr(self, 'bookmarks') else 0
        if bm_count > 0:
            self.export_status.setText(f"💾 已导出 {bm_count} 条")
            self.export_status.setStyleSheet("color: #16A34A; font-size: 11.5px;")
            classified = sum(1 for bm in self.bookmarks if bm.category_l1 and bm.category_l1 != "其他")
            self.classify_status.setText(f"🏷️ 已分类 {classified}/{bm_count}")
            if classified == bm_count:
                self.classify_status.setStyleSheet("color: #16A34A; font-size: 11.5px;")
            else:
                self.classify_status.setStyleSheet("color: #F59E0B; font-size: 11.5px;")
        else:
            self.export_status.setText("💾 未导出")
            self.export_status.setStyleSheet("color: #94A3B8; font-size: 11.5px;")
            self.classify_status.setText("🏷️ 未分类")
            self.classify_status.setStyleSheet("color: #94A3B8; font-size: 11.5px;")

        status = f"{proxy_on} | {fc_on} | {fc_key} | 缓存:{cache_stats['total']}条"
        self.status_bar.showMessage(status)

    # ──────────────────────────────────────────────
    #  日志
    # ──────────────────────────────────────────────

    def append_log(self, level: str, msg: str):
        color = {"INFO": "#333", "SUCCESS": "#28a745", "WARN": "#ffc107",
                 "ERROR": "#dc3545", "DEBUG": "#6c757d"}.get(level, "#333")
        icon = {"INFO": "ℹ️", "SUCCESS": "✅", "WARN": "⚠️",
                "ERROR": "❌", "DEBUG": "🔍"}.get(level, "")
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.append(f'<span style="color:#999">{timestamp}</span> '
                             f'<span style="color:{color}">{icon} {msg}</span>')
        # 同时写 logger
        getattr(logger, level.lower(), logger.info)(msg)

    # ──────────────────────────────────────────────
    #  操作: 导出+解析
    # ──────────────────────────────────────────────

    def _on_start(self):
        browser = self.browser_combo.currentText()
        profile = self.profile_combo.currentText()

        # ── 首次配置提醒 ──
        if not hasattr(self, '_first_warning_shown'):
            self._first_warning_shown = True
            missing = []
            if not self.secure_store.exists("deepseek"):
                missing.append("• AI API Key — 若需 AI 分类功能请先在 ⚙️设置 → AI/LLM 中配置")
            if not self.config.get("proxy.enabled", False):
                missing.append("• 代理 — 若需通过代理访问网络请先在 ⚙️设置 → 代理中启用")
            if missing:
                self._cn_ok("⚠️ 使用前提醒",
                    "开始处理前，请确保以下配置已完成：\n\n" +
                    "\n".join(missing) +
                    "\n\n未配置的功能将自动跳过，不影响整体流程。")

        self.append_log("INFO", f"开始处理: {browser} / {profile}")

        # ── 浏览器进程检测 + 弹框 (中文按钮) ──
        exporter = BookmarkExporter(self.config)
        if exporter.check_running(browser):
            browser_name = exporter.get_browser_display_name(browser)
            msg = (
                f"{browser_name} 正在运行中。\n\n"
                f"浏览器运行时书签文件可能被锁定，无法读取。\n"
                "是否自动关闭浏览器并继续导出？"
            )
            if not self._cn_question(f"{browser_name} 正在运行", msg, default_yes=True):
                self.append_log("WARN", "用户取消操作")
                return
            self.append_log("INFO", f"正在关闭 {browser_name}...")
            if exporter.kill_browser(browser):
                self.append_log("SUCCESS", f"✅ {browser_name} 已关闭")
                time.sleep(0.5)
            else:
                self.append_log("WARN", f"⚠️ 无法自动关闭 {browser_name}，请手动关闭后重试")
                return

        # ── 启动自动化流程 ──
        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 处理中...")
        self.progress_bar.setValue(5)
        self.progress_bar.setFormat("导出中...")
        self._chain_step_idx = 0
        self._set_step_active(0)

        parser = BookmarkParser()

        self.export_worker = ExportWorker(exporter, parser, browser, profile, self)
        self.export_worker.progress.connect(self._on_export_log)
        self.export_worker.progress_detail.connect(self._on_worker_detail)
        self.export_worker.finished_ok.connect(self._on_worker_success)
        self.export_worker.finished_error.connect(self._on_worker_error)
        self.export_worker.start()

    # ──────────────────────────────────────────────
    #  操作: 手动导入书签文件（核心功能）
    # ──────────────────────────────────────────────

    def _on_import_file(self):
        """手动导入浏览器导出的书签文件 → 解析 → 自动进入分类流程"""
        path, _ = QFileDialog.getOpenFileName(
            self, "📂 选择书签文件", "",
            "书签文件 (*.html *.htm *.json);;HTML 书签 (*.html *.htm);;Chrome JSON (*.json);;所有文件 (*)",
        )
        if not path:
            return

        self.append_log("INFO", f"📂 选择书签文件: {path}")
        self._set_import_btn_enabled(False)
        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 处理中...")
        self.progress_bar.setValue(5)
        self.progress_bar.setFormat("解析中...")
        self._chain_step_idx = 0
        self._set_step_active(0)

        parser = BookmarkParser()
        self.import_worker = FileImportWorker(path, parser, self)
        self.import_worker.progress.connect(self._on_export_log)
        self.import_worker.progress_detail.connect(self._on_worker_detail)
        self.import_worker.finished_ok.connect(self._on_worker_success)
        self.import_worker.finished_error.connect(self._on_worker_error)
        self.import_worker.start()

    def _set_import_btn_enabled(self, enabled: bool):
        """启停「导入书签文件」按钮（兼容未初始化场景）"""
        btn = getattr(self, "import_btn", None)
        if btn is not None:
            btn.setEnabled(enabled)

    @pyqtSlot(str)
    def _on_export_log(self, msg: str):
        level = "INFO"
        if "✅" in msg: level = "SUCCESS"
        elif "❌" in msg or "失败" in msg: level = "ERROR"
        elif "⚠️" in msg: level = "WARN"
        self.append_log(level, msg)

    @pyqtSlot(str)
    def _on_worker_detail(self, msg: str):
        self.progress_detail.setText(msg)

    @pyqtSlot(list)
    def _on_worker_success(self, bookmarks: list):
        self.bookmarks = bookmarks
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat(f"完成! {len(bookmarks)} 条")

        self._populate_table(bookmarks)
        self.preview_count.setText(f"{len(bookmarks)} 条")
        self._update_stats()

        self._set_step_state(0, "done")
        self._set_step_active(1)
        self.append_log("SUCCESS", f"🎉 导出+解析完成! 共 {len(bookmarks)} 条书签")
        self._refresh_status()

        # ── 自动链式下一步: URL 体检（本地/死链分流）→ 规则分类 ──
        self._start_probe()

    @pyqtSlot(str)
    def _on_worker_error(self, error_msg: str):
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("❌ 失败")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 一键处理")
        self._set_import_btn_enabled(True)
        self.append_log("ERROR", error_msg)
        self._set_step_error(0)
        self._cn_error("处理失败", error_msg)

    # ──────────────────────────────────────────────
    #  链式工作流: URL 体检（T1）
    # ──────────────────────────────────────────────

    def _start_probe(self):
        """解析完成后先做 URL 体检（本地/死链分流），再进入规则分类"""
        if not self.bookmarks:
            self._chain_classify()
            return

        cache_dir = self.config.get("classification.cache_dir", "data/cache")
        self.probe_worker = ProbeWorker(self.bookmarks, cache_dir=f"{cache_dir}/probe", parent=self)
        self.probe_worker.progress.connect(self._on_export_log)
        self.probe_worker.progress_detail.connect(self._on_worker_detail)
        self.probe_worker.finished_ok.connect(self._on_probe_success)
        self.probe_worker.finished_error.connect(self._on_probe_error)
        self.probe_worker.start()

    @pyqtSlot(list)
    def _on_probe_success(self, bookmarks: list):
        """体检完成 → 刷新预览（含状态列/系统桶分布）→ 进入规则分类"""
        self.bookmarks = bookmarks
        self._populate_table(bookmarks)
        self._update_dist_tree(bookmarks)   # T5.4: 系统桶（失效/本地）计数入树
        self._refresh_status()
        self._chain_classify()

    @pyqtSlot(str)
    def _on_probe_error(self, error_msg: str):
        """体检失败不阻塞流程，降级为不体检直接分类"""
        self.append_log("WARN", error_msg)
        self._chain_classify()

    # ──────────────────────────────────────────────
    #  链式工作流: 规则分类
    # ──────────────────────────────────────────────

    def _chain_classify(self):
        """自动化: 规则分类"""
        if not self.bookmarks:
            return

        self.append_log("INFO", "开始规则分类...")
        self.progress_bar.setValue(15)
        self.progress_bar.setFormat("分类中...")
        self._chain_step_idx = 1
        self._set_step_active(1)

        self.classify_worker = ClassifyWorker(self.bookmarks, self.classifier, self.cache, self)
        self.classify_worker.progress.connect(self._on_classify_log)
        self.classify_worker.progress_detail.connect(self._on_worker_detail)
        self.classify_worker.finished_ok.connect(self._on_classify_success)
        self.classify_worker.finished_error.connect(self._on_chain_error)
        self.classify_worker.cache_stats.connect(self._on_cache_stats)
        self.classify_worker.start()

    @pyqtSlot(str)
    def _on_classify_log(self, msg: str):
        level = "INFO"
        if "✅" in msg: level = "SUCCESS"
        elif "❌" in msg: level = "ERROR"
        elif "⚠️" in msg: level = "WARN"
        self.append_log(level, msg)

    @pyqtSlot(list)
    def _on_classify_success(self, bookmarks: list):
        self.bookmarks = bookmarks
        self.progress_bar.setValue(30)
        self.progress_bar.setFormat("分类完成!")

        self._populate_table(bookmarks)
        self._update_dist_tree(bookmarks)
        self._update_stats()

        classified = sum(1 for bm in bookmarks if bm.category_l1 and bm.category_l1 != "其他")
        unmatched = sum(1 for bm in bookmarks if not bm.category_l1 or bm.category_l1 == "其他")
        self.preview_count.setText(f"{len(bookmarks)} 条 (已分:{classified} 待处理:{unmatched})")

        if unmatched > 0:
            self.append_log("WARN", f"⚠️ {unmatched} 条待 AI/人工分类")
        else:
            self.append_log("SUCCESS", f"🎉 全部 {len(bookmarks)} 条已分类!")

        self._set_step_state(1, "done")

        cache_s = self.cache.stats()
        self.append_log("INFO", f"💾 缓存: {cache_s['total']}条 | 命中率: {cache_s['hit_rate']*100:.0f}%")
        self._refresh_status()

        # ── 自动链式下一步: 网页抓取 ──
        self._chain_fetch()

    @pyqtSlot(str)
    def _on_chain_error(self, error_msg: str):
        """链式工作流出错 - 标记步骤为错误，恢复按钮"""
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("❌ 失败")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 一键处理")
        self.append_log("ERROR", error_msg)
        # 标记当前步骤为错误状态
        step_idx = getattr(self, '_chain_step_idx', 0)
        self._set_step_error(step_idx)
        self._cn_error("处理失败", error_msg)

    @pyqtSlot(dict)
    def _on_cache_stats(self, stats: dict):
        self.append_log("INFO", f"💾 缓存: 命中{stats['hits']} 未命中{stats['misses']}")

    # ──────────────────────────────────────────────
    #  链式工作流: 网页抓取
    # ──────────────────────────────────────────────

    def _chain_fetch(self):
        """自动化: 网页抓取（仅抓取未分类的书签）"""
        if not self.bookmarks:
            self._chain_ai()
            return

        to_fetch = []
        for bm in self.bookmarks:
            if bm.user_deleted:
                continue
            if bm.status in ("local", "dead"):
                continue  # 本地/失效书签不抓取
            if bm.category_l1 and bm.category_l1 != "其他":
                continue
            if bm.url in self.fetch_results:
                continue
            to_fetch.append(bm.url)

        if not to_fetch:
            self.append_log("INFO", "所有书签已分类或已抓取，无需抓取")
            self._set_step_state(2, "done")
            self._chain_ai()
            return

        self.append_log("INFO", f"准备抓取 {len(to_fetch)} 个 URL...")
        self.progress_bar.setValue(30)
        self.progress_bar.setFormat(f"抓取中... 0/{len(to_fetch)}")
        self._chain_step_idx = 2
        self._set_step_active(2)

        seen = set()
        unique_urls = []
        for u in to_fetch:
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)

        self.fetch_worker = FetchWorker(self.fetcher, unique_urls, self)
        self.fetch_worker.progress.connect(self._on_fetch_log)
        self.fetch_worker.progress_detail.connect(self._on_fetch_detail)
        self.fetch_worker.item_done.connect(self._on_fetch_item)
        self.fetch_worker.finished_ok.connect(self._on_fetch_success)
        self.fetch_worker.finished_error.connect(self._on_chain_error)
        self.fetch_worker.stats_update.connect(self._on_fetch_stats)
        self.fetch_worker.start()

    @pyqtSlot(str)
    def _on_fetch_log(self, msg: str):
        level = "INFO"
        if "✅" in msg: level = "SUCCESS"
        elif "❌" in msg: level = "ERROR"
        self.append_log(level, msg)

    @pyqtSlot(str)
    def _on_fetch_detail(self, msg: str):
        self.progress_detail.setText(msg)
        m = __import__("re").search(r"(\d+)/(\d+)", msg)
        if m:
            cur, total = int(m.group(1)), int(m.group(2))
            pct = int(cur / total * 40) + 30
            self.progress_bar.setValue(min(pct, 65))
            self.progress_bar.setFormat(f"抓取中... {cur}/{total}")

    @pyqtSlot(int, int, dict)
    def _on_fetch_item(self, current: int, total: int, result: dict):
        url = result.get("url", "")
        self.fetch_results[url] = result

    @pyqtSlot(dict)
    def _on_fetch_stats(self, stats: dict):
        cache = stats.get("cache", {})
        self.append_log("DEBUG",
            f"📡 抓取统计: 总{stats['total']} 成功{stats['success']} "
            f"失败{stats['failed']} 缓存命中{stats['cached']} | "
            f"引擎: scrapling={stats['scrapling']} req={stats['requests']} fc={stats['firecrawl']}"
        )

    @pyqtSlot(dict)
    def _on_fetch_success(self, results: dict):
        """抓取完成"""
        self.fetch_results.update(results)

        success = sum(1 for r in results.values() if r.success)
        failed = sum(1 for r in results.values() if not r.success)

        self.progress_bar.setValue(70)
        self.progress_bar.setFormat(f"抓取完成! ✅{success} ❌{failed}")

        self._populate_table(self.bookmarks)
        self._update_stats()
        self.append_log("SUCCESS", f"🎉 抓取完成! 成功:{success} 失败:{failed}")

        fetcher_stats = self.fetcher.get_stats()
        fc = fetcher_stats.get("cache", {})
        self.append_log("INFO", f"💾 抓取缓存: {fc.get('total', 0)}条")

        # ── 自动链式下一步: 摘要二阶段规则 → AI 分类 ──
        self._set_step_state(2, "done")
        self._apply_summary_rules()

    # ──────────────────────────────────────────────
    #  链式工作流: 摘要二阶段规则（T2, design §5 B3）
    # ──────────────────────────────────────────────

    def _apply_summary_rules(self):
        """
        抓取完成后，用页面摘要对仍未分类的书签再跑一次规则

        流程: 本地摘要提取(summarizer) → classify_with_summary
        命中(且置信度 ≥ 阈值) → classify_method=summary_rule，AI 跳过；
        未命中 → 交给 AI 兜底（AI prompt 将使用 page_summary）
        """
        try:
            from modules.summarizer import summarize_bookmarks

            summaries = summarize_bookmarks(self.fetch_results)
            if not summaries:
                self._chain_ai()
                return

            changed = 0
            for bm in self.bookmarks:
                if bm.user_deleted:
                    continue
                if bm.category_l1 and bm.category_l1 != "其他":
                    continue
                summary = summaries.get(bm.url)
                if not summary:
                    continue
                bm.page_summary = summary
                if self.classifier.classify_with_summary(bm):
                    changed += 1

            if changed:
                self._populate_table(self.bookmarks)
                self._update_dist_tree(self.bookmarks)
                self.append_log("SUCCESS", f"📝 摘要规则二阶段: {changed} 条已归类 (summary_rule)")
            else:
                self.append_log("INFO", "📝 摘要规则二阶段: 无命中，交给 AI")

        except Exception as e:
            self.append_log("WARN", f"⚠️ 摘要规则二阶段失败: {type(e).__name__}: {e}")

        self._chain_ai()

    # ──────────────────────────────────────────────
    #  链式工作流: AI 分类
    # ──────────────────────────────────────────────

    def _chain_ai(self):
        """自动化: AI 分类（AI 只兜底：summary_rule 已归类的跳过）"""
        if not self.bookmarks:
            self._chain_review()
            return

        to_classify = []
        for bm in self.bookmarks:
            if bm.user_deleted:
                continue
            if bm.status in ("local", "dead"):
                continue  # 本地/失效书签不消耗 AI
            if bm.classify_method == "summary_rule":
                continue  # 摘要规则已落地，AI 不再重复
            if bm.category_l1 and bm.category_l1 != "其他" and bm.confidence >= 0.8:
                continue
            to_classify.append(bm)

        if not to_classify:
            self.append_log("INFO", "✅ 所有书签已分类完成，无需 AI 处理")
            self._set_step_state(3, "done")
            self._chain_review()
            return

        api_key = self.secure_store.load("deepseek")
        if not api_key:
            self.append_log("WARN", "⚠️ 未配置 AI API Key，跳过 AI 分类")
            self._set_step_state(3, "done")
            self._chain_review()
            return

        # 成本预估 + 确认
        categories = self.config.get("categories", [])
        client_preview = DeepSeekClient(
            config=self._build_fetcher_config(),
            categories=categories,
            api_key=api_key,
        )
        estimate = client_preview.estimate_cost(len(to_classify))
        max_cost = self.config.get("ai.max_cost_yuan", 5.0)

        cost_msg = (
            f"将对 {len(to_classify)} 条书签进行 AI 分类。\n\n"
            f"预估费用: ¥{estimate['estimated_cost_yuan']:.4f}\n"
            f"费用上限: ¥{max_cost:.2f}\n\n"
            "是否继续？"
        )
        if not self._cn_question("AI 分类确认", cost_msg, default_yes=True):
            self.append_log("INFO", "用户取消 AI 分类")
            self._chain_review()
            return

        # 构建 AI 客户端
        self.ai_client = DeepSeekClient(
            config=self._build_fetcher_config(),
            categories=categories,
            proxy_adapter=ProxyAdapter(proxy_manager=self.proxy_manager, config=self._build_fetcher_config()),
            api_key=api_key,
        )

        bookmarks_info = []
        for bm in to_classify:
            fetch = self.fetch_results.get(bm.url)
            info = {
                "url": bm.url,
                "title": bm.title,
                "domain": bm.domain,
                "description": fetch.description if fetch else "",
                "keywords": fetch.keywords if fetch else [],
                # T3: AI 输入用页面摘要（本地摘要或抓取正文片段），省 token
                "summary": (bm.page_summary or (fetch.text[:200] if fetch else "")),
            }
            bookmarks_info.append(info)

        self.append_log("INFO", f"🤖 开始 AI 分类 {len(bookmarks_info)} 条...")
        self.progress_bar.setValue(70)
        self.progress_bar.setFormat("AI 分类中...")
        self._chain_step_idx = 3
        self._set_step_active(3)

        self.ai_worker = AIWorker(self.ai_client, bookmarks_info, self)
        self.ai_worker.progress.connect(self._on_ai_log)
        self.ai_worker.progress_detail.connect(self._on_ai_detail)
        self.ai_worker.item_done.connect(self._on_ai_item)
        self.ai_worker.finished_ok.connect(self._on_ai_success)
        self.ai_worker.finished_error.connect(self._on_chain_error)
        self.ai_worker.stats_update.connect(self._on_ai_stats)
        self.ai_worker.budget_warning.connect(self._on_budget_warning)
        self.ai_worker.start()

    @pyqtSlot(str)
    def _on_ai_log(self, msg: str):
        level = "INFO"
        if "✅" in msg: level = "SUCCESS"
        elif "❌" in msg: level = "ERROR"
        elif "⚠️" in msg: level = "WARN"
        self.append_log(level, msg)

    @pyqtSlot(str)
    def _on_ai_detail(self, msg: str):
        self.progress_detail.setText(msg)
        m = __import__("re").search(r"(\d+)/(\d+)", msg)
        if m:
            cur, total = int(m.group(1)), int(m.group(2))
            pct = int(cur / total * 80) + 10
            self.progress_bar.setValue(min(pct, 95))
            self.progress_bar.setFormat(f"AI: {cur}/{total}")

    @pyqtSlot(int, int, dict)
    def _on_ai_item(self, current: int, total: int, result_dict: dict):
        """单条 AI 分类完成，回写到书签"""
        url = result_dict.get("url", "")
        bm = next((b for b in self.bookmarks if b.url == url), None)
        if not bm:
            return

        if result_dict.get("success"):
            bm.category_l1 = result_dict.get("category_l1", "")
            bm.category_l2 = result_dict.get("category_l2", "")
            bm.confidence = result_dict.get("confidence", 0.5)
            bm.classify_method = "ai_deepseek"
            # T3: AI 摘要回写 page_summary
            ai_summary = result_dict.get("summary", "")
            if ai_summary:
                bm.page_summary = ai_summary

        # 存储 AI 结果
        if not hasattr(self, 'ai_results'):
            self.ai_results = {}
        from types import SimpleNamespace
        self.ai_results[url] = SimpleNamespace(**result_dict)

    @pyqtSlot(list)
    def _on_ai_success(self, results: list):
        """AI 分类完成"""
        success = sum(1 for r in results if r.success)
        failed = len(results) - success
        stats = self.ai_client.get_stats()

        self.progress_bar.setValue(85)
        self.progress_bar.setFormat(f"AI 完成! ✅{success} ❌{failed}")

        self.append_log("SUCCESS", f"🎉 AI 分类完成! 成功:{success} 失败:{failed}")
        self.append_log("INFO", f"💰 费用: ¥{stats['estimated_cost_yuan']:.4f} / ¥{self.ai_client.max_cost_yuan:.2f}")

        self._populate_table(self.bookmarks)
        self._update_dist_tree(self.bookmarks)
        self._update_stats()
        self._set_step_state(3, "done")
        self._refresh_status()

        # ── 自动链式下一步: 审核确认 ──
        self._chain_review()

    @pyqtSlot(str)
    def _on_ai_stats(self, stats: dict):
        cache = stats.get("cache", {})
        self.append_log("DEBUG",
            f"🤖 AI统计: 总{stats['total']} 成功{stats['success']} "
            f"失败{stats['failed']} 缓存{stats['cached']} "
            f"Tokens={stats['tokens_used']} 费用=¥{stats['estimated_cost_yuan']:.4f}"
        )

    @pyqtSlot(float, float)
    def _on_budget_warning(self, used: float, max_budget: float):
        self.append_log("WARN", f"⚠️ AI 预算即将耗尽: ¥{used:.4f} / ¥{max_budget:.2f}")

    # ──────────────────────────────────────────────
    #  链式工作流: 审核确认
    # ──────────────────────────────────────────────

    def _chain_review(self):
        """自动化: 打开审核对话框"""
        self.progress_bar.setValue(85)
        self.progress_bar.setFormat("审核中...")
        self._set_step_active(4)
        self.append_log("INFO", "📋 等待用户审核确认...")

        categories = self.config.get("categories", [])
        ai_dict = getattr(self, 'ai_results', {})

        dlg = ReviewDialog(
            bookmarks=self.bookmarks,
            categories=categories,
            fetch_results=self.fetch_results,
            ai_results=ai_dict,
            parent=self,
        )
        dlg.review_completed.connect(self._on_review_completed)
        dlg.exec()

    @pyqtSlot(list)
    def _on_review_completed(self, reviewed_bookmarks: list):
        """审核完成，自动进入下一阶段"""
        self.bookmarks = reviewed_bookmarks
        confirmed = sum(1 for b in self.bookmarks if b.user_confirmed)
        deleted = sum(1 for b in self.bookmarks if b.user_deleted)

        self.append_log("SUCCESS", f"✅ 审核完成: {confirmed} 条确认, {deleted} 条删除")
        self._populate_table(self.bookmarks)
        self._update_dist_tree(self.bookmarks)
        self._update_stats()
        self._refresh_status()

        active_count = len([b for b in self.bookmarks if not b.user_deleted])
        summary = (
            f"审核完成！\n\n"
            f"  ✅ 已确认: {confirmed} 条\n"
            f"  🗑️ 已删除: {deleted} 条\n"
            f"  📝 保留: {active_count} 条\n\n"
            f"是否立即生成分类后的书签 HTML 文件？"
        )
        if self._cn_question("生成书签文件", summary, default_yes=True):
            self._generate_html()
        else:
            self._set_step_state(4, "done")
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("审核完成")
            self.append_log("INFO", "用户选择稍后生成 HTML")
            self._finalize_workflow()

    # ──────────────────────────────────────────────
    #  链式工作流: 生成 HTML
    # ──────────────────────────────────────────────

    def _generate_html(self):
        """生成分类后的 HTML 书签文件"""
        from PyQt6.QtWidgets import QFileDialog
        from datetime import datetime

        self._set_step_active(5)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"bookmarks_classified_{ts}.html"
        export_dir = self.config.get("output.export_dir", "data/exports")
        default_path = str(Path(export_dir) / default_name)

        path, _ = QFileDialog.getSaveFileName(
            self, "保存分类书签", default_path, "HTML (*.html)"
        )
        if not path:
            self._set_step_state(5, "done")
            self._finalize_workflow()
            return

        # T5.3: 导出前询问包含选项（默认值来自配置）
        include_dead = bool(self.config.get("output.export_include_dead", False))
        include_local = bool(self.config.get("output.export_include_local", True))
        ok, include_dead, include_local = self._ask_export_options(
            include_dead, include_local
        )
        if not ok:
            self._set_step_state(5, "done")
            self._finalize_workflow()
            return

        self.append_log("INFO", "🔨 正在生成分类书签 HTML...")
        self.progress_bar.setValue(90)
        self.progress_bar.setFormat("生成 HTML...")

        try:
            result = build_and_save(
                bookmarks=self.bookmarks,
                output_path=path,
                root_name="书签栏",
                sort_by="title",
                add_favicon=True,
                preserve_dates=True,
                include_dead=include_dead,
                include_local=include_local,
            )

            self.progress_bar.setValue(95)

            if result["success"]:
                size_kb = result["html_size"] / 1024
                s = result["stats"]
                extra = ""
                if s.get("excluded_dead"):
                    extra += f" (排除失效 {s['excluded_dead']} 条)"
                if s.get("excluded_local"):
                    extra += f" (排除本地 {s['excluded_local']} 条)"
                self.append_log("SUCCESS",
                    f"✅ HTML 生成成功! {s['kept']}条书签, "
                    f"{s['folders_created']}个文件夹, {size_kb:.1f}KB{extra}"
                )
                self.progress_bar.setValue(100)
                self.progress_bar.setFormat("HTML 生成完成!")

                # 打开导入向导
                self._open_import_wizard(path, s["kept"], s["deleted"])

            else:
                errors = result["validation"]["errors"]
                self.append_log("WARN", f"⚠️ HTML 验证有问题:")
                for e in errors:
                    self.append_log("WARN", f"   • {e}")
                self.progress_bar.setFormat("HTML 有警告")
                self._open_import_wizard(path, result["stats"]["kept"], result["stats"]["deleted"])

        except Exception as e:
            self.append_log("ERROR", f"❌ HTML 生成失败: {e}")
            self.progress_bar.setFormat("生成失败")
            self._cn_error("生成失败", f"HTML 生成出错:\n\n{type(e).__name__}: {e}")
            self._set_step_state(5, "done")
            self._finalize_workflow()

    def _ask_export_options(self, include_dead: bool, include_local: bool):
        """T5.3: 导出包含选项复选框（失效默认排除、本地默认包含）
        返回: (ok, include_dead, include_local)"""
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("导出选项")
        dlg.setMinimumWidth(380)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        tip = QLabel("选择导出 HTML 时要包含哪些书签：")
        tip.setStyleSheet("color: #6B7280; font-size: 12px;")
        layout.addWidget(tip)

        dead_cb = QCheckBox("包含失效链接")
        dead_cb.setChecked(include_dead)
        dead_cb.setToolTip("勾选后，状态为「失效」的书签也会写入导出的 HTML")
        layout.addWidget(dead_cb)

        local_cb = QCheckBox("包含本地/内网书签")
        local_cb.setChecked(include_local)
        local_cb.setToolTip("file://、localhost、内网地址等本地书签（默认包含）")
        layout.addWidget(local_cb)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        ok_btn = QPushButton("✅ 生成")
        ok_btn.setObjectName("primaryBtn")
        ok_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        return (accepted, dead_cb.isChecked(), local_cb.isChecked())

    def _open_import_wizard(self, html_path: str, count: int, deleted: int):
        """打开导入向导"""
        dlg = ImportWizard(
            html_path=html_path,
            bookmarks_count=count,
            deleted_count=deleted,
            parent=self,
        )
        dlg.import_completed.connect(self._on_import_done)
        dlg.exec()

    def _finalize_workflow(self):
        """工作流结束 - 恢复按钮状态，显示统计"""
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 一键处理")
        self._set_import_btn_enabled(True)

        total = len(self.bookmarks)
        active = sum(1 for b in self.bookmarks if not b.user_deleted)
        confirmed = sum(1 for b in self.bookmarks if b.user_confirmed)
        classified = sum(1 for b in self.bookmarks if b.category_l1 and b.category_l1 != "其他")

        self.append_log("INFO", "─" * 50)
        self.append_log("INFO", f"📊 最终统计:")
        self.append_log("INFO", f"   原始书签: {total} 条")
        self.append_log("INFO", f"   保留: {active} 条 | 删除: {total - active} 条")
        self.append_log("INFO", f"   已分类: {classified} 条 | 确认: {confirmed} 条")
        self.append_log("INFO", f"   分类覆盖率: {classified/total*100:.0f}%")
        self.append_log("INFO", "─" * 50)
        self._update_stats()
        self._refresh_status()

    @pyqtSlot(str)
    def _on_import_done(self, html_path: str):
        """导入向导完成"""
        self.append_log("SUCCESS", f"🎉 全部流程完成! 文件: {html_path}")
        self._set_step_state(5, "done")
        self._finalize_workflow()

    def _export_review_excel(self):
        """导出审核 Excel"""
        from PyQt6.QtWidgets import QFileDialog
        from modules.excel_writer import generate_review_excel

        path, _ = QFileDialog.getSaveFileName(
            self, "保存审核表", "书签审核.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return

        categories = self.config.get("categories", [])
        ai_dict = {}
        if hasattr(self, 'ai_results'):
            for url, r in self.ai_results.items():
                if isinstance(r, AIResult):
                    ai_dict[url] = r

        stats = self.ai_client.get_stats() if hasattr(self, 'ai_client') else {}

        output = generate_review_excel(
            bookmarks=self.bookmarks,
            fetch_results=self.fetch_results,
            ai_results=ai_dict,
            categories=categories,
            output_path=path,
            stats=stats,
        )
        self._cn_ok("导出成功", f"审核表已保存:\n{output}")

    # ──────────────────────────────────────────────
    #  统计仪表盘
    # ──────────────────────────────────────────────

    def _update_stats(self):
        """更新统计仪表盘数据"""
        if not hasattr(self, 'bookmarks') or not self.bookmarks:
            return
        total = len(self.bookmarks)
        classified = sum(1 for b in self.bookmarks
                         if b.category_l1 and b.category_l1 != "其他" and not b.user_deleted)
        fetched = sum(1 for b in self.bookmarks
                      if b.url in self.fetch_results and not b.user_deleted)
        ai_count = sum(1 for b in self.bookmarks
                       if hasattr(b, 'classify_method') and b.classify_method == 'ai_deepseek')
        deleted = sum(1 for b in self.bookmarks if b.user_deleted)
        self.stats_dashboard.update_stats(total, classified, fetched, ai_count, deleted)

    # ──────────────────────────────────────────────
    #  表格 & 分布
    # ──────────────────────────────────────────────

    def _populate_table(self, bookmarks: list):
        filter_text = self.filter_combo.currentText() if hasattr(self, 'filter_combo') else "全部"
        filtered = self._apply_filter(bookmarks, filter_text)
        max_show = min(200, len(filtered))
        self.table.setRowCount(max_show)

        for i, bm in enumerate(filtered[:max_show]):
            self.table.setItem(i, 0, QTableWidgetItem(str(bm.id)))
            self.table.setItem(i, 1, QTableWidgetItem(bm.title))
            self.table.setItem(i, 2, QTableWidgetItem(bm.domain))
            self.table.setItem(i, 3, QTableWidgetItem(bm.folder))
            self.table.setItem(i, 4, QTableWidgetItem(bm.category_l1))
            self.table.setItem(i, 5, QTableWidgetItem(bm.category_l2))
            self.table.setItem(i, 6, QTableWidgetItem(bm.classify_method))

            # T5.1: 状态列（探活三态 + 抓取标记）
            self.table.setItem(i, 7, QTableWidgetItem(
                _status_text(bm, bm.url in self.fetch_results)
            ))

        # 删除标记
        del_btn = QTableWidgetItem("🗑️" if bm.user_deleted else "")
        self.table.setItem(i, 8, del_btn)

        # 颜色标记
        self._color_row(i, bm)

        # T5.2: 同步删除按钮可用态
        if hasattr(self, "delete_dead_btn"):
            self.delete_dead_btn.setEnabled(
                any(b.status == "dead" and not b.user_deleted for b in bookmarks)
            )

    def _color_row(self, row: int, bm: Bookmark):
        color = None
        if bm.user_deleted:
            color = QColor(255, 200, 200)  # 浅红
        elif bm.category_l1 == "其他" or not bm.category_l1:
            color = QColor(240, 240, 240)  # 灰
        elif bm.classify_method and "rule" in bm.classify_method:
            color = QColor(220, 255, 220)  # 浅绿
        elif bm.url in self.fetch_results:
            color = QColor(220, 235, 255)  # 浅蓝

        if color:
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item:
                    item.setBackground(color)

    def _apply_filter(self, bookmarks: list, filter_text: str) -> list:
        if filter_text == "全部":
            return bookmarks
        elif filter_text == "已分类":
            return [bm for bm in bookmarks if bm.category_l1 and bm.category_l1 != "其他"]
        elif filter_text == "待AI/人工":
            return [bm for bm in bookmarks if not bm.category_l1 or bm.category_l1 == "其他"]
        elif filter_text == "已抓取":
            return [bm for bm in bookmarks if bm.url in self.fetch_results]
        elif filter_text == "失效链接":
            return [bm for bm in bookmarks if bm.status == "dead"]
        elif filter_text == "已删除":
            return [bm for bm in bookmarks if bm.user_deleted]
        return bookmarks

    def _on_filter_changed(self, text: str):
        if hasattr(self, 'bookmarks'):
            self._populate_table(self.bookmarks)

    def _delete_dead_bookmarks(self):
        """T5.2: 一键删除失效链接（二次确认）"""
        dead = [bm for bm in self.bookmarks
                if bm.status == "dead" and not bm.user_deleted]
        if not dead:
            self._cn_ok("删除失效", "没有可删除的失效链接。")
            return

        ok = self._cn_question(
            "删除失效链接",
            f"确定要将 {len(dead)} 条失效链接标记为删除吗？\n\n"
            "被标记的书签不会出现在导出的 HTML 中（可在「已删除」筛选下恢复，"
            "或通过审核对话框撤销）。",
            default_yes=False,
        )
        if not ok:
            return

        for bm in dead:
            bm.user_deleted = True
        self._populate_table(self.bookmarks)
        self._update_dist_tree(self.bookmarks)
        self._update_stats()
        self.append_log("WARN", f"🗑️ 已将 {len(dead)} 条失效链接标记为删除")
        self._refresh_status()

    def _update_dist_tree(self, bookmarks: list):
        dist = self.classifier.get_distribution(bookmarks)
        self.dist_tree.clear()
        for l1, l2s in sorted(dist.items(), key=lambda x: sum(x[1].values()), reverse=True):
            total = sum(l2s.values())
            parent = QTreeWidgetItem([f"📁 {l1} ({total})"])
            self.dist_tree.addTopLevelItem(parent)
            for l2, count in sorted(l2s.items(), key=lambda x: x[1], reverse=True):
                parent.addChild(QTreeWidgetItem([f"  ├─ {l2}: {count}"]))
            parent.setExpanded(True)

    # ──────────────────────────────────────────────
    #  设置 & 工具
    # ──────────────────────────────────────────────

    def _open_settings(self):
        dlg = SettingsDialog(self.config, self.secure_store, self.proxy_manager, self)
        dlg.theme_changed.connect(self._on_theme_changed)
        if dlg.exec():
            self.append_log("INFO", "设置已更新")
            # 刷新 fetcher 配置
            self.fetcher.proxy.refresh()
            fc_key = self.secure_store.load("firecrawl_api_key")
            if fc_key:
                self.fetcher.set_firecrawl_key(fc_key)
            self._refresh_status()

    def _on_theme_changed(self, theme: str):
        """主题切换 - 重新加载 QSS"""
        app = QApplication.instance()
        if not app:
            return
        qss_filename = "styles_dark.qss" if theme == "dark" else "styles.qss"
        qss_path = Path(__file__).resolve().parent.parent / "ui" / "resources" / qss_filename
        if qss_path.exists():
            with open(qss_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
            self.append_log("INFO", f"主题已切换为: {'🌙深色' if theme == 'dark' else '☀️浅色'}")

    def _test_proxy(self):
        """测试代理连通性"""
        url = "https://www.google.com"
        proxy_url = ""
        if self.proxy_manager.is_enabled():
            proxies = self.proxy_manager.get_proxies()
            proxy_url = proxies.get("https", "") if proxies else ""

        from modules.fetcher import test_connectivity
        result = test_connectivity(url, proxy_url)

        if result["success"]:
            self._cn_ok("代理测试",
                f"✅ 连接成功\n\nURL: {url}\n耗时: {result['elapsed_ms']}ms\n代理: {result.get('proxy', 'direct')}")
            self.append_log("SUCCESS", f"代理测试通过: {result['elapsed_ms']}ms")
        else:
            self._cn_error("代理测试",
                f"❌ 连接失败\n\n{result.get('error', 'unknown')}")
            self.append_log("ERROR", f"代理测试失败: {result.get('error', '')}")


# 向后兼容别名
BookmarkManagerWindow = MainWindow

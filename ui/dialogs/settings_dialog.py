"""
settings_dialog.py - 系统设置对话框
Tab 分页: 代理 | AI/LLM | 抓取 | 分类 | 高级
"""

import logging
from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QFormLayout, QTextEdit, QMessageBox, QSizePolicy,
    QScrollArea, QWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from modules.config_manager import ConfigManager
from modules.secure_store import SecureStore
from modules.proxy import ProxyManager

logger = logging.getLogger("ui.settings")


class SettingsDialog(QDialog):
    """设置对话框 - Tab 分页"""

    # 主题变更信号（仅在主题实际变化时触发）
    theme_changed = pyqtSignal(str)

    def __init__(self, config: ConfigManager, secure_store: SecureStore, proxy: ProxyManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.secure_store = secure_store
        self.proxy = proxy

        self.setWindowTitle("⚙ 系统设置")
        self.setMinimumSize(600, 500)
        self.resize(650, 550)

        # 记住当前主题，保存时检测变化
        self._old_theme = config.get("ui.theme", "light")

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Tab 容器
        self.tabs = QTabWidget()

        # 创建各 Tab 页（包裹在可滚动区域中）
        self.tab_proxy = ProxySettingsTab(self.config, self.proxy)
        self.tab_ai = AISettingsTab(self.config, self.secure_store)
        self.tab_fetch = FetchSettingsTab(self.config)
        self.tab_classify = ClassificationSettingsTab(self.config)
        self.tab_advanced = AdvancedSettingsTab(self.config)

        self.tabs.addTab(self._make_scrollable(self.tab_proxy), "🌐 代理")
        self.tabs.addTab(self._make_scrollable(self.tab_ai), "🤖 AI/LLM")
        self.tabs.addTab(self._make_scrollable(self.tab_fetch), "🕷️ 抓取")
        self.tabs.addTab(self._make_scrollable(self.tab_classify), "📂 分类")
        self.tabs.addTab(self._make_scrollable(self.tab_advanced), "🔧 高级")

        layout.addWidget(self.tabs, stretch=1)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_reset = QPushButton("还原默认")
        self.btn_reset.setObjectName("secondaryBtn")
        self.btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(self.btn_reset)

        btn_row.addSpacing(8)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("保存")
        self.btn_save.setObjectName("primaryBtn")
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self.btn_save)

        layout.addLayout(btn_row)

    @staticmethod
    def _make_scrollable(widget: QWidget) -> QScrollArea:
        """将 widget 包裹在 QScrollArea 中，使其内容可滚动"""
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)  # 无边框，保持 TabPane 样式
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        return scroll

    def _on_save(self):
        """保存所有 Tab 的设置"""
        errors = []

        for tab in [self.tab_proxy, self.tab_ai, self.tab_fetch, self.tab_classify, self.tab_advanced]:
            err = tab.validate()
            if err:
                errors.extend(err)

        if errors:
            QMessageBox.warning(self, "保存失败", "\n".join(errors))
            return

        # 提交保存
        for tab in [self.tab_proxy, self.tab_ai, self.tab_fetch, self.tab_classify, self.tab_advanced]:
            tab.save()

        self.config.save()
        logger.info("设置已保存")

        # 检测主题变更
        new_theme = self.config.get("ui.theme", "light")
        if new_theme != self._old_theme:
            self.theme_changed.emit(new_theme)

        self.accept()

    def _on_reset(self):
        """重置确认"""
        reply = QMessageBox.question(
            self, "确认重置",
            "确定要恢复所有设置为默认值吗？\n（已配置的 API Key 不会删除）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config.reset_to_defaults()
            # 重新加载各 Tab
            self.tab_proxy.reload()
            self.tab_ai.reload()
            self.tab_fetch.reload()
            self.tab_classify.reload()
            self.tab_advanced.reload()

            # 检测主题是否因重置而改变
            new_theme = self.config.get("ui.theme", "light")
            if new_theme != self._old_theme:
                self.theme_changed.emit(new_theme)
                self._old_theme = new_theme

            QMessageBox.information(self, "完成", "已恢复默认设置")


# ──────────────────────────────────────────────
#  Tab: 代理设置
# ──────────────────────────────────────────────

class ProxySettingsTab(QWidget):
    """🌐 代理设置 Tab"""

    def __init__(self, config: ConfigManager, proxy: ProxyManager):
        super().__init__()
        self.config = config
        self.proxy = proxy
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── 总开关 ──
        switch_group = QGroupBox("代理总开关")
        switch_layout = QHBoxLayout(switch_group)

        self.enable_switch = QPushButton()
        self.enable_switch.setObjectName("bigToggle")
        self.enable_switch.setCheckable(True)
        self.enable_switch.setMinimumSize(80, 36)
        current_enabled = self.config.get("proxy.enabled", False)
        self.enable_switch.setChecked(current_enabled)
        self.enable_switch.toggled.connect(self._on_toggle)
        self._update_switch_text(current_enabled)

        switch_layout.addWidget(self.enable_switch)
        switch_layout.addWidget(QLabel("点击切换代理开关"))
        switch_layout.addStretch()
        layout.addWidget(switch_group)

        # ── 自动检测 ──
        auto_group = QGroupBox("自动检测")
        auto_layout = QVBoxLayout(auto_group)

        self.auto_detect_cb = QCheckBox("自动检测系统/VPN 代理")
        self.auto_detect_cb.setChecked(self.config.get("proxy.auto_detect_system", True))
        auto_layout.addWidget(self.auto_detect_cb)

        self.detect_result_label = QLabel()
        self.detect_result_label.setObjectName("detectResult")
        self._refresh_detect_result()
        auto_layout.addWidget(self.detect_result_label)

        layout.addWidget(auto_group)

        # ── 自定义代理 ──
        custom_group = QGroupBox("自定义代理")
        custom_form = QFormLayout(custom_group)

        self.custom_enabled_cb = QCheckBox("启用自定义代理（覆盖系统代理）")
        self.custom_enabled_cb.setChecked(self.config.get("proxy.custom.enabled", False))
        custom_form.addRow(self.custom_enabled_cb)

        self.proxy_type_combo = QComboBox()
        self.proxy_type_combo.addItems(["http", "socks5"])
        self.proxy_type_combo.setCurrentText(self.config.get("proxy.custom.type", "http"))
        custom_form.addRow("类型:", self.proxy_type_combo)

        self.proxy_host_input = QLineEdit()
        self.proxy_host_input.setText(self.config.get("proxy.custom.host", "127.0.0.1"))
        custom_form.addRow("地址:", self.proxy_host_input)

        self.proxy_port_input = QSpinBox()
        self.proxy_port_input.setRange(1, 65535)
        self.proxy_port_input.setValue(self.config.get("proxy.custom.port", 7890))
        custom_form.addRow("端口:", self.proxy_port_input)

        self.proxy_user_input = QLineEdit()
        self.proxy_user_input.setText(self.config.get("proxy.custom.username", ""))
        custom_form.addRow("用户名:", self.proxy_user_input)

        self.proxy_pass_input = QLineEdit()
        self.proxy_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.proxy_pass_input.setText(self.config.get("proxy.custom.password", ""))
        custom_form.addRow("密码:", self.proxy_pass_input)

        layout.addWidget(custom_group)

        # ── 代理用途 ──
        use_group = QGroupBox("代理用途")
        use_layout = QVBoxLayout(use_group)

        self.use_webfetch_cb = QCheckBox("网页抓取（分类用）")
        self.use_webfetch_cb.setChecked(self.config.get("proxy.use_for.web_fetch", True))
        use_layout.addWidget(self.use_webfetch_cb)

        self.use_ai_cb = QCheckBox("AI API 请求（DeepSeek 国内通常不需代理）")
        self.use_ai_cb.setChecked(self.config.get("proxy.use_for.ai_api", False))
        use_layout.addWidget(self.use_ai_cb)

        self.use_firecrawl_cb = QCheckBox("Firecrawl API")
        self.use_firecrawl_cb.setChecked(self.config.get("proxy.use_for.firecrawl", True))
        use_layout.addWidget(self.use_firecrawl_cb)

        layout.addWidget(use_group)

        # ── 绕过列表 ──
        bypass_group = QGroupBox("绕过代理的域名")
        bypass_layout = QVBoxLayout(bypass_group)

        self.bypass_text = QTextEdit()
        self.bypass_text.setMaximumHeight(80)
        bypass_domains = self.config.get("proxy.bypass_domains", [])
        self.bypass_text.setPlainText("\n".join(bypass_domains))
        bypass_layout.addWidget(self.bypass_text)

        layout.addWidget(bypass_group)

        # ── 测试按钮 ──
        test_row = QHBoxLayout()
        self.test_btn = QPushButton("🔍 测试连接")
        self.test_btn.setObjectName("primaryBtn")
        self.test_btn.clicked.connect(self._on_test)
        test_row.addWidget(self.test_btn)

        self.test_result_label = QLabel("点击测试按钮检查代理连通性")
        self.test_result_label.setObjectName("testResult")
        test_row.addWidget(self.test_result_label)
        test_row.addStretch()
        layout.addLayout(test_row)

        layout.addStretch()

    def _on_toggle(self, checked: bool):
        self._update_switch_text(checked)

    def _update_switch_text(self, checked: bool):
        if checked:
            self.enable_switch.setText("● 已启用")
            self.enable_switch.setProperty("class", "toggleOn")
        else:
            self.enable_switch.setText("○ 已禁用")
            self.enable_switch.setProperty("class", "toggleOff")
        # 刷新样式
        self.enable_switch.style().unpolish(self.enable_switch)
        self.enable_switch.style().polish(self.enable_switch)

    def _refresh_detect_result(self):
        info = self.proxy.get_status_info()
        if info.get("vpn_detected"):
            self.detect_result_label.setText("🟢 检测到 VPN 连接")
        elif info.get("mode") == "系统代理(自动)":
            self.detect_result_label.setText(f"🟢 检测到系统代理: {info.get('address', '')}")
        else:
            self.detect_result_label.setText("⚪ 未检测到系统代理")

    def _on_test(self):
        """测试代理连通性"""
        self.test_result_label.setText("⏳ 测试中...")
        self.test_btn.setEnabled(False)

        # 临时应用当前设置
        self.save()

        result = self.proxy.test_connection()

        self.test_btn.setEnabled(True)
        if result["success"]:
            self.test_result_label.setText(
                f"✅ 代理可用 | IP: {result['ip']} | 延迟: {result['latency_ms']}ms"
            )
            self.test_result_label.setStyleSheet("color: #10B981;")
        else:
            self.test_result_label.setText(f"❌ 连接失败: {result['error']}")
            self.test_result_label.setStyleSheet("color: #EF4444;")

    def validate(self) -> list[str]:
        errors = []
        if self.custom_enabled_cb.isChecked():
            if not self.proxy_host_input.text().strip():
                errors.append("自定义代理已启用，请填写地址")
            if self.proxy_port_input.value() <= 0:
                errors.append("自定义代理端口无效")
        return errors

    def save(self):
        self.config.set("proxy.enabled", self.enable_switch.isChecked())
        self.config.set("proxy.auto_detect_system", self.auto_detect_cb.isChecked())
        self.config.set("proxy.custom.enabled", self.custom_enabled_cb.isChecked())
        self.config.set("proxy.custom.type", self.proxy_type_combo.currentText())
        self.config.set("proxy.custom.host", self.proxy_host_input.text().strip())
        self.config.set("proxy.custom.port", self.proxy_port_input.value())
        self.config.set("proxy.custom.username", self.proxy_user_input.text().strip())
        self.config.set("proxy.custom.password", self.proxy_pass_input.text())
        self.config.set("proxy.use_for.web_fetch", self.use_webfetch_cb.isChecked())
        self.config.set("proxy.use_for.ai_api", self.use_ai_cb.isChecked())
        self.config.set("proxy.use_for.firecrawl", self.use_firecrawl_cb.isChecked())

        bypass = [line.strip() for line in self.bypass_text.toPlainText().splitlines() if line.strip()]
        self.config.set("proxy.bypass_domains", bypass)

        # 重新加载代理模块
        self.proxy.load_config()

    def reload(self):
        """重新加载配置到 UI"""
        self.enable_switch.setChecked(self.config.get("proxy.enabled", False))
        self._update_switch_text(self.config.get("proxy.enabled", False))
        self.auto_detect_cb.setChecked(self.config.get("proxy.auto_detect_system", True))
        self.custom_enabled_cb.setChecked(self.config.get("proxy.custom.enabled", False))
        self.proxy_type_combo.setCurrentText(self.config.get("proxy.custom.type", "http"))
        self.proxy_host_input.setText(self.config.get("proxy.custom.host", ""))
        self.proxy_port_input.setValue(self.config.get("proxy.custom.port", 7890))
        self.proxy_user_input.setText(self.config.get("proxy.custom.username", ""))
        self.proxy_pass_input.setText(self.config.get("proxy.custom.password", ""))
        self.use_webfetch_cb.setChecked(self.config.get("proxy.use_for.web_fetch", True))
        self.use_ai_cb.setChecked(self.config.get("proxy.use_for.ai_api", False))
        self.use_firecrawl_cb.setChecked(self.config.get("proxy.use_for.firecrawl", True))


# ──────────────────────────────────────────────
#  Tab: AI/LLM 设置
# ──────────────────────────────────────────────

class AISettingsTab(QWidget):
    """🤖 AI/LLM 设置 Tab"""

    def __init__(self, config: ConfigManager, secure_store: SecureStore):
        super().__init__()
        self.config = config
        self.secure_store = secure_store
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 服务商
        provider_group = QGroupBox("服务商")
        form = QFormLayout(provider_group)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["DeepSeek", "OpenAI (兼容)", "自定义 OpenAI 兼容"])
        self.provider_combo.setCurrentText("DeepSeek")
        form.addRow("服务商:", self.provider_combo)

        layout.addWidget(provider_group)

        # API Key
        key_group = QGroupBox("API Key（加密存储）")
        key_form = QFormLayout(key_group)

        key_row = QHBoxLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        existing_key = self.secure_store.load("deepseek") or ""
        if existing_key:
            self.api_key_input.setPlaceholderText("已配置 (输入新值将覆盖)")
        key_row.addWidget(self.api_key_input)

        self.show_key_btn = QPushButton("👁")
        self.show_key_btn.setMaximumWidth(36)
        self.show_key_btn.setCheckable(True)
        self.show_key_btn.toggled.connect(self._on_show_key)
        key_row.addWidget(self.show_key_btn)

        self.test_key_btn = QPushButton("🔑 测试")
        self.test_key_btn.clicked.connect(self._on_test_key)
        key_row.addWidget(self.test_key_btn)

        key_widget = QWidget()
        key_widget.setLayout(key_row)
        key_form.addRow("API Key:", key_widget)

        self.key_status_label = QLabel()
        self._refresh_key_status()
        key_form.addRow("", self.key_status_label)

        layout.addWidget(key_group)

        # 模型配置
        model_group = QGroupBox("模型配置")
        model_form = QFormLayout(model_group)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(["deepseek-chat", "deepseek-reasoner"])
        self.model_combo.setCurrentText(self.config.get("ai.model", "deepseek-chat"))
        model_form.addRow("模型:", self.model_combo)

        self.base_url_input = QLineEdit()
        self.base_url_input.setText(self.config.get("ai.base_url", "https://api.deepseek.com/v1"))
        model_form.addRow("Base URL:", self.base_url_input)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setValue(self.config.get("ai.timeout", 30))
        self.timeout_spin.setSuffix(" 秒")
        model_form.addRow("超时:", self.timeout_spin)

        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 10)
        self.retry_spin.setValue(self.config.get("ai.max_retries", 3))
        model_form.addRow("最大重试:", self.retry_spin)

        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 20)
        self.concurrency_spin.setValue(self.config.get("ai.concurrency", 3))
        model_form.addRow("并发数:", self.concurrency_spin)

        self.max_cost_spin = QDoubleSpinBox()
        self.max_cost_spin.setRange(0.1, 100)
        self.max_cost_spin.setDecimals(1)
        self.max_cost_spin.setValue(self.config.get("ai.max_cost_yuan", 5.0))
        self.max_cost_spin.setSuffix(" 元")
        model_form.addRow("费用上限:", self.max_cost_spin)

        layout.addWidget(model_group)

        # 使用统计
        stats_group = QGroupBox("使用统计")
        stats_layout = QVBoxLayout(stats_group)
        self.stats_label = QLabel(
            "本次运行: ¥0.00\n"
            "本月累计: ¥0.00\n"
            "总累计: ¥0.00\n\n"
            "（统计功能将在 Phase 5 实现）"
        )
        stats_layout.addWidget(self.stats_label)
        layout.addWidget(stats_group)

        layout.addStretch()

    def _on_show_key(self, checked: bool):
        if checked:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_key_btn.setText("🔒")
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_key_btn.setText("👁")

    def _on_test_key(self):
        """测试 API Key 是否有效"""
        key = self.api_key_input.text().strip()
        if not key:
            key = self.secure_store.load("deepseek")
        if not key:
            QMessageBox.warning(self, "提示", "请先输入 API Key")
            return

        from modules.ai_client import test_api_key
        base_url = self.base_url_input.text().strip() or "https://api.deepseek.com/v1"
        model = self.model_combo.currentText() or "deepseek-chat"

        self.test_key_btn.setEnabled(False)
        self.test_key_btn.setText("测试中...")

        result = test_api_key(key, base_url=base_url, model=model)

        self.test_key_btn.setEnabled(True)
        self.test_key_btn.setText("🔑 测试")

        if result["success"]:
            QMessageBox.information(
                self, "测试成功",
                f"✅ API Key 有效!\n\n"
                f"模型: {result.get('model', model)}\n"
                f"响应: {result.get('test_response', '')[:50]}\n"
                f"延迟: {result.get('elapsed_ms', 0)}ms"
            )
            self.key_status_label.setText("🟢 已验证: Key 有效")
            self.key_status_label.setStyleSheet("color: #10B981;")
        else:
            QMessageBox.warning(
                self, "测试失败",
                f"❌ API Key 无效或网络不通\n\n{result.get('error', 'unknown')}"
            )
            self.key_status_label.setText("🔴 验证失败")
            self.key_status_label.setStyleSheet("color: #EF4444;")

    def _refresh_key_status(self):
        if self.secure_store.exists("deepseek"):
            self.key_status_label.setText("🟢 已配置并加密存储")
            self.key_status_label.setStyleSheet("color: #10B981;")
        else:
            self.key_status_label.setText("🔴 未配置")
            self.key_status_label.setStyleSheet("color: #EF4444;")

    def validate(self) -> list[str]:
        return []  # API Key 可选（规则分类不依赖 AI）

    def save(self):
        # 保存 API Key（如果有新输入）
        new_key = self.api_key_input.text().strip()
        if new_key:
            self.secure_store.save("deepseek", new_key)

        self.config.set("ai.provider", self.provider_combo.currentText().lower().replace(" ", "_"))
        self.config.set("ai.model", self.model_combo.currentText())
        self.config.set("ai.base_url", self.base_url_input.text().strip())
        self.config.set("ai.timeout", self.timeout_spin.value())
        self.config.set("ai.max_retries", self.retry_spin.value())
        self.config.set("ai.concurrency", self.concurrency_spin.value())
        self.config.set("ai.max_cost_yuan", self.max_cost_spin.value())

    def reload(self):
        self.api_key_input.clear()
        self.api_key_input.setPlaceholderText("已配置 (输入新值将覆盖)")
        self.model_combo.setCurrentText(self.config.get("ai.model", "deepseek-chat"))
        self.base_url_input.setText(self.config.get("ai.base_url", ""))
        self.timeout_spin.setValue(self.config.get("ai.timeout", 30))
        self.retry_spin.setValue(self.config.get("ai.max_retries", 3))
        self.concurrency_spin.setValue(self.config.get("ai.concurrency", 3))
        self.max_cost_spin.setValue(self.config.get("ai.max_cost_yuan", 5.0))
        self._refresh_key_status()


# ──────────────────────────────────────────────
#  Tab: 抓取设置
# ──────────────────────────────────────────────

class FetchSettingsTab(QWidget):
    """🕷️ 网页抓取设置 Tab"""

    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 抓取引擎
        engine_group = QGroupBox("抓取引擎")
        engine_form = QFormLayout(engine_group)

        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["scrapling", "playwright", "requests"])
        self.engine_combo.setCurrentText(self.config.get("fetch.engine", "scrapling"))
        engine_form.addRow("引擎:", self.engine_combo)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 60)
        self.timeout_spin.setValue(self.config.get("fetch.timeout", 10))
        self.timeout_spin.setSuffix(" 秒")
        engine_form.addRow("超时:", self.timeout_spin)

        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 5)
        self.retry_spin.setValue(self.config.get("fetch.max_retries", 2))
        engine_form.addRow("最大重试:", self.retry_spin)

        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 20)
        self.concurrency_spin.setValue(self.config.get("fetch.concurrency", 5))
        engine_form.addRow("并发数:", self.concurrency_spin)

        layout.addWidget(engine_group)

        # 兜底策略
        fallback_group = QGroupBox("兜底策略")
        fallback_layout = QVBoxLayout(fallback_group)

        self.fallback_cb = QCheckBox("Scrapling 失败时自动使用 Firecrawl 兜底")
        self.fallback_cb.setChecked(self.config.get("fetch.fallback_to_firecrawl", True))
        fallback_layout.addWidget(self.fallback_cb)

        layout.addWidget(fallback_group)

        # User-Agent
        ua_group = QGroupBox("请求头")
        ua_layout = QVBoxLayout(ua_group)

        self.ua_input = QLineEdit()
        self.ua_input.setText(self.config.get("fetch.user_agent", ""))
        self.ua_input.setMinimumWidth(400)
        ua_layout.addWidget(QLabel("User-Agent:"))
        ua_layout.addWidget(self.ua_input)

        layout.addWidget(ua_group)

        layout.addStretch()

    def validate(self) -> list[str]:
        return []

    def save(self):
        self.config.set("fetch.engine", self.engine_combo.currentText())
        self.config.set("fetch.timeout", self.timeout_spin.value())
        self.config.set("fetch.max_retries", self.retry_spin.value())
        self.config.set("fetch.concurrency", self.concurrency_spin.value())
        self.config.set("fetch.fallback_to_firecrawl", self.fallback_cb.isChecked())
        self.config.set("fetch.user_agent", self.ua_input.text().strip())

    def reload(self):
        self.engine_combo.setCurrentText(self.config.get("fetch.engine", "scrapling"))
        self.timeout_spin.setValue(self.config.get("fetch.timeout", 10))
        self.retry_spin.setValue(self.config.get("fetch.max_retries", 2))
        self.concurrency_spin.setValue(self.config.get("fetch.concurrency", 5))
        self.fallback_cb.setChecked(self.config.get("fetch.fallback_to_firecrawl", True))
        self.ua_input.setText(self.config.get("fetch.user_agent", ""))


# ──────────────────────────────────────────────
#  Tab: 分类设置
# ──────────────────────────────────────────────

class ClassificationSettingsTab(QWidget):
    """📂 分类设置 Tab"""

    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 规则分类
        rule_group = QGroupBox("规则分类")
        rule_form = QFormLayout(rule_group)

        self.rule_enabled_cb = QCheckBox("启用规则匹配")
        self.rule_enabled_cb.setChecked(self.config.get("classification.rule_enabled", True))
        rule_form.addRow("", self.rule_enabled_cb)

        self.rule_threshold = QDoubleSpinBox()
        self.rule_threshold.setRange(0.1, 1.0)
        self.rule_threshold.setDecimals(1)
        self.rule_threshold.setSingleStep(0.1)
        self.rule_threshold.setValue(self.config.get("classification.rule_confidence_threshold", 0.8))
        rule_form.addRow("置信度阈值:", self.rule_threshold)

        layout.addWidget(rule_group)

        # AI 分类
        ai_group = QGroupBox("AI 分类")
        ai_form = QFormLayout(ai_group)

        self.ai_enabled_cb = QCheckBox("启用 AI 分类（规则未命中时使用）")
        self.ai_enabled_cb.setChecked(self.config.get("classification.ai_enabled", True))
        ai_form.addRow("", self.ai_enabled_cb)

        self.ai_threshold = QDoubleSpinBox()
        self.ai_threshold.setRange(0.1, 1.0)
        self.ai_threshold.setDecimals(1)
        self.ai_threshold.setSingleStep(0.1)
        self.ai_threshold.setValue(self.config.get("classification.ai_confidence_threshold", 0.5))
        ai_form.addRow("置信度阈值:", self.ai_threshold)

        layout.addWidget(ai_group)

        # 缓存
        cache_group = QGroupBox("缓存")
        cache_layout = QVBoxLayout(cache_group)

        self.cache_enabled_cb = QCheckBox("启用分类缓存（二次运行秒级完成）")
        self.cache_enabled_cb.setChecked(self.config.get("classification.cache_enabled", True))
        cache_layout.addWidget(self.cache_enabled_cb)

        layout.addWidget(cache_group)

        # 删除
        delete_group = QGroupBox("删除操作")
        delete_layout = QVBoxLayout(delete_group)

        self.allow_delete_cb = QCheckBox("允许在审核中标记删除")
        self.allow_delete_cb.setChecked(self.config.get("classification.allow_delete", True))
        delete_layout.addWidget(self.allow_delete_cb)

        self.confirm_delete_cb = QCheckBox("删除前弹出二次确认")
        self.confirm_delete_cb.setChecked(self.config.get("classification.confirm_delete", True))
        delete_layout.addWidget(self.confirm_delete_cb)

        layout.addWidget(delete_group)

        # 分类体系预览
        cats_group = QGroupBox("分类体系（编辑 config.yaml 自定义）")
        cats_layout = QVBoxLayout(cats_group)

        categories = self.config.get_categories()
        preview_text = "\n".join(
            f"{cat['name']} → {', '.join(cat.get('sub_categories', []))}"
            for cat in categories
        )
        self.cats_preview = QTextEdit()
        self.cats_preview.setPlainText(preview_text)
        self.cats_preview.setReadOnly(True)
        self.cats_preview.setMaximumHeight(120)
        cats_layout.addWidget(self.cats_preview)

        layout.addWidget(cats_group)

        layout.addStretch()

    def validate(self) -> list[str]:
        return []

    def save(self):
        self.config.set("classification.rule_enabled", self.rule_enabled_cb.isChecked())
        self.config.set("classification.rule_confidence_threshold", self.rule_threshold.value())
        self.config.set("classification.ai_enabled", self.ai_enabled_cb.isChecked())
        self.config.set("classification.ai_confidence_threshold", self.ai_threshold.value())
        self.config.set("classification.cache_enabled", self.cache_enabled_cb.isChecked())
        self.config.set("classification.allow_delete", self.allow_delete_cb.isChecked())
        self.config.set("classification.confirm_delete", self.confirm_delete_cb.isChecked())

    def reload(self):
        self.rule_enabled_cb.setChecked(self.config.get("classification.rule_enabled", True))
        self.rule_threshold.setValue(self.config.get("classification.rule_confidence_threshold", 0.8))
        self.ai_enabled_cb.setChecked(self.config.get("classification.ai_enabled", True))
        self.ai_threshold.setValue(self.config.get("classification.ai_confidence_threshold", 0.5))
        self.cache_enabled_cb.setChecked(self.config.get("classification.cache_enabled", True))
        self.allow_delete_cb.setChecked(self.config.get("classification.allow_delete", True))
        self.confirm_delete_cb.setChecked(self.config.get("classification.confirm_delete", True))


# ──────────────────────────────────────────────
#  Tab: 高级设置
# ──────────────────────────────────────────────

class AdvancedSettingsTab(QWidget):
    """🔧 高级设置 Tab"""

    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 输出
        output_group = QGroupBox("输出设置")
        output_form = QFormLayout(output_group)

        self.export_dir_input = QLineEdit()
        self.export_dir_input.setText(self.config.get("output.export_dir", "data/exports"))
        output_form.addRow("导出目录:", self.export_dir_input)

        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText(self.config.get("output.log_level", "INFO"))
        output_form.addRow("日志级别:", self.log_level_combo)

        layout.addWidget(output_group)

        # 界面
        ui_group = QGroupBox("界面设置")
        ui_form = QFormLayout(ui_group)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["light", "dark"])
        self.theme_combo.setCurrentText(self.config.get("ui.theme", "light"))
        ui_form.addRow("主题:", self.theme_combo)

        self.language_combo = QComboBox()
        self.language_combo.addItems(["zh_CN", "en_US"])
        self.language_combo.setCurrentText(self.config.get("ui.language", "zh_CN"))
        ui_form.addRow("语言:", self.language_combo)

        layout.addWidget(ui_group)

        layout.addStretch()

    def validate(self) -> list[str]:
        return []

    def save(self):
        self.config.set("output.export_dir", self.export_dir_input.text().strip())
        self.config.set("output.log_level", self.log_level_combo.currentText())
        self.config.set("ui.theme", self.theme_combo.currentText())
        self.config.set("ui.language", self.language_combo.currentText())

    def reload(self):
        self.export_dir_input.setText(self.config.get("output.export_dir", ""))
        self.log_level_combo.setCurrentText(self.config.get("output.log_level", "INFO"))
        self.theme_combo.setCurrentText(self.config.get("ui.theme", "light"))
        self.language_combo.setCurrentText(self.config.get("ui.language", "zh_CN"))

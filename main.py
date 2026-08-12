"""
浏览器收藏夹智能分类管理工具 - 主入口
v1.0 - 完整版 (含启动画面 + 全部 Phase)
"""

import sys
import logging
from pathlib import Path

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.config_manager import ConfigManager
from modules.secure_store import SecureStore
from modules.proxy import ProxyManager
from ui.main_window import MainWindow

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer

# 延迟导入 splash (避免 PyInstaller 打包问题)
try:
    from ui.splash import SplashScreen
    HAS_SPLASH = True
except ImportError:
    HAS_SPLASH = False


def setup_logging(config: ConfigManager):
    """初始化日志系统"""
    log_dir = PROJECT_ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, config.get("output.log_level", "INFO"), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="[%(asctime)s] %(levelname)-7s %(name)s - %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
        ]
    )


def ensure_runtime_dirs(config: ConfigManager):
    """确保运行时目录存在"""
    base = PROJECT_ROOT / "data"
    for sub in ["exports", "cache", "logs", ".secure", "backups"]:
        (base / sub).mkdir(parents=True, exist_ok=True)


def main():
    # 0. 创建 QApplication (需要先于任何 QWidget)
    app = QApplication(sys.argv)
    app.setApplicationName("收藏夹管理工具")
    app.setOrganizationName("BookmarkManager")

    # Qt 6 默认启用高 DPI 缩放，无需手动设置
    # see: https://doc.qt.io/qt-6/highdpi.html

    # 1. 加载配置 (先于 QSS 加载，因为主题配置存储在 config 中)
    config = ConfigManager(PROJECT_ROOT / "config.yaml")
    config.load()

    # 加载全局样式（根据当前主题）
    theme = config.get("ui.theme", "light")
    qss_filename = "styles_dark.qss" if theme == "dark" else "styles.qss"
    qss_path = PROJECT_ROOT / "ui" / "resources" / qss_filename
    if qss_path.exists():
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    # 2. 初始化日志
    setup_logging(config)
    logger = logging.getLogger("main")
    logger.info("=" * 60)
    logger.info("🔖 收藏夹管理工具 v1.0 启动")
    logger.info("=" * 60)

    # 3. 确保目录结构
    ensure_runtime_dirs(config)

    # 4. 初始化核心模块
    secure_store = SecureStore(PROJECT_ROOT / "data" / ".secure")
    proxy = ProxyManager(config, secure_store)

    logger.info("核心模块初始化完成")
    logger.info(f"  配置: {config.config_path}")
    logger.info(f"  代理: {'启用' if proxy.is_enabled() else '禁用'}")
    logger.info(f"  加密存储: {secure_store.store_dir}")

    # 5. 启动画面 or 直接显示
    window = MainWindow(config, secure_store, proxy)

    if HAS_SPLASH:
        splash = SplashScreen()
        splash.show()
        app.processEvents()

        def _on_splash_done():
            splash.close()
            window.show()

        # 显示 1.5 秒后淡出
        QTimer.singleShot(1500, lambda: splash.fade_out(_on_splash_done))
    else:
        window.show()

    logger.info("主窗口已显示，进入事件循环")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

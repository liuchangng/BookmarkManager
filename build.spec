# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 - 收藏夹管理工具
生成: 单文件 exe (Windows) / 单文件可执行 (macOS/Linux)

使用:
  pyinstaller build.spec --clean
"""

import os
import sys
from pathlib import Path

# ──────────────────────────────────────────────
#  路径配置
# ──────────────────────────────────────────────

project_root = Path(SPECPATH).resolve()
app_name = "BookmarkManager"
app_title = "🔖 收藏夹管理工具"

# ──────────────────────────────────────────────
#  数据文件 (需打包进 exe 的资源)
# ──────────────────────────────────────────────

datas = [
    # 配置文件
    (str(project_root / "config.yaml"), "."),
    # UI 样式
    (str(project_root / "ui" / "resources" / "styles.qss"), "ui/resources"),
    # 图标
    (str(project_root / "ui" / "resources" / "icon.ico"), "ui/resources"),
    # 分类规则 (如果有独立文件)
    (str(project_root / "config.yaml"), "config"),
]

# ──────────────────────────────────────────────
#  隐藏导入 (PyQt6 + 动态导入的模块)
# ──────────────────────────────────────────────

hiddenimports = [
    # PyQt6 子模块
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    # 核心依赖
    "requests",
    "urllib3",
    "yaml",
    "openpyxl",
    "cryptography",
    "psutil",
    "scrapling",
    # 动态导入的模块
    "modules.config_manager",
    "modules.secure_store",
    "modules.proxy",
    "modules.exporter",
    "modules.parser",
    "modules.bookmark",
    "modules.classifier",
    "modules.cache",
    "modules.fetcher",
    "modules.fetch_worker",
    "modules.ai_client",
    "modules.ai_worker",
    "modules.excel_writer",
    "modules.html_builder",
    "modules.importer",    # UI 模块
    "ui.main_window",
    "ui.splash",
    "ui.dialogs.settings_dialog",
    "ui.dialogs.review_dialog",
    "ui.dialogs.import_wizard",]

# ──────────────────────────────────────────────
#  排除不需要的模块 (减小体积)
# ──────────────────────────────────────────────

excludes = [
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "PIL",
    "tkinter",
    "unittest",
    "test",
    "distutils",
    "setuptools",
]

# ──────────────────────────────────────────────
#  Windows 专属
# ──────────────────────────────────────────────

if sys.platform == "win32":
    icon_path = str(project_root / "ui" / "resources" / "icon.ico")
    version_file = str(project_root / "version_info.txt")
else:
    icon_path = None
    version_file = None

# ──────────────────────────────────────────────
#  Analysis & Build
# ──────────────────────────────────────────────

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=2,  # 字节码优化
)

pyz = PYZ(a.pure)

# 单文件模式
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # 压缩可执行文件
    upx_exclude=[],
    runtime_tmpdir=None, # 解压到系统临时目录
    console=False,       # 不显示控制台窗口
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
    version=version_file,
)

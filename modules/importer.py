"""
importer.py - 浏览器书签导入辅助
功能: 检测浏览器/备份原文件/生成导入指引/打开浏览器导入页
"""

import logging
import platform
import subprocess
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger("importer")


# ──────────────────────────────────────────────
#  浏览器检测
# ──────────────────────────────────────────────

def detect_browsers() -> dict[str, dict]:
    """
    检测系统已安装的浏览器

    返回: {browser_name: {path, profile_dir, bookmarks_file, installed}}
    """
    system = platform.system().lower()
    results: dict[str, dict] = {}

    if system == "windows":
        results = _detect_windows()
    elif system == "darwin":  # macOS
        results = _detect_macos()
    elif system == "linux":
        results = _detect_linux()

    return results


def _detect_windows() -> dict:
    import os
    user = os.environ.get("USERPROFILE", "")
    local = os.environ.get("LOCALAPPDATA", "")
    results = {}

    # Chrome
    chrome_dir = Path(local) / "Google" / "Chrome" / "User Data"
    if chrome_dir.exists():
        results["chrome"] = {
            "name": "Chrome",
            "installed": True,
            "profile_dir": str(chrome_dir),
            "bookmarks_file": str(chrome_dir / "Default" / "Bookmarks"),
            "import_url": "chrome://bookmarks/",
        }
    else:
        results["chrome"] = {"name": "Chrome", "installed": False}

    # Edge
    edge_dir = Path(local) / "Microsoft" / "Edge" / "User Data"
    if edge_dir.exists():
        results["edge"] = {
            "name": "Edge",
            "installed": True,
            "profile_dir": str(edge_dir),
            "bookmarks_file": str(edge_dir / "Default" / "Bookmarks"),
            "import_url": "edge://favorites/",
        }
    else:
        results["edge"] = {"name": "Edge", "installed": False}

    return results


def _detect_macos() -> dict:
    results = {}

    chrome_dir = Path("~/Library/Application Support/Google/Chrome").expanduser()
    if chrome_dir.exists():
        results["chrome"] = {
            "name": "Chrome", "installed": True,
            "profile_dir": str(chrome_dir),
            "bookmarks_file": str(chrome_dir / "Default" / "Bookmarks"),
            "import_url": "chrome://bookmarks/",
        }
    else:
        results["chrome"] = {"name": "Chrome", "installed": False}

    edge_dir = Path("~/Library/Application Support/Microsoft Edge").expanduser()
    if edge_dir.exists():
        results["edge"] = {
            "name": "Edge", "installed": True,
            "profile_dir": str(edge_dir),
            "bookmarks_file": str(edge_dir / "Default" / "Bookmarks"),
            "import_url": "edge://favorites/",
        }
    else:
        results["edge"] = {"name": "Edge", "installed": False}

    return results


def _detect_linux() -> dict:
    results = {}

    chrome_dir = Path("~/.config/google-chrome").expanduser()
    if chrome_dir.exists():
        results["chrome"] = {
            "name": "Chrome", "installed": True,
            "profile_dir": str(chrome_dir),
            "bookmarks_file": str(chrome_dir / "Default" / "Bookmarks"),
            "import_url": "chrome://bookmarks/",
        }
    else:
        results["chrome"] = {"name": "Chrome", "installed": False}

    edge_dir = Path("~/.config/microsoft-edge").expanduser()
    if edge_dir.exists():
        results["edge"] = {
            "name": "Edge", "installed": True,
            "profile_dir": str(edge_dir),
            "bookmarks_file": str(edge_dir / "Default" / "Bookmarks"),
            "import_url": "edge://favorites/",
        }
    else:
        results["edge"] = {"name": "Edge", "installed": False}

    return results


# ──────────────────────────────────────────────
#  备份原书签
# ──────────────────────────────────────────────

def backup_bookmarks_file(bookmarks_file: str, backup_dir: str = "data/backups") -> str:
    """备份浏览器书签 JSON 文件"""
    import shutil
    from datetime import datetime

    src = Path(bookmarks_file)
    if not src.exists():
        logger.warning(f"⚠️ 书签文件不存在: {bookmarks_file}")
        return ""

    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    browser = "chrome" if "Chrome" in str(src) else "edge"
    dst = backup_path / f"{browser}_bookmarks_{ts}.json"

    shutil.copy2(src, dst)
    logger.info(f"📦 书签已备份: {dst}")
    return str(dst)


def backup_and_replace(bookmarks_file: str, new_html: str, backup_dir: str = "data/backups") -> dict:
    """
    备份原书签并准备替换提示

    注意: 不直接替换 JSON 文件 (格式不同)
    而是备份后提示用户通过浏览器导入 HTML
    """
    backup_path = backup_bookmarks_file(bookmarks_file, backup_dir)

    return {
        "backup_path": backup_path,
        "original_file": bookmarks_file,
        "new_html_size": len(new_html),
        "action": "import_html",  # 用户需手动导入 HTML
    }


# ──────────────────────────────────────────────
#  打开浏览器导入页
# ──────────────────────────────────────────────

def open_import_page(browser: str = "chrome") -> bool:
    """尝试打开浏览器的书签管理页面"""
    system = platform.system().lower()

    urls = {
        "chrome": "chrome://bookmarks/",
        "edge": "edge://favorites/",
    }
    url = urls.get(browser, urls["chrome"])

    try:
        if system == "windows":
            subprocess.Popen(f'start "" "{url}"', shell=True)
        elif system == "darwin":
            subprocess.Popen(["open", url])
        elif system == "linux":
            subprocess.Popen(["xdg-open", url])
        logger.info(f"🌐 已打开 {browser} 书签页面: {url}")
        return True
    except Exception as e:
        logger.error(f"无法打开浏览器: {e}")
        return False


# ──────────────────────────────────────────────
#  导入向导
# ──────────────────────────────────────────────

def create_import_instructions(html_path: str, browser: str = "chrome") -> str:
    """生成完整的导入指引文本"""
    from datetime import datetime

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if browser == "chrome":
        steps = f"""╔════════════════════════════════════════════╗
║   📥 Chrome 书签导入指南                  ║
╠════════════════════════════════════════════╣
║                                            ║
║  生成时间: {ts:<29}║
║  文件位置: {html_path:<29}║
║                                            ║
║  步骤:                                    ║
║  1. 打开 Chrome                            ║
║  2. 地址栏输入: chrome://bookmarks/        ║
║  3. 点击右上角 ⋮ → 导入书签                ║
║  4. 选择文件:                              ║
║     {html_path:<38}║
║  5. 点击「打开」→ 等待导入完成             ║
║  6. 书签会出现在「导入的书签」文件夹       ║
║                                            ║
║  ⚠️ 建议先备份原有书签 (已自动完成)        ║
╚════════════════════════════════════════════╝
"""
    elif browser == "edge":
        steps = f"""╔════════════════════════════════════════════╗
║   📥 Edge 收藏夹导入指南                  ║
╠════════════════════════════════════════════╣
║                                            ║
║  生成时间: {ts:<29}║
║  文件位置: {html_path:<29}║
║                                            ║
║  步骤:                                    ║
║  1. 打开 Edge                              ║
║  2. 地址栏输入: edge://favorites/          ║
║  3. 点击 ⋯ → 导入收藏夹                   ║
║  4. 选择「从文件导入」                     ║
║  5. 选择文件:                              ║
║     {html_path:<38}║
║  6. 点击「打开」→ 等待导入完成             ║
║                                            ║
║  ⚠️ 建议先备份原有收藏夹 (已自动完成)      ║
╚════════════════════════════════════════════╝
"""
    else:
        steps = f"浏览器: {browser}\n文件: {html_path}\n请手动导入此 HTML 文件到浏览器书签。"

    return steps


# ──────────────────────────────────────────────
#  自动导入 (高级 - 直接操作 JSON)
# ──────────────────────────────────────────────

def auto_import_via_json(html_path: str, browser: str = "chrome",
                         profile: str = "Default") -> dict:
    """
    高级功能: 直接修改浏览器 Bookmarks JSON
    ⚠️ 需要浏览器完全关闭!

    返回: {success, message, backup_path}
    """
    import json
    import shutil
    from datetime import datetime

    # 定位书签文件
    system = platform.system().lower()
    if browser == "chrome":
        if system == "windows":
            base = Path(f"{__import__('os').environ.get('LOCALAPPDATA','')}/Google/Chrome/User Data")
        elif system == "darwin":
            base = Path("~/Library/Application Support/Google/Chrome").expanduser()
        else:
            base = Path("~/.config/google-chrome").expanduser()
    elif browser == "edge":
        if system == "windows":
            base = Path(f"{__import__('os').environ.get('LOCALAPPDATA','')}/Microsoft/Edge/User Data")
        elif system == "darwin":
            base = Path("~/Library/Application Support/Microsoft Edge").expanduser()
        else:
            base = Path("~/.config/microsoft-edge").expanduser()
    else:
        return {"success": False, "message": f"不支持的浏览器: {browser}"}

    bm_file = base / profile / "Bookmarks"

    if not bm_file.exists():
        return {"success": False, "message": f"书签文件不存在: {bm_file}"}

    # 备份
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = bm_file.parent / f"Bookmarks.backup_{ts}"
    shutil.copy2(bm_file, backup)

    # 读取 JSON
    try:
        with open(bm_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return {"success": False, "message": "书签 JSON 解析失败 (文件可能正在使用中)"}

    # 检查浏览器是否运行
    import psutil  # 可选依赖
    proc_names = {"chrome": ["chrome.exe", "Google Chrome"], "edge": ["msedge.exe", "Microsoft Edge"]}
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name", "")
        if name in proc_names.get(browser, []):
            return {
                "success": False,
                "message": f"⚠️ {browser} 正在运行! 请先关闭浏览器再试。",
                "backup_path": str(backup),
            }

    # TODO: 将 HTML 解析后写入 JSON 结构
    # 这是高风险操作，Phase 6 仅做框架，完整实现放 v1.1
    return {
        "success": False,
        "message": "自动 JSON 导入功能将在 v1.1 提供。当前请使用 HTML 导入方式。",
        "backup_path": str(backup),
        "html_path": html_path,
    }

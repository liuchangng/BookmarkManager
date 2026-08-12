"""
exporter.py - 浏览器收藏夹导出模块
支持: Chrome / Edge (JSON → Netscape HTML)
功能: 自动检测浏览器和Profile、检查进程占用、带毫秒时间戳命名
"""

import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import platform
import os

from modules.config_manager import ConfigManager

logger = logging.getLogger("exporter")

# Chrome/Edge JSON 中的时间起点: 1601-01-01 (Windows FILETIME epoch)
# 需要转换为 Unix 时间戳 (1970-01-01)
# 差值: 11644473600000000 微秒
FILETIME_OFFSET = 11644473600000000


class BookmarkExporter:
    """
    浏览器收藏夹导出器

    流程:
    1. detect_browsers() → 找到已安装的浏览器和 Profile
    2. check_running() → 检查浏览器是否运行（文件可能被锁）
    3. export() → 读取 JSON → 转换为 Netscape HTML → 保存
    """

    # 已知浏览器定义
    BROWSERS = {
        "chrome": {
            "name": "Google Chrome",
            "windows_path": r"%LOCALAPPDATA%\Google\Chrome\User Data",
            "mac_path": "~/Library/Application Support/Google/Chrome",
            "linux_path": "~/.config/google-chrome",
            "process_names": ["chrome.exe", "Google Chrome", "chrome"],
        },
        "edge": {
            "name": "Microsoft Edge",
            "windows_path": r"%LOCALAPPDATA%\Microsoft\Edge\User Data",
            "mac_path": "~/Library/Application Support/Microsoft Edge",
            "linux_path": "~/.config/microsoft-edge",
            "process_names": ["msedge.exe", "Microsoft Edge", "msedge"],
        },
    }

    def __init__(self, config: ConfigManager):
        self.config = config
        self._last_error: str = ""

    # ──────────────────────────────────────────────
    #  浏览器检测
    # ──────────────────────────────────────────────

    def detect_browsers(self) -> dict[str, list[str]]:
        """
        检测已安装的浏览器及其 Profile 列表
        返回: {"chrome": ["Default", "Profile 1"], "edge": ["Default"]}
        """
        results: dict[str, list[str]] = {}
        system = platform.system()

        for browser_key, info in self.BROWSERS.items():
            # 解析路径
            if system == "Windows":
                base = os.path.expandvars(info["windows_path"])
            elif system == "Darwin":
                base = os.path.expanduser(info["mac_path"])
            else:
                base = os.path.expanduser(info["linux_path"])

            base_path = Path(base)
            if not base_path.exists():
                logger.debug(f"{info['name']} 未安装 ({base_path} 不存在)")
                continue

            # 查找 Profile 目录
            profiles = self._find_profiles(base_path)
            if profiles:
                results[browser_key] = profiles
                logger.info(f"检测到 {info['name']}: {profiles}")
            else:
                logger.debug(f"{info['name']} 未检测到 Profile")

        return results

    def _find_profiles(self, base_path: Path) -> list[str]:
        """在浏览器 User Data 目录下查找所有 Profile"""
        profiles = []

        # 始终检查 Default
        default_path = base_path / "Default"
        if default_path.exists() and (default_path / "Bookmarks").exists():
            profiles.append("Default")

        # 查找 Profile 1, Profile 2, ...
        for item in sorted(base_path.iterdir()):
            if item.is_dir() and item.name.startswith("Profile "):
                if (item / "Bookmarks").exists():
                    profiles.append(item.name)

        # 也检查其他命名的 Profile（如 "Person 1"）
        for item in sorted(base_path.iterdir()):
            if item.is_dir() and item.name not in [p for p in profiles] and item.name not in ["Crashpad", "ShaderCache", "GPUCache", "Default"]:
                if (item / "Bookmarks").exists():
                    profiles.append(item.name)

        return profiles

    def get_bookmarks_path(self, browser: str, profile: str = "Default") -> Optional[Path]:
        """
        获取指定浏览器/Profile 的书签文件路径

        支持两种模式:
        1. profile 为完整路径 → 直接查找该路径下的 Bookmarks 文件
        2. profile 为名称 → 拼接标准浏览器安装路径
        """
        system = platform.system()
        browser = browser.lower()

        # 模式1: profile 是完整路径
        profile_path = Path(profile)
        if profile_path.is_absolute():
            # 路径本身是 Bookmarks 文件
            if profile_path.name == "Bookmarks" and profile_path.exists():
                return profile_path
            # 路径 / Bookmarks
            candidate = profile_path / "Bookmarks"
            if candidate.exists():
                return candidate
            # 路径是 User Data 目录 → Default/Bookmarks
            candidate = profile_path / "Default" / "Bookmarks"
            if candidate.exists():
                return candidate
            # 完全没找到
            logger.debug(f"自定义路径下未找到书签: {profile}")
            return None

        # 模式2: 标准路径拼接
        if browser not in self.BROWSERS:
            return None

        info = self.BROWSERS[browser]
        if system == "Windows":
            base = os.path.expandvars(info["windows_path"])
        elif system == "Darwin":
            base = os.path.expanduser(info["mac_path"])
        else:
            base = os.path.expanduser(info["linux_path"])

        bm_path = Path(base) / profile / "Bookmarks"
        return bm_path if bm_path.exists() else None

    # ──────────────────────────────────────────────
    #  进程检查
    # ──────────────────────────────────────────────

    def check_running(self, browser: str) -> bool:
        """
        检查浏览器进程是否运行中
        返回: True=运行中, False=未运行
        """
        browser = browser.lower()
        if browser not in self.BROWSERS:
            return False

        process_names = self.BROWSERS[browser]["process_names"]
        system = platform.system()

        try:
            if system == "Windows":
                import subprocess
                result = subprocess.run(
                    ["tasklist", "/FO", "CSV"],
                    capture_output=True, text=True, timeout=5
                )
                output = result.stdout.lower()
                for name in process_names:
                    if name.lower() in output:
                        logger.warning(f"{browser} 进程运行中: {name}")
                        return True

            elif system in ("Darwin", "Linux"):
                import subprocess
                result = subprocess.run(
                    ["pgrep", "-l", "-f", process_names[0].split(".")[0]],
                    capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip():
                    logger.warning(f"{browser} 进程运行中")
                    return True

        except Exception as e:
            logger.debug(f"进程检查失败: {e}")

        return False

    # ──────────────────────────────────────────────
    #  进程管理
    # ──────────────────────────────────────────────

    def kill_browser(self, browser: str) -> bool:
        """
        强制关闭浏览器进程
        返回: True=成功终止, False=失败或无进程
        """
        browser = browser.lower()
        if browser not in self.BROWSERS:
            return False

        process_names = self.BROWSERS[browser]["process_names"]
        system = platform.system()

        killed = False
        for name in process_names:
            try:
                if system == "Windows":
                    import subprocess
                    result = subprocess.run(
                        ["taskkill", "/F", "/IM", name],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        logger.info(f"已终止进程: {name}")
                        killed = True
                    elif "not found" not in result.stderr.lower():
                        logger.warning(f"终止进程 {name} 结果: {result.stderr.strip()}")
                elif system in ("Darwin", "Linux"):
                    import subprocess
                    proc_name = name.split(".")[0]
                    result = subprocess.run(
                        ["pkill", "-f", proc_name],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        logger.info(f"已终止进程: {proc_name}")
                        killed = True
            except Exception as e:
                logger.debug(f"终止进程 {name} 失败: {e}")

        return killed

    # ──────────────────────────────────────────────
    #  导出
    # ──────────────────────────────────────────────

    def export(self, browser: str, profile: str = "Default", force: bool = False) -> str:
        """
        导出指定浏览器 Profile 的书签为 Netscape HTML

        参数:
            force: 如果为 True，跳过浏览器进程运行检查
        返回: 导出文件的完整路径
        异常: FileNotFoundError / RuntimeError
        """
        browser = browser.lower()
        bm_path = self.get_bookmarks_path(browser, profile)
        if not bm_path:
            raise FileNotFoundError(
                f"未找到 {browser} [{profile}] 的书签文件\n"
                f"请确认浏览器书签文件路径是否正确，或直接在 Profile 输入框中粘贴完整路径"
            )

        # 检查进程（除非 force=True）
        if not force and self.check_running(browser):
            raise RuntimeError(
                f"{self.BROWSERS[browser]['name']} 正在运行，"
                f"请先关闭浏览器后重试（文件可能被锁定）"
            )

        # 读取 JSON
        try:
            with open(bm_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"书签文件格式错误: {e}")

        # 转换为 Netscape HTML
        html_content = self._chrome_json_to_html(data)

        # 生成输出路径
        export_dir = Path(
            self.config.get("output.export_dir", "data/exports")
        )
        export_dir.mkdir(parents=True, exist_ok=True)

        filename = self._generate_filename()
        output_path = export_dir / filename

        # 写入文件
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info(f"导出成功: {output_path}")
        return str(output_path)

    def export_all_profiles(self, browser: str) -> list[str]:
        """导出某浏览器所有 Profile → 返回文件路径列表"""
        profiles = self.detect_browsers().get(browser, [])
        results = []

        for profile in profiles:
            try:
                path = self.export(browser, profile)
                results.append(path)
            except Exception as e:
                logger.error(f"导出 {browser}[{profile}] 失败: {e}")

        return results

    # ──────────────────────────────────────────────
    #  JSON → Netscape HTML 转换
    # ──────────────────────────────────────────────

    def _chrome_json_to_html(self, json_data: dict) -> str:
        """
        将 Chrome/Edge 书签 JSON 转换为 Netscape 书签 HTML 格式
        """
        now = int(time.time())

        # 文件头
        lines = [
            "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
            '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
            f"<TITLE>Bookmarks ({self.BROWSERS.get('chrome', {}).get('name', '')})</TITLE>",
            "<H1>Bookmarks</H1>",
            "<DL><p>",
        ]

        roots = json_data.get("roots", {})

        # 遍历三个根文件夹
        root_order = ["bookmark_bar", "other", "synced"]
        root_names = {
            "bookmark_bar": "书签栏",
            "other": "其他书签",
            "synced": "已同步",
        }

        for root_key in root_order:
            root = roots.get(root_key)
            if not root:
                continue

            # 根文件夹（使用中文名称）
            display_name = root_names.get(root_key, root.get("name", root_key))
            lines.append(f'    <DT><H3 ADD_DATE="{now}" LAST_MODIFIED="{now}">{display_name}</H3>')
            lines.append("    <DL><p>")

            children = root.get("children", [])
            self._write_node(children, lines, indent=8)

            lines.append("    </DL><p>")

        lines.append("</DL><p>")
        return "\n".join(lines) + "\n"

    def _write_node(self, children: list, lines: list, indent: int = 8):
        """递归写入书签节点"""
        pad = " " * indent

        for item in children:
            item_type = item.get("type", "")

            if item_type == "url":
                # 书签链接
                name = item.get("name", "").replace("<", "&lt;").replace(">", "&gt;")
                url = item.get("url", "")
                add_date = item.get("date_added", "")
                # 转换为 Unix 时间戳
                add_sec = self._filetime_to_unix(add_date)
                tags = item.get("tags", "")

                line = f'{pad}<DT><A HREF="{url}" ADD_DATE="{add_sec}"'
                if tags:
                    line += f' TAGS="{tags}"'
                line += f'>{name}</A>'
                lines.append(line)

            elif item_type == "folder":
                # 文件夹
                name = item.get("name", "").replace("<", "&lt;").replace(">", "&gt;")
                add_date = item.get("date_added", "")
                add_sec = self._filetime_to_unix(add_date)

                lines.append(f'{pad}<DT><H3 ADD_DATE="{add_sec}">{name}</H3>')
                lines.append(f'{pad}<DL><p>')

                sub_children = item.get("children", [])
                self._write_node(sub_children, lines, indent + 4)

                lines.append(f'{pad}</DL><p>')

    @staticmethod
    def _filetime_to_unix(filetime_str: str) -> int:
        """Chrome FILETIME (微秒, 从1601起) → Unix 时间戳 (秒)"""
        try:
            ft = int(filetime_str)
            unix_us = ft - FILETIME_OFFSET
            return max(0, unix_us // 1000000)
        except (ValueError, TypeError):
            return int(time.time())

    @staticmethod
    def _unix_to_readable(timestamp: int) -> str:
        """Unix 时间戳 → 可读日期"""
        try:
            return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError, OSError):
            return ""

    # ──────────────────────────────────────────────
    #  文件名生成
    # ──────────────────────────────────────────────

    def _generate_filename(self) -> str:
        """
        生成带毫秒时间戳的文件名
        格式: bookmark-YYYYMMDDHHmmssSSS.html
        """
        now = datetime.now()
        # 毫秒: 当前微秒 // 1000
        ms = now.microsecond // 1000
        return f"bookmark-{now.strftime('%Y%m%d%H%M%S')}{ms:03d}.html"

    # ──────────────────────────────────────────────
    #  工具方法
    # ──────────────────────────────────────────────

    def get_last_error(self) -> str:
        """获取最后一次错误信息"""
        return self._last_error

    def get_browser_display_name(self, browser_key: str) -> str:
        """获取浏览器的显示名称"""
        return self.BROWSERS.get(browser_key.lower(), {}).get("name", browser_key)

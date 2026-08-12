"""
parser.py - 书签解析模块
支持: Netscape HTML 格式 + Chrome/Edge JSON 原生格式
功能: 提取标题/URL/文件夹/日期/域名 → Bookmark 对象列表
"""

import json
import re
import logging
from typing import Optional
from urllib.parse import urlparse

from modules.bookmark import Bookmark

logger = logging.getLogger("parser")

# Chrome FILETIME offset (微秒)
FILETIME_OFFSET = 11644473600000000


class BookmarkParser:
    """
    书签解析器

    支持两种输入:
    1. Netscape HTML (导出文件或浏览器直接导出)
    2. Chrome/Edge JSON (直接读原生文件，更快更准)
    """

    def __init__(self):
        self._id_counter: int = 0

    # ──────────────────────────────────────────────
    #  统一入口
    # ──────────────────────────────────────────────

    def parse(self, filepath: str) -> list[Bookmark]:
        """自动判断格式并解析"""
        try:
            # utf-8-sig: 自动剥离 BOM；lstrip: 容忍前导空白
            with open(filepath, "r", encoding="utf-8-sig") as f:
                header = f.read(100).lstrip()
        except (UnicodeDecodeError, FileNotFoundError) as e:
            raise RuntimeError(f"无法读取文件: {e}")

        if header.startswith("{"):
            logger.info(f"检测到 JSON 格式: {filepath}")
            return self.parse_chrome_json(filepath)
        else:
            logger.info(f"检测到 Netscape HTML 格式: {filepath}")
            return self.parse_html(filepath)

    # ──────────────────────────────────────────────
    #  HTML 解析 (Netscape 格式) —— 正则线性扫描
    # ──────────────────────────────────────────────

    def parse_html(self, filepath: str) -> list[Bookmark]:
        """
        解析 Netscape 书签 HTML

        方案: 正则线性扫描提取 <A> 标签和文件夹层级。
        文件夹层级通过 <DL> 嵌套深度追踪。
        避免 BeautifulSoup/lxml 对 Netscape 非标准格式的容错干扰。
        """
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # 清理噪声
        content = re.sub(r'<!DOCTYPE[^>]*>', '', content, flags=re.I)
        content = re.sub(r'<META[^>]*>', '', content, flags=re.I)
        content = content.replace('\r\n', '\n').replace('\r', '\n')
        # 移除 <p> 分隔符
        content = re.sub(r'</?p>', '\n', content, flags=re.I)

        # 在每个关键标签前后加换行
        content = re.sub(r'(<DL>)', r'\n\1\n', content, flags=re.I)
        content = re.sub(r'(</DL>)', r'\n\1\n', content, flags=re.I)
        content = re.sub(r'(<DT>)', r'\n\1', content, flags=re.I)

        # 正则
        bookmark_re = re.compile(r'<A\s+HREF="([^"]*)"[^>]*>(.*?)</A>', re.I | re.S)
        folder_re = re.compile(r'<H3[^>]*>(.*?)</H3>', re.I | re.S)
        add_date_re = re.compile(r'ADD_DATE="(\d+)"', re.I)

        bookmarks: list[Bookmark] = []
        self._id_counter = 0
        folder_stack: list[str] = []

        lines = content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            if line == '<DL>':
                # 进入子文件夹层级（名称已在之前的 H3 中入栈）
                pass

            elif line == '</DL>':
                # 退出当前文件夹
                if folder_stack:
                    folder_stack.pop()

            elif line.startswith('<DT>') or line.startswith('<DT '):
                # 收集完整 DT 内容（可能跨行）
                dt_lines = [line]
                # 看下几行是否属于同一个 DT
                j = i + 1
                # 简单策略：如果下一行以 < 开头且不是 </DT> 或 <DL，继续收集
                # 但实际上 A 和 H3 通常都在同一行内
                # 关键是找到对应的 </DT> 或下一个 <DT>
                while j < len(lines):
                    nl = lines[j].strip()
                    if not nl:
                        j += 1
                        continue
                    if nl.startswith('<DT') or nl.startswith('</DT>') or nl == '<DL>' or nl == '</DL>':
                        break
                    # 可能是跨行的 A 或 H3 内容
                    dt_lines.append(nl)
                    j += 1

                dt_content = '\n'.join(dt_lines)

                if '<A' in dt_content.upper():
                    # 书签链接
                    m = bookmark_re.search(dt_content)
                    if m:
                        url = m.group(1).strip()
                        title = m.group(2).strip()
                        title = self._decode_entities(title)

                        if url and not url.startswith('javascript:'):
                            dm = add_date_re.search(dt_content)
                            add_sec = self._parse_add_date(dm.group(1) if dm else "")

                            self._id_counter += 1
                            root = folder_stack[0] if folder_stack else "书签栏"
                            bookmark = Bookmark(
                                id=self._id_counter,
                                title=title or url,
                                url=url,
                                folder=" / ".join(folder_stack) if folder_stack else "",
                                root_folder=root,
                                add_date=self._unix_to_readable(add_sec),
                                add_date_raw=str(add_sec),
                                domain=self._extract_domain(url),
                            )
                            bookmarks.append(bookmark)

                elif '<H3' in dt_content.upper():
                    # 文件夹
                    m = folder_re.search(dt_content)
                    if m:
                        folder_name = self._decode_entities(m.group(1).strip())
                        if folder_name:
                            folder_stack.append(folder_name)

                i = j
                continue

            i += 1

        logger.info(f"HTML 解析完成: {len(bookmarks)} 条书签")
        return bookmarks

    # ──────────────────────────────────────────────
    #  JSON 解析 (Chrome/Edge 原生)
    # ──────────────────────────────────────────────

    def parse_chrome_json(self, filepath: str) -> list[Bookmark]:
        """解析 Chrome/Edge 原生 JSON 格式"""
        try:
            # utf-8-sig: 自动剥离 BOM
            with open(filepath, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"书签 JSON 解析失败: {e}")

        if not isinstance(data, dict):
            raise RuntimeError("书签 JSON 格式不正确: 顶层应为对象")

        bookmarks: list[Bookmark] = []
        self._id_counter = 0

        roots = data.get("roots") or {}
        root_names = {
            "bookmark_bar": "书签栏",
            "other": "其他书签",
            "synced": "已同步",
        }

        for root_key, root_data in roots.items():
            if not root_data:
                continue
            display_name = root_names.get(root_key, root_data.get("name", root_key))
            children = root_data.get("children", []) or []
            self._parse_json_children(children, [display_name], bookmarks)

        logger.info(f"JSON 解析完成: {len(bookmarks)} 条书签")
        return bookmarks

    def _parse_json_children(self, children: list, folder_stack: list[str], results: list[Bookmark]):
        for item in children:
            item_type = item.get("type", "")
            if item_type == "url":
                bookmark = self._parse_json_bookmark(item, folder_stack)
                if bookmark:
                    results.append(bookmark)
            elif item_type == "folder":
                folder_name = item.get("name", "").strip()
                new_stack = list(folder_stack) + ([folder_name] if folder_name else [])
                self._parse_json_children(item.get("children", []) or [], new_stack, results)

    def _parse_json_bookmark(self, item: dict, folder_stack: list[str]) -> Optional[Bookmark]:
        url = item.get("url", "").strip()
        title = item.get("name", "").strip()
        if not url or url.startswith("javascript:"):
            return None

        add_sec = self._filetime_to_unix(item.get("date_added", ""))
        self._id_counter += 1

        root = folder_stack[0] if folder_stack else "书签栏"
        return Bookmark(
            id=self._id_counter,
            title=title or url,
            url=url,
            folder=" / ".join(folder_stack) if folder_stack else "",
            root_folder=root,
            add_date=self._unix_to_readable(add_sec),
            add_date_raw=str(add_sec),
            domain=self._extract_domain(url),
        )

    # ──────────────────────────────────────────────
    #  工具方法
    # ──────────────────────────────────────────────

    @staticmethod
    def _decode_entities(text: str) -> str:
        """解码 HTML 实体（&amp; &lt; &quot; &#39; &#x27; &nbsp; 等）"""
        from html import unescape
        return unescape(text or "").strip()

    @staticmethod
    def _parse_add_date(raw: str) -> int:
        """解析 ADD_DATE 属性值 → Unix 秒"""
        if not raw:
            return 0
        try:
            val = int(raw)
            # Chrome: 微秒 (17位) → 除以 1e6
            # Netscape: 秒 (10位) 或毫秒 (13位)
            if val > 10**14:  # 微秒
                return val // 1000000
            elif val > 10**11:  # 毫秒
                return val // 1000
            else:  # 秒
                return val
        except ValueError:
            return 0

    @staticmethod
    def _filetime_to_unix(filetime_str: str) -> int:
        """Chrome FILETIME (微秒, 从1601起) → Unix 秒"""
        try:
            ft = int(filetime_str)
            return max(0, (ft - FILETIME_OFFSET) // 1000000)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _unix_to_readable(timestamp: int) -> str:
        try:
            from datetime import datetime
            return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError, OSError):
            return ""

    @staticmethod
    def _extract_domain(url: str) -> str:
        """提取主域名"""
        multi_suffixes = {
            "co.uk", "com.au", "com.cn", "org.cn", "net.cn", "gov.cn",
            "co.jp", "ne.jp", "ac.uk", "com.tw", "com.hk", "com.sg",
            "co.kr", "co.in", "com.br", "com.mx",
        }
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            if not host:
                return ""
            if host.startswith("www."):
                host = host[4:]
            if all(p.isdigit() for p in host.split(".") if p):
                return host
            parts = host.split(".")
            if len(parts) <= 2:
                return host
            last_two = f"{parts[-2]}.{parts[-1]}"
            if last_two in multi_suffixes and len(parts) >= 3:
                return f"{parts[-3]}.{parts[-2]}.{parts[-1]}"
            return f"{parts[-2]}.{parts[-1]}"
        except Exception:
            return ""

    # ──────────────────────────────────────────────
    #  后处理
    # ──────────────────────────────────────────────

    def merge_duplicates(self, bookmarks: list[Bookmark]) -> list[Bookmark]:
        """去重：同 URL 只保留第一条"""
        seen: dict[str, Bookmark] = {}
        for bm in bookmarks:
            url = bm.url.strip().rstrip("/")
            if url in seen:
                existing = seen[url]
                if bm.folder and bm.folder not in existing.folder:
                    existing.folder = f"{existing.folder} | {bm.folder}"
            else:
                seen[url] = bm
        result = list(seen.values())
        dup_count = len(bookmarks) - len(result)
        if dup_count > 0:
            logger.info(f"去重: 移除 {dup_count} 条重复，剩余 {len(result)} 条")
        return result

    def get_stats(self, bookmarks: list[Bookmark]) -> dict:
        """统计信息"""
        domains: dict[str, int] = {}
        folders: dict[str, int] = {}
        for bm in bookmarks:
            if bm.domain:
                domains[bm.domain] = domains.get(bm.domain, 0) + 1
            if bm.folder:
                top = bm.folder.split(" / ")[0]
                folders[top] = folders.get(top, 0) + 1

        return {
            "total": len(bookmarks),
            "unique_domains": len(domains),
            "top_domains": sorted(domains.items(), key=lambda x: x[1], reverse=True)[:10],
            "top_folders": sorted(folders.items(), key=lambda x: x[1], reverse=True)[:10],
            "with_date": sum(1 for bm in bookmarks if bm.add_date),
            "without_date": sum(1 for bm in bookmarks if not bm.add_date),
        }

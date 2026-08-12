"""
html_builder.py - 分类后 HTML 生成器
功能: 将审核后的书签列表生成 Netscape Bookmark HTML 格式
特性: 两级文件夹(L1/L2) / 保留原始日期 / 图标 favicon / 排序
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from modules.bookmark import Bookmark

logger = logging.getLogger("html_builder")


# ──────────────────────────────────────────────
#  常量
# ──────────────────────────────────────────────

DOCTYPE = "<!DOCTYPE NETSCAPE-Bookmark-file-1>"
HEADER = (
    '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n'
    '<TITLE>Bookmarks</TITLE>\n'
)
ROOT_FOLDER_ICON = "folder"
DEFAULT_ICON = "https://www.google.com/s2/favicons?domain="


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def _esc(text: str) -> str:
    """HTML 转义"""
    if not text:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _timestamp_to_netscape(ts: float) -> str:
    """将时间戳转为 Netscape 格式 (秒级整数)"""
    return str(int(ts))


def _datetime_to_netscape(dt_str: str) -> str:
    """将 ISO 日期字符串转为 Netscape 时间戳"""
    if not dt_str:
        return _timestamp_to_netscape(time.time())
    try:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
            try:
                dt = datetime.strptime(str(dt_str), fmt)
                return _timestamp_to_netscape(dt.timestamp())
            except ValueError:
                continue
        # 尝试 int
        return _timestamp_to_netscape(int(dt_str))
    except (ValueError, TypeError):
        return _timestamp_to_netscape(time.time())


def _get_favicon_url(url: str) -> str:
    """获取 favicon URL"""
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).hostname or ""
        if domain:
            return f"{DEFAULT_ICON}{domain}"
    except Exception:
        pass
    return ""


# ──────────────────────────────────────────────
#  核心生成器
# ──────────────────────────────────────────────

class BookmarkHTMLBuilder:
    """
    将书签列表构建为 Netscape Bookmark HTML

    两级结构:
        📁 书签栏
            📂 💻 开发技术
                📂 代码托管
                    🔖 GitHub
                    🔖 GitLab
                📂 文档教程
                    🔖 MDN
            📂 📚 学习知识
                ...
        📁 其他书签
            📂 📁 其他
                ...
    """

    def __init__(self, bookmarks: list[Bookmark],
                 root_name: str = "书签栏",
                 other_root_name: str = "其他书签",
                 sort_by: str = "title",  # title / date / domain / folder
                 add_favicon: bool = True,
                 preserve_dates: bool = True,
                 backup_original: bool = True,
                 include_dead: bool = False,    # 默认排除失效链接（设计决策 #1）
                 include_local: bool = True):   # 默认包含本地/内网（设计决策 #2）
        self.bookmarks = bookmarks
        self.root_name = root_name
        self.other_root_name = other_root_name
        self.sort_by = sort_by
        self.add_favicon = add_favicon
        self.preserve_dates = preserve_dates
        self.backup_original = backup_original
        self.include_dead = include_dead
        self.include_local = include_local

        self.stats = {
            "total": len(bookmarks),
            "kept": 0,
            "deleted": 0,
            "excluded_dead": 0,
            "excluded_local": 0,
            "folders_created": 0,
            "favicons_added": 0,
        }

    # ──────────────────────────────────────────────
    #  主入口
    # ──────────────────────────────────────────────

    def build(self) -> str:
        """生成完整 HTML 字符串"""
        # 过滤已删除
        active = [b for b in self.bookmarks if not b.user_deleted]
        deleted = [b for b in self.bookmarks if b.user_deleted]
        self.stats["deleted"] = len(deleted)

        # T5.3: 按状态过滤（失效默认排除、本地默认包含）
        kept = []
        for bm in active:
            if bm.status == "dead" and not self.include_dead:
                self.stats["excluded_dead"] += 1
                continue
            if bm.status == "local" and not self.include_local:
                self.stats["excluded_local"] += 1
                continue
            kept.append(bm)
        active = kept
        self.stats["kept"] = len(active)

        # 按 root 分组
        by_root: dict[str, list[Bookmark]] = {}
        for bm in active:
            root = bm.root_folder or self.root_name
            by_root.setdefault(root, []).append(bm)

        # 构建 HTML
        lines: list[str] = []
        lines.append(DOCTYPE)
        lines.append(HEADER)
        lines.append('<H1>Bookmarks</H1>\n')
        lines.append('<DL><p>\n')

        now = time.time()
        now_str = _timestamp_to_netscape(now)

        for root_name, bms in by_root.items():
            # 空根目录不输出，避免生成无内容文件夹
            if not bms:
                continue

            # 根文件夹
            lines.append(
                f'    <DT><H3 ADD_DATE="{now_str}" LAST_MODIFIED="{now_str}">'
                f'{_esc(root_name)}</H3>\n'
            )
            lines.append('    <DL><p>\n')

            # 按 L1 分组
            by_l1: dict[str, list[Bookmark]] = {}
            no_category: list[Bookmark] = []
            for bm in bms:
                l1 = bm.category_l1 or "📁 其他"
                if l1 == "其他" or not bm.category_l1:
                    l1 = "📁 其他"
                if l1 in ("📁 其他",) or not bm.category_l1:
                    no_category.append(bm)
                else:
                    by_l1.setdefault(l1, []).append(bm)

            # 有分类的: 按 L1 → L2 输出
            for l1_name in sorted(by_l1.keys()):
                l1_bms = by_l1[l1_name]
                l1_modified = self._latest_date(l1_bms)

                lines.append(
                    f'        <DT><H3 ADD_DATE="{now_str}" '
                    f'LAST_MODIFIED="{l1_modified}">{_esc(l1_name)}</H3>\n'
                )
                lines.append('        <DL><p>\n')
                self.stats["folders_created"] += 1

                # 按 L2 分组
                by_l2: dict[str, list[Bookmark]] = {}
                for bm in l1_bms:
                    l2 = bm.category_l2 or "未分类"
                    by_l2.setdefault(l2, []).append(bm)

                for l2_name in sorted(by_l2.keys()):
                    l2_bms = by_l2[l2_name]
                    l2_modified = self._latest_date(l2_bms)

                    lines.append(
                        f'            <DT><H3 ADD_DATE="{now_str}" '
                        f'LAST_MODIFIED="{l2_modified}">{_esc(l2_name)}</H3>\n'
                    )
                    lines.append('            <DL><p>\n')
                    self.stats["folders_created"] += 1

                    # 排序
                    sorted_bms = self._sort(l2_bms)
                    for bm in sorted_bms:
                        lines.append(self._render_bookmark(bm))

                    lines.append('            </DL><p>\n')

                lines.append('        </DL><p>\n')

            # 无分类的 / "其他" —— 保持两级结构: 📁 其他 / <待分类>
            if no_category:
                other_name = "📁 其他"
                other_modified = self._latest_date(no_category)
                lines.append(
                    f'        <DT><H3 ADD_DATE="{now_str}" '
                    f'LAST_MODIFIED="{other_modified}">{other_name}</H3>\n'
                )
                lines.append('        <DL><p>\n')
                self.stats["folders_created"] += 1

                # 按二级小类分组
                by_l2: dict[str, list[Bookmark]] = {}
                for bm in no_category:
                    l2 = bm.category_l2 or "未分类"
                    by_l2.setdefault(l2, []).append(bm)

                for l2_name in sorted(by_l2.keys()):
                    l2_bms = by_l2[l2_name]
                    l2_modified = self._latest_date(l2_bms)
                    lines.append(
                        f'            <DT><H3 ADD_DATE="{now_str}" '
                        f'LAST_MODIFIED="{l2_modified}">{_esc(l2_name)}</H3>\n'
                    )
                    lines.append('            <DL><p>\n')
                    self.stats["folders_created"] += 1

                    for bm in self._sort(l2_bms):
                        lines.append(self._render_bookmark(bm))

                    lines.append('            </DL><p>\n')

                lines.append('        </DL><p>\n')

            lines.append('    </DL><p>\n')

        lines.append('</DL><p>\n')

        html = "".join(lines)
        logger.info(
            f"✅ HTML 构建完成: {self.stats['kept']} 条书签, "
            f"{self.stats['folders_created']} 个文件夹, "
            f"{self.stats['favicons_added']} 个 favicon"
        )
        return html

    # ──────────────────────────────────────────────
    #  书签渲染
    # ──────────────────────────────────────────────

    def _render_bookmark(self, bm: Bookmark) -> str:
        """渲染单条书签为 <DT><A> 标签"""
        # 日期
        if self.preserve_dates and bm.add_date:
            add_date = _datetime_to_netscape(bm.add_date)
        else:
            add_date = _timestamp_to_netscape(time.time())

        last_modified = add_date  # Netscape 用同一值

        # favicon
        icon = ""
        if self.add_favicon:
            favicon = _get_favicon_url(bm.url)
            if favicon:
                icon = f' ICON="{_esc(favicon)}"'
                self.stats["favicons_added"] += 1

        # 标签
        tags = ""
        if bm.tags:
            tags = f' TAGS="{_esc(",".join(bm.tags))}"'

        # 分类信息作为标签前缀
        classify_tag = ""
        if bm.classify_method:
            method_map = {
                "rule_domain": "规则-域名",
                "rule_keyword": "规则-关键词",
                "rule_path": "规则-路径",
                "rule_regex": "规则-正则",
                "ai_deepseek": "AI",
                "user_confirmed": "用户确认",
                "manual": "手动",
            }
            m = method_map.get(bm.classify_method, bm.classify_method)
            classify_tag = f' CLASSIFY="{_esc(m)}"'

        title = _esc(bm.title) or _esc(bm.url)
        url = _esc(bm.url)

        return (
            f'                <DT><A HREF="{url}" '
            f'ADD_DATE="{add_date}" '
            f'LAST_MODIFIED="{last_modified}"'
            f'{icon}{tags}{classify_tag}>'
            f'{title}</A>\n'
        )

    # ──────────────────────────────────────────────
    #  排序
    # ──────────────────────────────────────────────

    def _sort(self, bookmarks: list[Bookmark]) -> list[Bookmark]:
        """排序书签列表"""
        bms = list(bookmarks)
        if self.sort_by == "title":
            bms.sort(key=lambda b: b.title.lower())
        elif self.sort_by == "date":
            bms.sort(key=lambda b: str(b.add_date or ""), reverse=True)
        elif self.sort_by == "domain":
            bms.sort(key=lambda b: b.domain)
        elif self.sort_by == "folder":
            bms.sort(key=lambda b: (b.category_l1 or "", b.category_l2 or ""))
        return bms

    def _latest_date(self, bookmarks: list[Bookmark]) -> str:
        """获取一组书签中最新的日期"""
        if not self.preserve_dates:
            return _timestamp_to_netscape(time.time())

        latest = None
        for bm in bookmarks:
            if bm.add_date:
                ts = _datetime_to_netscape(bm.add_date)
                if latest is None or ts > latest:
                    latest = ts
        return latest or _timestamp_to_netscape(time.time())

    # ──────────────────────────────────────────────
    #  保存到文件
    # ──────────────────────────────────────────────

    def save(self, output_path: str) -> str:
        """生成并保存到文件"""
        html = self.build()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"💾 HTML 已保存: {output_path} ({len(html)} 字节)")
        return output_path

    # ──────────────────────────────────────────────
    #  备份原文件
    # ──────────────────────────────────────────────

    @staticmethod
    def backup_original_file(original_path: str, backup_dir: str = "data/backups") -> str:
        """备份原始书签文件"""
        if not Path(original_path).exists():
            logger.warning(f"⚠️ 原始文件不存在: {original_path}")
            return ""

        backup_path = Path(backup_dir)
        backup_path.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        src_name = Path(original_path).name
        dst = backup_path / f"backup_{ts}_{src_name}"

        import shutil
        shutil.copy2(original_path, dst)
        logger.info(f"📦 原始文件已备份: {dst}")
        return str(dst)


# ──────────────────────────────────────────────
#  预览生成器 (轻量级, 用于 UI 预览)
# ──────────────────────────────────────────────

def generate_preview_tree(bookmarks: list[Bookmark], max_items: int = 50) -> str:
    """
    生成文本预览树 (用于 UI 展示)
    返回: 多行字符串
    """
    active = [b for b in bookmarks if not b.user_deleted]

    # 按 L1/L2 分组
    tree: dict[str, dict[str, list[Bookmark]]] = {}
    for bm in active:
        l1 = bm.category_l1 or "📁 其他"
        l2 = bm.category_l2 or "未分类"
        tree.setdefault(l1, {}).setdefault(l2, []).append(bm)

    lines = [f"📊 分类预览 (共 {len(active)} 条, 显示前 {max_items} 项)\n"]

    count = 0
    for l1 in sorted(tree.keys()):
        if count >= max_items:
            lines.append(f"  ... (更多省略)")
            break
        l1_bms = []
        for l2 in sorted(tree[l1].keys()):
            l1_bms.extend(tree[l1][l2])

        lines.append(f"📂 {l1} ({len(l1_bms)})")
        for l2 in sorted(tree[l1].keys()):
            bms = tree[l1][l2]
            lines.append(f"  ├─ {l2} ({len(bms)})")
            for bm in bms[:3]:
                if count >= max_items:
                    break
                icon = "🔖"
                title = bm.title[:30] + ("…" if len(bm.title) > 30 else "")
                lines.append(f"  │   {icon} {title}")
                count += 1
            if len(bms) > 3:
                lines.append(f"  │   ... +{len(bms)-3} 条")

    return "\n".join(lines)


# ──────────────────────────────────────────────
#  验证生成结果
# ──────────────────────────────────────────────

def validate_html(html: str) -> dict:
    """
    验证生成的 HTML 是否符合 Netscape 格式
    返回: {valid: bool, errors: [...], stats: {...}}
    """
    errors: list[str] = []
    stats = {"total_tags": 0, "bookmarks": 0, "folders": 0, "depth": 0}

    # 基本检查
    if "<!DOCTYPE NETSCAPE" not in html.upper():
        errors.append("缺少 DOCTYPE 声明")

    if "<DL>" not in html:
        errors.append("缺少 <DL> 标签")

    # 计数
    import re
    dt_count = len(re.findall(r"<DT>", html, re.IGNORECASE))
    a_count = len(re.findall(r"<A\s+HREF", html, re.IGNORECASE))
    h3_count = len(re.findall(r"<H3", html, re.IGNORECASE))
    dl_open = len(re.findall(r"<DL>", html, re.IGNORECASE))
    dl_close = len(re.findall(r"</DL>", html, re.IGNORECASE))

    stats["total_tags"] = dt_count
    stats["bookmarks"] = a_count
    stats["folders"] = h3_count

    if a_count == 0:
        errors.append("没有生成任何书签条目")

    if dl_open != dl_close:
        errors.append(f"<DL> 标签不匹配: 开启 {dl_open} vs 关闭 {dl_close}")

    # 深度检查
    max_depth = 0
    depth = 0
    for line in html.split("\n"):
        if "<DL>" in line.upper():
            depth += 1
            max_depth = max(max_depth, depth)
        elif "</DL>" in line.upper():
            depth -= 1
    stats["depth"] = max_depth

    if max_depth > 4:
        errors.append(f"嵌套过深: {max_depth} 层 (Netscape 标准通常 3-4 层)")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "stats": stats,
    }


# ──────────────────────────────────────────────
#  导入指南生成
# ──────────────────────────────────────────────

def generate_import_guide(browser: str = "chrome") -> str:
    """生成浏览器导入指南"""
    guides = {
        "chrome": """📥 Chrome 导入书签步骤:

1. 打开 Chrome 浏览器
2. 点击右上角 ⋮ → 书签和清单 → 书签管理器
   (或直接访问 chrome://bookmarks/)
3. 点击右上角 ⋮ → 导入书签
4. 选择生成的 HTML 文件
5. 导入完成后，书签会出现在「导入的书签」文件夹中

⚠️ 建议: 先删除旧的分类混乱的书签，再导入新的
""",
        "edge": """📥 Edge 导入书签步骤:

1. 打开 Edge 浏览器
2. 点击右上角 ⋯ → 收藏夹 → ⋯ → 管理收藏夹
   (或直接访问 edge://favorites/)
3. 点击 ⋯ → 导入收藏夹
4. 选择 "从文件导入" → 选择 HTML 文件
5. 确认导入

⚠️ 建议: 先清空或整理旧收藏夹
""",
    }
    return guides.get(browser, guides["chrome"])


# ──────────────────────────────────────────────
#  一键构建 + 保存 + 验证
# ──────────────────────────────────────────────

def build_and_save(
    bookmarks: list[Bookmark],
    output_path: str,
    root_name: str = "书签栏",
    sort_by: str = "title",
    add_favicon: bool = True,
    preserve_dates: bool = True,
    include_dead: bool = False,
    include_local: bool = True,
) -> dict:
    """
    一键构建并保存

    返回: {success, path, html_size, stats, validation}
    """
    builder = BookmarkHTMLBuilder(
        bookmarks=bookmarks,
        root_name=root_name,
        sort_by=sort_by,
        add_favicon=add_favicon,
        preserve_dates=preserve_dates,
        include_dead=include_dead,
        include_local=include_local,
    )

    path = builder.save(output_path)
    html_size = Path(path).stat().st_size

    validation = validate_html(Path(path).read_text(encoding="utf-8"))

    result = {
        "success": validation["valid"],
        "path": path,
        "html_size": html_size,
        "stats": builder.stats,
        "validation": validation,
    }

    if not validation["valid"]:
        logger.warning(f"⚠️ HTML 验证有 {len(validation['errors'])} 个问题:")
        for e in validation["errors"]:
            logger.warning(f"   • {e}")

    return result

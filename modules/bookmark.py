"""
bookmark.py - 书签数据结构
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Bookmark:
    """单条书签的完整信息"""
    id: int = 0
    title: str = ""
    url: str = ""
    folder: str = ""           # 原始文件夹路径（如 "书签栏/开发工具/在线"）
    root_folder: str = ""       # 根文件夹（"书签栏" 或 "其他书签"）
    add_date: str = ""         # 可读日期
    add_date_raw: str = ""     # 原始时间戳（用于排序）
    domain: str = ""           # 提取的主域名
    category_l1: str = ""      # 大类
    category_l2: str = ""      # 子类
    classify_method: str = ""   # rule / ai / manual / fallback
    confidence: float = 0.0     # 置信度 0-1
    user_confirmed: bool = False
    user_deleted: bool = False
    page_summary: str = ""      # 网页摘要（供AI使用）
    tags: list = field(default_factory=list)  # 标签
    error: str = ""             # 错误信息
    # ── URL 体检（T1，design §6 C1）──
    status: str = "pending"     # ok / local / dead / pending
    probe_error: str = ""       # 死链原因（DNS/HTTP/超时/SSL）
    http_status: int = 0        # 探活 HTTP 状态码

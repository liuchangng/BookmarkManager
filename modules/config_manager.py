"""
config_manager.py - 配置管理系统
负责加载、读取、修改、保存 YAML 配置文件
"""

import yaml
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("config")


class ConfigManager:
    """统一管理 config.yaml 的读写"""

    DEFAULT_CONFIG = {
        "browser": {
            "type": "auto",
            "chrome_profiles": [],
            "edge_profiles": [],
        },
        "proxy": {
            "enabled": False,
            "auto_detect_system": True,
            "custom": {
                "enabled": False,
                "type": "http",
                "host": "127.0.0.1",
                "port": 7890,
                "username": "",
                "password": "",
            },
            "use_for": {
                "web_fetch": True,
                "ai_api": False,
                "firecrawl": True,
            },
            "bypass_domains": [
                "api.deepseek.com",
                "localhost",
                "127.0.0.1",
            ],
        },
        "ai": {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
            "timeout": 30,
            "max_retries": 3,
            "concurrency": 3,
            "batch_size": 5,
            "max_cost_yuan": 5.0,
        },
        "firecrawl": {
            "enabled": True,
            "api_url": "https://api.firecrawl.dev/v1",
            "timeout": 30,
        },
        "fetch": {
            "engine": "scrapling",
            "timeout": 10,
            "max_retries": 2,
            "concurrency": 5,
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "fallback_to_firecrawl": True,
        },
        "classification": {
            "rule_enabled": True,
            "rule_confidence_threshold": 0.8,
            "ai_enabled": True,
            "ai_confidence_threshold": 0.5,
            "cache_enabled": True,
            "cache_dir": "data/cache",
            "allow_delete": True,
            "confirm_delete": True,
            "summary_rule_enabled": True,
        },
        "categories": [
            {
                "name": "💻 开发技术",
                "keywords": [
                    "github", "stackoverflow", "gitlab", "npm", "pypi",
                    "docker", "kubernetes", "maven", "gradle", "pip",
                    "go.dev", "rust-lang", "python.org", "mdn",
                ],
                "sub_categories": ["代码托管", "文档教程", "开发工具", "API/SDK", "DevOps"],
                "sub_keywords": {
                    "代码托管": ["github", "gitlab", "gitee", "bitbucket", "coding.net"],
                    "文档教程": ["mdn", "docs", "w3schools", "developer", "tutorial"],
                    "开发工具": ["vscode", "jetbrains", "codepen", "jsfiddle", "postman"],
                    "API/SDK": ["api", "sdk", "openapi", "swagger"],
                    "DevOps": ["jenkins", "gitlab-ci", "terraform", "ansible"],
                },
            },
            {
                "name": "📚 学习知识",
                "keywords": [
                    "wikipedia", "zhihu", "juejin", "csdn", "cnblogs",
                    "coursera", "edx", "arxiv", "sciencedirect", "springer",
                ],
                "sub_categories": ["百科", "技术博客", "在线课程", "论文/研究"],
                "sub_keywords": {
                    "百科": ["wikipedia", "baike"],
                    "技术博客": ["juejin", "csdn", "cnblogs", "segmentfault", "medium"],
                    "在线课程": ["coursera", "udemy", "edx", "mooc"],
                    "论文/研究": ["arxiv", "sciencedirect", "springer", "semanticscholar", "pubmed"],
                },
            },
            {
                "name": "🛒 购物消费",
                "keywords": [
                    "taobao", "jd.com", "amazon", "tmall", "1688",
                    "pdd", "ebay", "aliexpress", "suning",
                ],
                "sub_categories": ["综合电商", "海淘", "优惠券/比价"],
                "sub_keywords": {
                    "综合电商": ["taobao", "jd.com", "tmall", "pdd", "suning"],
                    "海淘": ["amazon", "ebay", "aliexpress", "iherb"],
                    "优惠券/比价": ["smzdm", "什么值得买"],
                },
            },
            {
                "name": "📺 视频娱乐",
                "keywords": [
                    "youtube", "bilibili", "netflix", "douyin", "vimeo",
                    "iqiyi", "youku", "tiktok", "twitch",
                ],
                "sub_categories": ["在线视频", "短视频", "直播", "音乐"],
                "sub_keywords": {
                    "在线视频": ["youtube", "bilibili", "netflix", "iqiyi", "youku", "vimeo"],
                    "短视频": ["douyin", "tiktok", "kuaishou"],
                    "直播": ["twitch", "huya", "douyu"],
                    "音乐": ["spotify", "qqmusic", "netease", "kugou"],
                },
            },
            {
                "name": "💬 社交沟通",
                "keywords": [
                    "twitter", "weibo", "telegram", "discord", "whatsapp",
                    "reddit", "mastodon", "line",
                ],
                "sub_categories": ["社交媒体", "即时通讯", "论坛/社区"],
                "sub_keywords": {
                    "社交媒体": ["twitter", "weibo", "instagram", "facebook"],
                    "即时通讯": ["telegram", "discord", "whatsapp", "wechat", "qq"],
                    "论坛/社区": ["reddit", "v2ex", "hackernews"],
                },
            },
            {
                "name": "💰 金融银行",
                "keywords": [
                    "paypal", "alipay", "bank", "stock", "fund",
                    "eastmoney", "binance", "coinbase", "xueqiu",
                ],
                "sub_categories": ["银行/支付", "股票/基金", "加密货币"],
                "sub_keywords": {
                    "银行/支付": ["paypal", "alipay", "wechatpay", "unionpay", "icbc", "ccb"],
                    "股票/基金": ["eastmoney", "xueqiu", "tonghuashun", "stock", "fund"],
                    "加密货币": ["binance", "coinbase", "okx", "bybit", "metamask"],
                },
            },
            {
                "name": "☁️ 云存储与工具",
                "keywords": [
                    "drive", "dropbox", "onedrive", "notion", "feishu",
                    "docs", "figma", "canva", "trello", "airtable",
                ],
                "sub_categories": ["网盘/存储", "笔记/文档", "在线工具", "设计"],
                "sub_keywords": {
                    "网盘/存储": ["drive", "dropbox", "onedrive", "baiduyun", "aliyundrive"],
                    "笔记/文档": ["notion", "feishu", "docs", "yuque", "evernote", "obsidian"],
                    "在线工具": ["canva", "trello", "airtable", "ilovepdf"],
                    "设计": ["figma", "dribbble", "behance", "pinterest"],
                },
            },
            {
                "name": "🎮 游戏",
                "keywords": [
                    "steam", "epic", "battlenet", "twitch", "gamer",
                    "ign.com", "gamespot",
                ],
                "sub_categories": ["游戏平台", "攻略/社区"],
                "sub_keywords": {
                    "游戏平台": ["steam", "epicgames", "battlenet", "origin"],
                    "攻略/社区": ["ign.com", "gamespot", "gamefaqs", "metacritic"],
                },
            },
            {
                "name": "🏥 生活健康",
                "keywords": [
                    "dianping", "meituan", "health", "hospital", "trip",
                    "ctrip", "qunar", "yangsheng",
                ],
                "sub_categories": ["美食/外卖", "医疗/健康", "出行/旅游"],
                "sub_keywords": {
                    "美食/外卖": ["dianping", "meituan", "eleme"],
                    "医疗/健康": ["health", "hospital", "dingxiang"],
                    "出行/旅游": ["ctrip", "qunar", "mafengwo", "airbnb", "booking", "12306"],
                },
            },
            {
                "name": "📰 新闻资讯",
                "keywords": [
                    "news", "bbc", "cnn", "xinhua", "36kr",
                    "huxiu", "bloomberg", "reuters", "caixin",
                ],
                "sub_categories": ["综合新闻", "科技资讯", "财经资讯"],
                "sub_keywords": {
                    "综合新闻": ["news", "bbc", "cnn", "xinhua", "reuters"],
                    "科技资讯": ["36kr", "huxiu", "ithome", "solidot", "theverge"],
                    "财经资讯": ["bloomberg", "caixin", "cls.cn", "yicai"],
                },
            },
            {
                "name": "🏢 工作办公",
                "keywords": [
                    "jira", "confluence", "slack", "zoom", "office",
                    "trello", "asana", "notion", "feishu", "dingtalk",
                ],
                "sub_categories": ["项目管理", "协作沟通", "邮箱", "HR/考勤"],
                "sub_keywords": {
                    "项目管理": ["jira", "trello", "asana", "todoist"],
                    "协作沟通": ["slack", "feishu", "dingtalk", "wecom", "zoom", "teams"],
                    "邮箱": ["gmail", "outlook", "mail", "163.com", "qqmail"],
                    "HR/考勤": ["workday", "智联", "前程无忧"],
                },
            },
            {
                "name": "📖 参考工具",
                "keywords": [],
                "sub_categories": ["字典/翻译", "单位/换算", "天气/日历", "计算/工具"],
                "sub_keywords": {
                    "字典/翻译": ["dict", "dictionary", "translate", "translator", "翻译", "词典"],
                    "单位/换算": ["converter", "convert", "换算", "单位"],
                    "天气/日历": ["weather", "calendar", "天气", "日历", "农历"],
                    "计算/工具": ["calculator", "计算器", "timetool"],
                },
            },
            {
                "name": "🏠 居家生活",
                "keywords": [],
                "sub_categories": ["装修/家居", "食谱/美食", "宠物/园艺"],
                "sub_keywords": {
                    "装修/家居": ["装修", "家居", "宜家", "ikea", "家装"],
                    "食谱/美食": ["食谱", "下厨房", "菜谱", "cooking", "xiachufang"],
                    "宠物/园艺": ["养花", "园艺", "多肉", "宠物"],
                },
            },
            {
                "name": "📁 其他",
                "keywords": [],
                "sub_categories": ["未分类", "个人"],
            },
        ],
        "output": {
            "export_dir": "data/exports",
            "filename_pattern": "bookmark-{timestamp}.html",
            "excel_dir": "data/exports",
            "html_dir": "data/exports",
            "log_dir": "data/logs",
            "log_level": "INFO",
            "export_include_dead": False,
            "export_include_local": True,
        },
        "ui": {
            "theme": "light",
            "language": "zh_CN",
            "window_width": 1200,
            "window_height": 800,
        },
    }

    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self._config: dict = {}
        self._defaults = self.DEFAULT_CONFIG.copy()

    def load(self) -> dict:
        """加载配置文件，不存在则用默认值并创建"""
        if not self.config_path.exists():
            logger.info(f"配置文件不存在，创建默认: {self.config_path}")
            self._config = self._deep_copy(self._defaults)
            self.save()
            return self._config

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            # 深度合并：默认值打底，用户配置覆盖
            self._config = self._deep_merge(self._defaults, loaded)
            logger.info(f"配置加载成功: {self.config_path}")
        except Exception as e:
            logger.error(f"配置加载失败: {e}，使用默认配置")
            self._config = self._deep_copy(self._defaults)

        return self._config

    def save(self):
        """保存当前配置到 YAML 文件"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    self._config,
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                    indent=2,
                )
            logger.info(f"配置已保存: {self.config_path}")
        except Exception as e:
            logger.error(f"配置保存失败: {e}")
            raise

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        点分路径获取配置值
        例: config.get("proxy.custom.port", 7890)
        """
        keys = key_path.split(".")
        current = self._config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def set(self, key_path: str, value: Any):
        """点分路径设置配置值"""
        keys = key_path.split(".")
        current = self._config
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

    def get_all(self) -> dict:
        """返回完整配置副本"""
        return self._deep_copy(self._config)

    def update(self, new_config: dict):
        """合并更新配置"""
        self._config = self._deep_merge(self._config, new_config)

    def get_categories(self) -> list[dict]:
        """获取分类体系"""
        return self._config.get("categories", [])

    def set_categories(self, categories: list[dict]):
        """更新分类体系"""
        self._config["categories"] = categories

    def reset_to_defaults(self):
        """重置为默认配置"""
        self._config = self._deep_copy(self._defaults)
        self.save()
        logger.info("配置已重置为默认值")

    @staticmethod
    def _deep_merge(default: dict, override: dict) -> dict:
        """深度合并两个字典，override 优先"""
        result = dict(default)
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _deep_copy(obj):
        """深拷贝"""
        import copy
        return copy.deepcopy(obj)

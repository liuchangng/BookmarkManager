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
            "timeout": 60,
            "max_retries": 3,
            "concurrency": 5,
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "fallback_to_firecrawl": True,
        },
        "probe": {
            # 探活超时（秒）与误判容忍：网络不稳时加大超时/连续失败次数，避免误标失效
            "timeout": 10,
            "max_fail_confirm": 3,
        },
        "classification": {
            "ai_enabled": True,
            "ai_confidence_threshold": 0.5,
            "cache_enabled": True,
            "cache_dir": "data/cache",
            "allow_delete": True,
            "confirm_delete": True,
        },
        # 分类由 AI 自动生成（方案 A：全程自动化），无需维护分类/关键词配置
        "categories": [],
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
        "web": {
            "host": "127.0.0.1",
            "port": 8989,
            "auto_open_browser": True,
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

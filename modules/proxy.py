"""
proxy.py - 代理管理模块
统一管理所有网络请求的代理配置，提供界面开关
支持: 系统/VPN代理自动检测 + 自定义代理 + 开关控制 + 连通性测试
"""

import platform
import logging
import time
import os
from typing import Optional, Dict
from urllib.parse import urlencode

import httpx
import requests

from modules.config_manager import ConfigManager

logger = logging.getLogger("proxy")


class ProxyManager:
    """
    代理管理器

    优先级:
    1. 总开关 proxy.enabled == false → 全部不走代理
    2. 自定义代理 custom.enabled == true → 使用自定义
    3. 系统代理自动检测 auto_detect_system == true → 使用系统代理
    4. 以上都不满足 → 直连
    """

    def __init__(self, config: ConfigManager, secure_store=None):
        self.config = config
        self.secure_store = secure_store
        self._system_proxy: Optional[Dict[str, str]] = None
        self._last_test_result: Optional[Dict] = None

        # 启动时尝试检测系统代理
        if self.config.get("proxy.auto_detect_system", True):
            self._system_proxy = self.detect_system_proxy()
            if self._system_proxy:
                logger.info(f"检测到系统代理: {self._system_proxy.get('http', 'N/A')}")

    # ──────────────────────────────────────────────
    #  开关控制（界面绑定）
    # ──────────────────────────────────────────────

    def enable(self):
        """启用代理"""
        self.config.set("proxy.enabled", True)
        self.config.save()
        logger.info("代理已启用")

    def disable(self):
        """禁用代理"""
        self.config.set("proxy.enabled", False)
        self.config.save()
        logger.info("代理已禁用")

    def is_enabled(self) -> bool:
        """当前代理是否启用"""
        return self.config.get("proxy.enabled", False)

    def toggle(self) -> bool:
        """切换开关，返回新状态"""
        if self.is_enabled():
            self.disable()
            return False
        else:
            self.enable()
            return True

    # ──────────────────────────────────────────────
    #  代理获取
    # ──────────────────────────────────────────────

    def get_proxies(self) -> Optional[Dict[str, str]]:
        """
        返回 requests 兼容的 proxies dict
        未启用或无可用的代理 → 返回 None
        """
        if not self.is_enabled():
            return None

        # 优先自定义代理
        if self.config.get("proxy.custom.enabled", False):
            proxy_url = self._build_custom_proxy_url()
            if proxy_url:
                return {"http": proxy_url, "https": proxy_url}

        # 其次系统代理
        if self._system_proxy:
            return self._system_proxy

        return None

    def get_httpx_proxy(self) -> Optional[str]:
        """返回 httpx 格式的代理 URL 字符串"""
        proxies = self.get_proxies()
        if not proxies:
            return None
        # httpx 优先用 https 代理
        return proxies.get("https") or proxies.get("http")

    def get_playwright_proxy(self) -> Optional[Dict[str, str]]:
        """返回 Playwright/Scrapling 格式的代理配置"""
        if not self.is_enabled():
            return None

        if self.config.get("proxy.custom.enabled", False):
            return {
                "server": self._build_custom_proxy_url(),
                "username": self.config.get("proxy.custom.username", "") or None,
                "password": self.config.get("proxy.custom.password", "") or None,
            }

        # 系统代理转 Playwright 格式
        sys_proxy = self.get_proxies()
        if sys_proxy:
            url = sys_proxy.get("https") or sys_proxy.get("http")
            if url:
                return {"server": url}

        return None

    def _build_custom_proxy_url(self) -> Optional[str]:
        """构建自定义代理 URL"""
        host = self.config.get("proxy.custom.host", "")
        port = self.config.get("proxy.custom.port", 0)
        proxy_type = self.config.get("proxy.custom.type", "http")

        if not host or not port:
            return None

        # 处理带认证的代理
        username = self.config.get("proxy.custom.username", "")
        password = self.config.get("proxy.custom.password", "")

        if proxy_type == "socks5":
            scheme = "socks5h"  # socks5 with remote DNS
        else:
            scheme = "http"

        if username and password:
            return f"{scheme}://{username}:{password}@{host}:{port}"
        else:
            return f"{scheme}://{host}:{port}"

    # ──────────────────────────────────────────────
    #  系统代理检测
    # ──────────────────────────────────────────────

    def detect_system_proxy(self) -> Optional[Dict[str, str]]:
        """
        检测系统代理设置
        Windows: 读注册表
        macOS: 读 scutil
        Linux: 读环境变量
        """
        system = platform.system()

        if system == "Windows":
            return self._detect_windows_proxy()
        elif system == "Darwin":
            return self._detect_macos_proxy()
        else:
            return self._detect_linux_proxy()

    def _detect_windows_proxy(self) -> Optional[Dict[str, str]]:
        """从注册表读取 Windows 系统代理"""
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                # 检查是否启用代理
                try:
                    enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                except FileNotFoundError:
                    enabled = 0

                if not enabled:
                    # 检查是否使用自动配置 (PAC)
                    try:
                        pac_url, _ = winreg.QueryValueEx(key, "AutoConfigURL")
                        if pac_url:
                            logger.info(f"检测到 PAC 配置: {pac_url}（暂不支持自动解析）")
                    except FileNotFoundError:
                        pass
                    return None

                # 读取代理服务器
                try:
                    proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                except FileNotFoundError:
                    return None

                # ProxyServer 可能是 "host:port" 或 "http=host:port;https=host:port"
                if "=" in proxy_server:
                    proxies = {}
                    for part in proxy_server.split(";"):
                        scheme, addr = part.strip().split("=", 1)
                        proxies[scheme.strip()] = f"http://{addr.strip()}"
                    return proxies if proxies else None
                else:
                    proxy_url = f"http://{proxy_server}"
                    return {"http": proxy_url, "https": proxy_url}

        except ImportError:
            logger.debug("winreg 不可用（非 Windows 平台）")
        except Exception as e:
            logger.debug(f"读取系统代理失败: {e}")

        return None

    def _detect_macos_proxy(self) -> Optional[Dict[str, str]]:
        """从 scutil 读取 macOS 系统代理"""
        try:
            import subprocess
            result = subprocess.run(
                ["scutil", "--proxy"],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout

            enabled = "HTTPEnable : 1" in output
            if not enabled:
                return None

            proxies = {}
            for line in output.splitlines():
                line = line.strip()
                if line.startswith("HTTPProxy"):
                    host = line.split(": ")[1] if ": " in line else ""
                elif line.startswith("HTTPPort"):
                    port = line.split(": ")[1] if ": " in line else ""
                elif line.startswith("HTTPSProxy"):
                    https_host = line.split(": ")[1] if ": " in line else ""
                elif line.startswith("HTTPSPort"):
                    https_port = line.split(": ")[1] if ": " in line else ""

            if host and port:
                proxies["http"] = f"http://{host}:{port}"
            if https_host and https_port:
                proxies["https"] = f"http://{https_host}:{https_port}"
            elif "http" in proxies:
                proxies["https"] = proxies["http"]

            return proxies if proxies else None

        except Exception as e:
            logger.debug(f"检测 macOS 代理失败: {e}")
        return None

    def _detect_linux_proxy(self) -> Optional[Dict[str, str]]:
        """从环境变量读取 Linux 代理"""
        proxies = {}

        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy

        return proxies if proxies else None

    def detect_vpn(self) -> bool:
        """
        检测是否有 VPN 隧道连接
        通过检查网络适配器列表判断
        """
        system = platform.system()

        try:
            if system == "Windows":
                import subprocess
                result = subprocess.run(
                    ["ipconfig"], capture_output=True, text=True, timeout=5
                )
                # 检查 TAP/TUN 适配器
                vpn_keywords = ["tap", "tun", "vpn", "wireguard", "openvpn"]
                for line in result.stdout.lower().splitlines():
                    for kw in vpn_keywords:
                        if kw in line:
                            logger.info(f"检测到 VPN 适配器: {line.strip()}")
                            return True

            elif system == "Darwin" or system == "Linux":
                import subprocess
                result = subprocess.run(
                    ["ifconfig"], capture_output=True, text=True, timeout=5
                )
                vpn_keywords = ["utun", "tun", "tap", "wg", "wireguard"]
                for line in result.stdout.lower().splitlines():
                    for kw in vpn_keywords:
                        if kw in line.split(":")[0]:
                            logger.info(f"检测到 VPN 接口: {line.strip()}")
                            return True

        except Exception as e:
            logger.debug(f"VPN 检测失败: {e}")

        return False

    # ──────────────────────────────────────────────
    #  测试
    # ──────────────────────────────────────────────

    def test_connection(
        self,
        test_url: str = "https://www.google.com",
        timeout: int = 10
    ) -> Dict:
        """
        测试代理连通性
        返回: {"success": bool, "latency_ms": int, "ip": str, "error": str}
        """
        proxies = self.get_proxies()

        if not proxies and self.is_enabled():
            return {
                "success": False,
                "latency_ms": 0,
                "ip": "",
                "error": "代理已启用但未配置可用代理地址",
            }

        # 如果未启用代理，直接测试直连
        use_proxies = proxies if self.is_enabled() else None

        try:
            start = time.time()

            if use_proxies:
                # 用 httpx 走代理测试
                proxy_url = use_proxies.get("https") or use_proxies.get("http")
                with httpx.Client(proxy=proxy_url, timeout=timeout, follow_redirects=True) as client:
                    response = client.get(test_url)
                    response.raise_for_status()
                    # 尝试获取公网 IP
                    ip_response = client.get("https://api.ipify.org?format=json")
                    ip_data = ip_response.json()
                    public_ip = ip_data.get("ip", "unknown")
            else:
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    response = client.get(test_url)
                    response.raise_for_status()
                    ip_response = client.get("https://api.ipify.org?format=json")
                    ip_data = ip_response.json()
                    public_ip = ip_data.get("ip", "unknown")

            latency = int((time.time() - start) * 1000)

            result = {
                "success": True,
                "latency_ms": latency,
                "ip": public_ip,
                "error": "",
            }
            self._last_test_result = result
            logger.info(f"代理测试成功: IP={public_ip}, 延迟={latency}ms")
            return result

        except Exception as e:
            result = {
                "success": False,
                "latency_ms": 0,
                "ip": "",
                "error": str(e),
            }
            self._last_test_result = result
            logger.warning(f"代理测试失败: {e}")
            return result

    # ──────────────────────────────────────────────
    #  规则
    # ──────────────────────────────────────────────

    def should_bypass(self, url: str) -> bool:
        """判断某 URL 是否应绕过代理"""
        if not url:
            return False

        from urllib.parse import urlparse
        try:
            hostname = urlparse(url).hostname or ""
        except ValueError:
            return False

        bypass_list = self.config.get("proxy.bypass_domains", [])
        for domain in bypass_list:
            if domain in hostname:
                return True

        return False

    # ──────────────────────────────────────────────
    #  持久化
    # ──────────────────────────────────────────────

    def save_config(self):
        """将当前代理设置写回 config.yaml"""
        self.config.save()

    def load_config(self):
        """从 config.yaml 重新加载"""
        self.config.load()
        # 重新检测系统代理
        if self.config.get("proxy.auto_detect_system", True):
            self._system_proxy = self.detect_system_proxy()

    def get_status_info(self) -> Dict:
        """返回当前代理状态摘要（供 UI 显示）"""
        info = {
            "enabled": self.is_enabled(),
            "mode": "直连",
            "address": "",
            "vpn_detected": self.detect_vpn(),
            "last_test": self._last_test_result,
        }

        if self.is_enabled():
            if self.config.get("proxy.custom.enabled", False):
                info["mode"] = "自定义代理"
                info["address"] = f"{self.config.get('proxy.custom.host', '')}:{self.config.get('proxy.custom.port', '')}"
            elif self._system_proxy:
                info["mode"] = "系统代理(自动)"
                info["address"] = self._system_proxy.get("http", "已检测")

        return info

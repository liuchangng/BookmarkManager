"""
secure_store.py - 敏感信息加密存储
使用 Fernet (AES-128-CBC + HMAC) 加密，密钥基于机器指纹派生
"""

import os
import json
import hashlib
import logging
import platform
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

logger = logging.getLogger("secure_store")


class SecureStore:
    """
    管理所有敏感信息的本地加密存储
    存储位置: data/.secure/
    加密方式: Fernet (AES-128-CBC + HMAC-SHA256)
    密钥派生: 机器指纹 (主机名+MAC+用户名) → SHA-256 → 取前32字节 → Base64
    """

    SERVICES = ["deepseek", "firecrawl"]

    def __init__(self, store_dir: Path):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._key = self._derive_key()
        self._fernet = Fernet(self._key)
        logger.info(f"加密存储初始化: {self.store_dir}")

    def _derive_key(self) -> bytes:
        """
        基于机器指纹派生加密密钥
        组合: 主机名 + 主MAC地址 + 用户名 + 固定盐
        注意: 这不是军工级安全，目的是防止明文泄露和跨机器读取
        """
        salt = b"BookmarkManager_v1_Salt_2026"
        hostname = platform.node().encode()
        if not hostname:
            hostname = os.environ.get("COMPUTERNAME", b"unknown-host")
        username = os.environ.get("USERNAME", os.environ.get("USER", "")).encode()

        # 获取主网卡MAC地址
        mac = self._get_primary_mac().encode()

        fingerprint = salt + hostname + mac + username
        digest = hashlib.sha256(fingerprint).digest()  # 32 bytes
        # Fernet 需要 Base64 编码的 32-byte key
        import base64
        return base64.urlsafe_b64encode(digest)

    def _get_primary_mac(self) -> str:
        """获取主网卡 MAC 地址"""
        try:
            import uuid
            mac = uuid.getnode()
            if mac != 0:
                return ":".join(f"{(mac >> i) & 0xff:02x}" for i in range(40, -1, -8))
        except Exception:
            pass
        return "00:00:00:00:00:00"

    def save(self, service: str, value: str) -> bool:
        """
        加密保存某个服务的敏感值
        返回: 是否成功
        """
        if service not in self.SERVICES and not service.startswith("custom_"):
            logger.warning(f"未知服务: {service}，仅支持 {self.SERVICES}")
            # 仍然允许保存（扩展用），但记录警告

        try:
            encrypted = self._fernet.encrypt(value.encode("utf-8"))
            filepath = self.store_dir / f"{service}.enc"
            with open(filepath, "wb") as f:
                f.write(encrypted)
            logger.info(f"已加密保存: {service}")
            return True
        except Exception as e:
            logger.error(f"加密保存失败 [{service}]: {e}")
            return False

    def load(self, service: str) -> Optional[str]:
        """
        解密读取某个服务的敏感值
        返回: 明文值 或 None
        """
        filepath = self.store_dir / f"{service}.enc"
        if not filepath.exists():
            return None

        try:
            with open(filepath, "rb") as f:
                encrypted = f.read()
            decrypted = self._fernet.decrypt(encrypted)
            return decrypted.decode("utf-8")
        except Exception as e:
            logger.error(f"解密读取失败 [{service}]: {e}")
            return None

    def exists(self, service: str) -> bool:
        """检查某服务是否已配置"""
        return (self.store_dir / f"{service}.enc").exists()

    def delete(self, service: str) -> bool:
        """删除某服务的存储"""
        filepath = self.store_dir / f"{service}.enc"
        if filepath.exists():
            try:
                filepath.unlink()
                logger.info(f"已删除: {service}")
                return True
            except Exception as e:
                logger.error(f"删除失败 [{service}]: {e}")
                return False
        return False

    def list_configured(self) -> list[str]:
        """列出所有已配置的服务"""
        configured = []
        for f in self.store_dir.glob("*.enc"):
            configured.append(f.stem)
        return configured

    def export_for_backup(self, password: str) -> str:
        """
        用用户提供的密码加密导出所有密钥（备份用）
        返回: Base64 编码的导出字符串
        """
        import base64 as b64

        # 收集所有明文
        all_data = {}
        for f in self.store_dir.glob("*.enc"):
            service = f.stem
            value = self.load(service)
            if value:
                all_data[service] = value

        if not all_data:
            raise ValueError("没有可导出的配置")

        # 用密码派生密钥
        pwd_digest = hashlib.sha256(password.encode()).digest()
        pwd_key = b64.urlsafe_b64encode(pwd_digest)
        pwd_fernet = Fernet(pwd_key)

        json_data = json.dumps(all_data, ensure_ascii=False).encode("utf-8")
        encrypted = pwd_fernet.encrypt(json_data)
        return b64.b64encode(encrypted).decode("ascii")

    def import_from_backup(self, backup_str: str, password: str) -> int:
        """
        用密码解密导入备份
        返回: 成功导入的服务数量
        """
        import base64 as b64

        encrypted = b64.b64decode(backup_str.encode("ascii"))
        pwd_digest = hashlib.sha256(password.encode()).digest()
        pwd_key = b64.urlsafe_b64encode(pwd_digest)
        pwd_fernet = Fernet(pwd_key)

        decrypted = pwd_fernet.decrypt(encrypted)
        all_data = json.loads(decrypted.decode("utf-8"))

        count = 0
        for service, value in all_data.items():
            if self.save(service, value):
                count += 1

        return count

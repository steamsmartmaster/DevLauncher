import json
import os
import logging
from pathlib import Path
from typing import Optional

import minecraft_launcher_lib

logger = logging.getLogger("DevLauncher")


class OfflineUser:
    """Offline mode user data"""
    def __init__(self, username: str):
        import uuid
        self.name = username
        self.id = str(uuid.uuid5(uuid.NAMESPACE_DNS, username))
        self.access_token = "offline_token"
        self.refresh_token = ""

    def to_dict(self):
        return {
            "name": self.name,
            "id": self.id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token
        }


class AuthManager:
    """Handle Microsoft authentication flow"""

    def __init__(self, client_id: str, redirect_url: str = "http://localhost:8080"):
        self.client_id = client_id
        self.redirect_url = redirect_url
        self._login_data: Optional[dict] = None
        self._code_verifier: Optional[str] = None
        self._state: Optional[str] = None
        self._data_dir = Path.home() / ".mc-launcher"
        self._data_file = self._data_dir / "auth.json"
        logger.info(f"AuthManager 初始化, 数据目录: {self._data_dir}")

    def get_login_url(self) -> tuple[str, str, str]:
        """Generate secure login URL and return (url, state, code_verifier)"""
        url, state, code_verifier = minecraft_launcher_lib.microsoft_account.get_secure_login_data(
            self.client_id, self.redirect_url
        )
        self._state = state
        self._code_verifier = code_verifier
        return url, state, code_verifier

    def parse_auth_code(self, callback_url: str) -> str:
        """Parse auth code from callback URL"""
        if self._state is None:
            raise ValueError("No state found. Call get_login_url first.")
        return minecraft_launcher_lib.microsoft_account.parse_auth_code_url(callback_url, self._state)

    def complete_login(self, auth_code: str) -> dict:
        """Complete the login process and return user data"""
        try:
            self._login_data = minecraft_launcher_lib.microsoft_account.complete_login(
                self.client_id, None, self.redirect_url, auth_code, self._code_verifier
            )
        except KeyError as e:
            logger.error(f"complete_login 失败 (KeyError: {e}) - Azure 应用配置可能不正确")
            raise Exception(
                "Microsoft 登录失败: Azure 应用未正确配置。\n"
                "请检查:\n"
                "1. Azure 应用注册中已启用「允许公共客户端流」\n"
                "2. 重定向 URI 设置为 http://localhost:8080\n"
                "3. API 权限已获批准"
            )
        except Exception as e:
            logger.error(f"complete_login 失败: {e}")
            raise

        self._save_login_data()
        return self._login_data

    def refresh_login(self, refresh_token: str) -> dict:
        """Refresh an existing login"""
        self._login_data = minecraft_launcher_lib.microsoft_account.complete_refresh(
            self.client_id, None, self.redirect_url, refresh_token
        )
        self._save_login_data()
        return self._login_data

    def get_login_data(self) -> Optional[dict]:
        """Get current login data"""
        if self._login_data is None:
            self._load_login_data()
        return self._login_data

    def logout(self):
        """Clear login data"""
        logger.info("用户登出, 清除登录数据")
        self._login_data = None
        self._clear_saved_data()

    def _save_login_data(self):
        """Save login data to file"""
        if self._login_data:
            try:
                self._data_dir.mkdir(exist_ok=True)
                with open(self._data_file, "w", encoding='utf-8') as f:
                    json.dump(self._login_data, f, indent=2, ensure_ascii=False)
                logger.info(f"登录数据已保存: {self._data_file}")
            except Exception as e:
                logger.error(f"保存登录数据失败: {e}")

    def _load_login_data(self) -> bool:
        """Load login data from file"""
        try:
            if self._data_file.exists():
                with open(self._data_file, "r", encoding='utf-8') as f:
                    self._login_data = json.load(f)
                logger.info(f"登录数据已加载: {self._login_data.get('name', 'unknown')}")
                return True
            else:
                logger.info("登录数据文件不存在")
        except Exception as e:
            logger.error(f"加载登录数据失败: {e}")
        return False

    def _clear_saved_data(self):
        """Clear saved login data"""
        try:
            if self._data_file.exists():
                self._data_file.unlink()
                logger.info("登录数据已删除")
        except Exception as e:
            logger.error(f"删除登录数据失败: {e}")

    def offline_login(self, username: str) -> dict:
        """Login with offline mode (no Microsoft account needed)"""
        logger.info(f"离线登录: {username}")
        user = OfflineUser(username)
        self._login_data = user.to_dict()
        self._save_login_data()
        return self._login_data

    @property
    def is_logged_in(self) -> bool:
        """Check if user is logged in"""
        return self.get_login_data() is not None

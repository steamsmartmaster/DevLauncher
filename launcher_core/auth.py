import logging
from typing import Optional

import minecraft_launcher_lib

from launcher_core.accounts import AccountStore

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

    def __init__(self, client_id: str, redirect_url: str = "http://localhost:8080",
                 store: Optional[AccountStore] = None):
        self.client_id = client_id
        self.redirect_url = redirect_url
        self.store: AccountStore = store if store is not None else AccountStore()
        self._code_verifier: Optional[str] = None
        self._state: Optional[str] = None
        try:
            self.store.migrate_legacy()
        except Exception:
            # I-3: 迁移失败不阻断启动 (accounts.json 不可写时本来也写不了)
            logger.error("旧账号数据迁移失败, 已跳过", exc_info=True)
        logger.info(f"AuthManager 初始化, 数据目录: {self.store.data_dir}")

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
            login_data = minecraft_launcher_lib.microsoft_account.complete_login(
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

        self.store.add(login_data, "microsoft")
        return login_data

    def refresh_login(self, refresh_token: str) -> dict:
        """Refresh an existing login"""
        if self.store.current_id() is None:
            logger.warning("refresh_login 失败: 未登录")
            raise RuntimeError("未登录，无法刷新令牌")
        try:
            new_data = minecraft_launcher_lib.microsoft_account.complete_refresh(
                self.client_id, None, self.redirect_url, refresh_token
            )
        except Exception as e:
            logger.error(f"refresh_login 失败: {e}", exc_info=True)
            raise
        self.store.update_data(self.store.current_id(), new_data)
        return new_data

    def get_login_data(self) -> Optional[dict]:
        """Get current login data"""
        return self.store.current()

    def logout(self):
        """Logout user: 取消选中当前账号（账号保留，删除是账户页独立功能）"""
        logger.info("用户登出, 取消选中当前账号")
        self.store.deselect()

    def offline_login(self, username: str) -> dict:
        """Login with offline mode (no Microsoft account needed)"""
        if not username.strip():
            raise ValueError("用户名不能为空")
        logger.info(f"离线登录: {username}")
        user = OfflineUser(username)
        data = user.to_dict()
        self.store.add(data, "offline")
        return data

    @property
    def is_logged_in(self) -> bool:
        """Check if user is logged in"""
        return self.store.current() is not None

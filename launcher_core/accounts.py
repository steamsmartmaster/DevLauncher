"""多账号持久化 (accounts.json) + 旧版 auth.json 迁移."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid as uuid_mod
from pathlib import Path

logger = logging.getLogger("DevLauncher")


class AccountStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else Path.home() / ".mc-launcher"
        self._current_id: str | None = None
        self._accounts: list[dict] = []
        self._load()

    # ---------------- 文件 ----------------

    @property
    def accounts_file(self) -> Path:
        return self.data_dir / "accounts.json"

    @property
    def legacy_file(self) -> Path:
        return self.data_dir / "auth.json"

    def _load(self) -> None:
        if not self.accounts_file.exists():
            return
        try:
            raw = self.accounts_file.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("accounts.json 读取失败: %s", e)
            return
        try:
            payload = json.loads(raw)
        except ValueError as e:
            logger.warning("accounts.json 解析失败: %s", e)
            return
        if not isinstance(payload, dict):
            logger.warning("accounts.json 结构非法(非 dict): %r", type(payload).__name__)
            return
        self._current_id = payload.get("current_id")
        accounts = payload.get("accounts")
        if not isinstance(accounts, list):
            self._accounts = []
            return
        valid: list[dict] = []
        for item in accounts:
            if (
                isinstance(item, dict)
                and "id" in item
                and "type" in item
                and "data" in item
                and isinstance(item["data"], dict)
            ):
                if "lastUsed" in item:
                    item["lastUsed"] = self._coerce_last_used(item["lastUsed"])
                valid.append(item)
            else:
                logger.warning("剔除非法账号条目: %r", item)
        self._accounts = valid

    def _save(self) -> None:
        payload = {"current_id": self._current_id, "accounts": self._accounts}
        tmp = self.data_dir / "accounts.json.tmp"
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.accounts_file)
        except (OSError, TypeError, ValueError) as e:
            logger.error("accounts.json 写入失败: %s", e, exc_info=True)
            raise

    def _now(self) -> float:
        now = time.time()
        for account in self._accounts:
            last = account.get("lastUsed", 0.0)
            if last >= now:
                now = last + 1e-6
        return now

    @staticmethod
    def _coerce_last_used(value) -> float:
        """lastUsed 归一化为 float；float 化失败（手改文件）即 0.0。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    # ---------------- 内部 ----------------

    def _find(self, account_id) -> dict | None:
        for account in self._accounts:
            if account.get("id") == account_id:
                return account
        return None

    def _summary(self, account: dict) -> dict:
        return {
            "id": account["id"],
            "type": account["type"],
            "name": account.get("name", ""),
            "uuid": account.get("uuid", ""),
            "lastUsed": account.get("lastUsed", 0.0),
            "isCurrent": account.get("id") == self._current_id,
        }

    def _record(self, data: dict, type: str, created: float) -> dict:
        return {
            "id": str(uuid_mod.uuid4()),
            "type": type,
            "name": data.get("name", ""),
            "uuid": data.get("id", ""),
            "data": dict(data),
            "created": created,
            "lastUsed": created,
        }

    # ---------------- API ----------------

    def list(self) -> list[dict]:
        ordered = sorted(self._accounts, key=lambda a: a.get("lastUsed", 0.0), reverse=True)
        return [self._summary(a) for a in ordered]

    def get(self, account_id) -> dict | None:
        account = self._find(account_id)
        return None if account is None else self._summary(account)

    def current(self) -> dict | None:
        account = self._find(self._current_id)
        return None if account is None else account.get("data")

    def current_id(self) -> str | None:
        if self._current_id is None or self._find(self._current_id) is None:
            return None
        return self._current_id

    def deselect(self) -> None:
        """取消选中当前账号（登出语义）：指针置空，账号全部保留。"""
        if self._current_id is None:
            return
        self._current_id = None
        self._save()

    def add(self, data: dict, type: str) -> dict:
        if type not in ("offline", "microsoft"):
            raise ValueError(f"invalid account type: {type}")
        now = self._now()
        existing = None
        if type == "microsoft":
            for account in self._accounts:
                if account.get("type") == "microsoft" and account.get("uuid") == data.get("id", ""):
                    existing = account
                    break
        else:
            for account in self._accounts:
                if account.get("type") == "offline" and account.get("name") == data.get("name", ""):
                    existing = account
                    break

        if existing is not None:
            existing["data"] = dict(data)
            existing["name"] = data.get("name", "")
            existing["uuid"] = data.get("id", "")
            existing["lastUsed"] = now
            record = existing
        else:
            record = self._record(data, type, now)
            self._accounts.append(record)

        self._current_id = record["id"]
        self._save()
        return self._summary(record)

    def switch(self, account_id) -> dict | None:
        record = self._find(account_id)
        if record is None:
            return None
        self._current_id = record["id"]
        record["lastUsed"] = self._now()
        self._save()
        return self._summary(record)

    def remove(self, account_id) -> None:
        record = self._find(account_id)
        if record is None:
            return
        self._accounts = [a for a in self._accounts if a.get("id") != account_id]
        if self._current_id == account_id:
            if self._accounts:
                newest = max(self._accounts, key=lambda a: a.get("lastUsed", 0.0))
                self._current_id = newest["id"]
            else:
                self._current_id = None
        self._save()

    def update_data(self, account_id, data) -> None:
        record = self._find(account_id)
        if record is None:
            return
        record["data"] = dict(data)
        record["name"] = data.get("name", "")
        record["uuid"] = data.get("id", "")
        self._save()

    def migrate_legacy(self) -> bool:
        if self.accounts_file.exists():
            return False
        if not self.legacy_file.exists():
            return False
        try:
            data = json.loads(self.legacy_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("auth.json 读取/解析失败, 跳过迁移: %s", e)
            return False
        if not isinstance(data, dict):
            logger.warning("auth.json 结构非法(非 dict), 跳过迁移: %r", type(data).__name__)
            return False
        account_type = "offline" if data.get("access_token") == "offline_token" else "microsoft"
        record = self._record(data, account_type, self._now())
        self._accounts.append(record)
        self._current_id = record["id"]
        self._save()
        return True

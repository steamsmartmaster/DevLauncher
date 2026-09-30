"""AccountStore 多账号持久化 + 迁移 (TDD RED/GREEN)

- add/list/get/current/switch/remove/update_data 摘要与持久化语义
- 摘要绝不含 data/令牌 (json.dumps 全文搜索验证)
- migrate_legacy 从 auth.json 导入首个账号
"""
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from launcher_core.accounts import AccountStore  # noqa: E402
from launcher_core.auth import AuthManager  # noqa: E402


def offline_data(name="Steve", token="offline_token", uid="uuid-steve") -> dict:
    return {
        "name": name,
        "id": uid,
        "access_token": token,
        "refresh_token": "",
    }


def ms_data(name="Alex", uid="ms-uuid-1", token="ms-access-token") -> dict:
    return {
        "name": name,
        "id": uid,
        "access_token": token,
        "refresh_token": "ms-refresh",
    }


def store(tmp_path) -> AccountStore:
    return AccountStore(Path(tmp_path))


def summary_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---------------- 1. add 离线 + 摘要无令牌 ----------------

def test_add_offline_returns_summary_without_token(tmp_path):
    s = store(tmp_path)
    summary = s.add(offline_data(), "offline")

    assert "data" not in summary
    assert "access_token" not in summary_json(summary)
    assert summary["type"] == "offline"
    assert summary["name"] == "Steve"
    assert summary["uuid"] == "uuid-steve"
    assert summary["isCurrent"] is True

    listed = s.list()
    assert len(listed) == 1
    assert listed[0]["isCurrent"] is True
    assert "data" not in listed[0]
    dumped = summary_json(listed)
    assert "access_token" not in dumped
    assert "offline_token" not in dumped


# ---------------- 2. current() 完整 data ----------------

def test_current_returns_full_data_with_token(tmp_path):
    s = store(tmp_path)
    data = offline_data()
    s.add(data, "offline")

    got = s.current()
    assert got is not None
    assert got["access_token"] == "offline_token"
    assert got["name"] == "Steve"
    assert got["id"] == "uuid-steve"


# ---------------- 3. 第二个账号成为 current，按 lastUsed 降序 ----------------

def test_second_account_becomes_current_and_list_sorted_desc(tmp_path):
    s = store(tmp_path)
    first = s.add(offline_data("Steve"), "offline")
    second = s.add(offline_data("Alex", uid="uuid-alex"), "offline")

    assert s.current_id() == second["id"]
    assert s.current_id() != first["id"]

    listed = s.list()
    assert [a["id"] for a in listed] == [second["id"], first["id"]]
    assert listed[0]["lastUsed"] >= listed[1]["lastUsed"]
    assert sum(1 for a in listed if a["isCurrent"]) == 1


# ---------------- 4. switch 更新 current_id + lastUsed + 排序 ----------------

def test_switch_updates_current_id_last_used_and_order(tmp_path):
    s = store(tmp_path)
    first = s.add(offline_data("Steve"), "offline")
    second = s.add(offline_data("Alex", uid="uuid-alex"), "offline")

    before_first_used = s.list()[1]["lastUsed"]
    returned = s.switch(first["id"])

    assert returned is not None
    assert returned["id"] == first["id"]
    assert returned["isCurrent"] is True
    assert s.current_id() == first["id"]
    assert s.current()["name"] == "Steve"

    listed = s.list()
    assert listed[0]["id"] == first["id"]
    assert listed[0]["lastUsed"] > before_first_used
    assert listed[1]["id"] == second["id"]


# ---------------- 5. switch 不存在 → None 且不改指针 ----------------

def test_switch_unknown_id_returns_none_and_keeps_current(tmp_path):
    s = store(tmp_path)
    first = s.add(offline_data("Steve"), "offline")
    s.add(offline_data("Alex", uid="uuid-alex"), "offline")
    before = s.current_id()

    assert s.switch("no-such-id") is None
    assert s.current_id() == before


# ---------------- 6. 同名同类型离线去重覆盖 ----------------

def test_offline_same_name_dedupes_and_overwrites_data(tmp_path):
    s = store(tmp_path)
    s.add(offline_data("Steve", token="token-A"), "offline")
    s.add(offline_data("Steve", token="token-B"), "offline")

    assert len(s.list()) == 1
    assert s.current()["access_token"] == "token-B"
    assert (Path(tmp_path) / "accounts.json").exists()


# ---------------- 7. 微软按 data["id"] 去重 ----------------

def test_microsoft_dedupe_by_data_id(tmp_path):
    s = store(tmp_path)
    s.add(ms_data("Alex", uid="ms-1"), "microsoft")
    s.add(ms_data("Alex", uid="ms-1", token="refreshed"), "microsoft")
    assert len(s.list()) == 1
    assert s.current()["access_token"] == "refreshed"

    s.add(ms_data("Alex", uid="ms-2"), "microsoft")
    assert len(s.list()) == 2
    ids = {a["uuid"] for a in s.list()}
    assert ids == {"ms-1", "ms-2"}


# ---------------- 8. remove 当前账号 → 回退 lastUsed 最新者 ----------------

def test_remove_current_falls_back_to_most_recently_used(tmp_path):
    s = store(tmp_path)
    a = s.add(offline_data("Steve"), "offline")
    b = s.add(offline_data("Alex", uid="uuid-alex"), "offline")
    c = s.add(offline_data("Notch", uid="uuid-notch"), "offline")
    # lastUsed 降序: c > b > a, current = c
    assert s.current_id() == c["id"]
    assert [x["id"] for x in s.list()] == [c["id"], b["id"], a["id"]]

    s.remove(c["id"])

    # 回退到剩余中 lastUsed 最新者 = b (而非首个插入的 a)
    assert s.current_id() == b["id"]
    assert s.current()["name"] == "Alex"
    remaining = {x["id"] for x in s.list()}
    assert remaining == {a["id"], b["id"]}


# ---------------- 9. remove 唯一账号 → 全空 ----------------

def test_remove_last_account_clears_current(tmp_path):
    s = store(tmp_path)
    only = s.add(offline_data("Steve"), "offline")
    s.remove(only["id"])

    assert s.current_id() is None
    assert s.current() is None
    assert s.list() == []
    on_disk = json.loads((Path(tmp_path) / "accounts.json").read_text(encoding="utf-8"))
    assert on_disk == {"current_id": None, "accounts": []}


# ---------------- 10. remove 不存在 → 静默 ----------------

def test_remove_unknown_id_is_silent(tmp_path):
    s = store(tmp_path)
    kept = s.add(offline_data("Steve"), "offline")
    s.remove("no-such-id")

    assert s.current_id() == kept["id"]
    assert len(s.list()) == 1


# ---------------- 11. 持久化往返 ----------------

def test_persistence_roundtrip_across_instances(tmp_path):
    s1 = store(tmp_path)
    a = s1.add(offline_data("Steve"), "offline")
    b = s1.add(offline_data("Alex", uid="uuid-alex"), "offline")
    s1.switch(a["id"])

    s2 = store(tmp_path)
    assert s2.current_id() == s1.current_id() == a["id"]
    assert s2.list() == s1.list()
    assert s2.current()["name"] == "Steve"
    assert len(s2.list()) == 2
    assert {x["id"] for x in s2.list()} == {a["id"], b["id"]}


# ---------------- 12. migrate_legacy 离线 ----------------

def test_migrate_legacy_offline_auth_json(tmp_path):
    legacy = offline_data("OldPlayer", uid="uuid-old")
    (Path(tmp_path) / "auth.json").write_text(
        json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
    )

    s = store(tmp_path)
    assert s.migrate_legacy() is True

    listed = s.list()
    assert len(listed) == 1
    assert listed[0]["type"] == "offline"
    assert listed[0]["isCurrent"] is True
    assert s.current_id() == listed[0]["id"]
    assert s.current()["access_token"] == "offline_token"
    assert (Path(tmp_path) / "auth.json").exists()  # 保留不删

    assert s.migrate_legacy() is False  # 已迁移 → False


# ---------------- 13. migrate_legacy 微软 ----------------

def test_migrate_legacy_microsoft_auth_json(tmp_path):
    legacy = ms_data("OldPlayer", uid="uuid-old")
    (Path(tmp_path) / "auth.json").write_text(
        json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
    )

    s = store(tmp_path)
    assert s.migrate_legacy() is True

    assert len(s.list()) == 1
    assert s.list()[0]["type"] == "microsoft"
    assert s.current()["access_token"] == "ms-access-token"


# ---------------- 14. accounts.json 已存在 → 不迁移 ----------------

def test_migrate_legacy_skips_when_accounts_json_exists(tmp_path):
    (Path(tmp_path) / "auth.json").write_text(
        json.dumps(offline_data("OldPlayer")), encoding="utf-8"
    )
    s = store(tmp_path)
    s.add(offline_data("Steve"), "offline")  # 生成 accounts.json

    s2 = store(tmp_path)
    assert s2.migrate_legacy() is False
    assert len(s2.list()) == 1
    assert s2.list()[0]["name"] == "Steve"


# ---------------- 15. update_data 回写 ----------------

def test_update_data_rewrites_account_data(tmp_path):
    s = store(tmp_path)
    added = s.add(offline_data("Steve", token="stale"), "offline")
    s.update_data(
        added["id"],
        offline_data("Steve", token="fresh-token", uid="uuid-steve-2"),
    )

    assert s.current()["access_token"] == "fresh-token"
    assert s.current()["id"] == "uuid-steve-2"
    assert s.get(added["id"])["name"] == "Steve"
    assert s.get(added["id"])["uuid"] == "uuid-steve-2"
    assert "data" not in s.get(added["id"])

    # 持久化后仍可见
    s2 = store(tmp_path)
    assert s2.current()["access_token"] == "fresh-token"

    # 不存在的 id 静默
    s.update_data("no-such-id", offline_data())
    assert s.current_id() == added["id"]


# ---------------- 16. add 非法 type → ValueError（不落盘） ----------------

def test_add_rejects_invalid_type(tmp_path):
    s = store(tmp_path)

    with pytest.raises(ValueError):
        s.add(offline_data("Steve"), "weird-type")

    # 校验发生在任何落盘/去重之前：store 保持空且未生成 accounts.json
    assert s.list() == []
    assert s.current_id() is None
    assert not (Path(tmp_path) / "accounts.json").exists()


# ---------------- 17. S1: 损坏 auth.json → 迁移安全返回 False ----------------

def test_migrate_legacy_broken_auth_json_is_safe(tmp_path):
    (Path(tmp_path) / "auth.json").write_text("{broken", encoding="utf-8")

    s = store(tmp_path)
    assert s.migrate_legacy() is False  # 不抛 JSONDecodeError

    assert s.list() == []
    assert s.current_id() is None
    assert not (Path(tmp_path) / "accounts.json").exists()

    # store 仍可用
    added = s.add(offline_data("Steve"), "offline")
    assert added["name"] == "Steve"
    assert s.current_id() == added["id"]
    assert len(s.list()) == 1


# ---------------- 18. M1: 非法 accounts 元素被剔除 + 悬空 current_id ----------------

def test_load_drops_invalid_elements_and_dangling_current(tmp_path):
    payload = {
        "current_id": "ghost-id",
        "accounts": [
            1,
            "bad",
            {"name": "only"},
            {
                "id": "ok-1",
                "type": "offline",
                "name": "Steve",
                "uuid": "u1",
                "data": {"name": "Steve", "id": "u1", "access_token": "offline_token"},
                "created": 1.0,
                "lastUsed": 2.0,
            },
        ],
    }
    (Path(tmp_path) / "accounts.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    s = store(tmp_path)

    listed = s.list()  # 不抛 AttributeError/KeyError
    assert [a["id"] for a in listed] == ["ok-1"]  # 非法项剔除、合法项保留
    assert s.current_id() is None  # 悬空 current 视同 None
    assert s.current() is None
    assert s.get("ghost-id") is None
    assert s.get("ok-1")["name"] == "Steve"
    assert all("data" not in a for a in listed)


# ---------------- 19. M2: 损坏 accounts.json 记录 WARNING ----------------

def test_corrupt_accounts_json_logs_warning(tmp_path, caplog):
    (Path(tmp_path) / "accounts.json").write_text("{broken", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="DevLauncher"):
        s = store(tmp_path)

    assert s.list() == []
    assert s.current_id() is None
    warnings = [r for r in caplog.records if r.name == "DevLauncher"]
    assert any(r.levelno == logging.WARNING for r in warnings), "缺少 WARNING 日志"


# ================= Task 2: AuthManager 接入 AccountStore =================

def make_auth(tmp_path) -> AuthManager:
    return AuthManager("test-client-id", store=AccountStore(Path(tmp_path)))


def legacy_auth_json(name="OldPlayer", uid="uuid-old") -> dict:
    return {
        "name": name,
        "id": uid,
        "access_token": "offline_token",
        "refresh_token": "",
    }


# ---------------- 20. offline_login 入库 + 成为 current + 不写 auth.json ----------------

def test_offline_login_stores_account_and_becomes_current(tmp_path):
    auth = make_auth(tmp_path)
    assert auth.is_logged_in is False

    data = auth.offline_login("Steve")

    assert data["name"] == "Steve"
    assert auth.get_login_data()["name"] == "Steve"
    assert auth.get_login_data()["access_token"] == "offline_token"

    listed = AccountStore(Path(tmp_path)).list()
    assert len(listed) == 1
    assert listed[0]["type"] == "offline"
    assert listed[0]["name"] == "Steve"
    assert listed[0]["isCurrent"] is True
    assert (Path(tmp_path) / "accounts.json").exists()
    assert not (Path(tmp_path) / "auth.json").exists()  # 不得再写 auth.json


# ---------------- 21. 连续不同名 → 2 条且 current 为最后一个 ----------------

def test_offline_login_two_distinct_names_keeps_two_accounts(tmp_path):
    auth = make_auth(tmp_path)
    auth.offline_login("Steve")
    auth.offline_login("Alex")

    listed = AccountStore(Path(tmp_path)).list()
    assert len(listed) == 2
    assert AccountStore(Path(tmp_path)).current()["name"] == "Alex"
    assert sum(1 for a in listed if a["isCurrent"]) == 1
    assert auth.get_login_data()["name"] == "Alex"


# ---------------- 22. 同名两次 → 覆盖仍 1 条 ----------------

def test_offline_login_same_name_twice_stays_single_account(tmp_path):
    auth = make_auth(tmp_path)
    auth.offline_login("Steve")
    auth.offline_login("Steve")

    store = AccountStore(Path(tmp_path))
    assert len(store.list()) == 1
    assert store.current()["name"] == "Steve"
    assert store.list()[0]["isCurrent"] is True
    assert auth.get_login_data()["name"] == "Steve"


# ---------------- 23. 构造 AuthManager 时自动迁移 legacy auth.json ----------------

def test_auth_manager_ctor_migrates_legacy_auth_json(tmp_path):
    (Path(tmp_path) / "auth.json").write_text(
        json.dumps(legacy_auth_json(), ensure_ascii=False), encoding="utf-8"
    )

    auth = make_auth(tmp_path)

    assert auth.get_login_data()["name"] == "OldPlayer"
    assert auth.get_login_data()["access_token"] == "offline_token"
    assert auth.is_logged_in is True

    accounts_file = Path(tmp_path) / "accounts.json"
    assert accounts_file.exists()
    on_disk = json.loads(accounts_file.read_text(encoding="utf-8"))
    assert len(on_disk["accounts"]) == 1
    assert on_disk["accounts"][0]["type"] == "offline"
    assert on_disk["accounts"][0]["name"] == "OldPlayer"
    assert on_disk["current_id"] == on_disk["accounts"][0]["id"]
    assert (Path(tmp_path) / "auth.json").exists()  # 迁移保留旧文件


# ---------------- 24. logout = 取消选中（产品决策: 登出 ≠ 删除账号） ----------------
# 语义变更: 原为 remove(当前) + 指针回退, 现改为 deselect(); 仅本用例按新语义更新

def test_logout_deselects_current_and_keeps_all_accounts(tmp_path):
    auth = make_auth(tmp_path)
    auth.offline_login("Steve")
    auth.offline_login("Alex")
    assert auth.get_login_data()["name"] == "Alex"

    auth.logout()

    # 取消选中: 指针清空, 账号一个不删
    assert auth.get_login_data() is None
    assert auth.is_logged_in is False
    assert AccountStore(Path(tmp_path)).current_id() is None

    store = AccountStore(Path(tmp_path))
    assert len(store.list()) == 2
    assert {a["name"] for a in store.list()} == {"Steve", "Alex"}
    assert all(a["isCurrent"] is False for a in store.list())

    # 再 switch() 可切回
    steve_id = next(a["id"] for a in store.list() if a["name"] == "Steve")
    auth.store.switch(steve_id)
    assert auth.get_login_data()["name"] == "Steve"
    assert auth.is_logged_in is True

    # 再次 logout 仍幂等
    auth.logout()
    assert auth.get_login_data() is None
    assert len(AccountStore(Path(tmp_path)).list()) == 2


# ---------------- 25. refresh_login 回写当前账号 data ----------------

def test_refresh_login_writes_back_new_token(tmp_path, monkeypatch):
    s = AccountStore(Path(tmp_path))
    s.add(ms_data("Alex", uid="ms-uuid-1"), "microsoft")
    auth = AuthManager("test-client-id", store=s)

    new_data = {
        "name": "Alex",
        "id": "ms-uuid-1",
        "access_token": "new",
        "refresh_token": "ms-refresh-2",
    }
    monkeypatch.setattr(
        "minecraft_launcher_lib.microsoft_account.complete_refresh",
        lambda client_id, token_store, redirect_url, refresh_token: dict(new_data),
    )

    returned = auth.refresh_login("ms-refresh")

    assert returned["access_token"] == "new"
    assert s.current()["access_token"] == "new"
    assert s.current()["refresh_token"] == "ms-refresh-2"
    assert len(s.list()) == 1  # 回写而非新增

    reloaded = AccountStore(Path(tmp_path))
    assert reloaded.current()["access_token"] == "new"
    assert reloaded.current_id() == s.current_id()


# ---------------- 26. complete_login 结果入库为微软账号 ----------------

def test_complete_login_stores_microsoft_account(tmp_path, monkeypatch):
    auth = make_auth(tmp_path)
    auth._code_verifier = "test-verifier"
    payload = {
        "name": "Alex",
        "id": "ms-uuid-1",
        "access_token": "ms-access-token",
        "refresh_token": "ms-refresh",
    }
    monkeypatch.setattr(
        "minecraft_launcher_lib.microsoft_account.complete_login",
        lambda client_id, token_store, redirect_url, auth_code, code_verifier: dict(payload),
    )

    out = auth.complete_login("some-auth-code")

    assert out["access_token"] == "ms-access-token"
    assert auth.get_login_data()["name"] == "Alex"

    store = AccountStore(Path(tmp_path))
    listed = store.list()
    assert len(listed) == 1
    assert listed[0]["type"] == "microsoft"
    assert listed[0]["isCurrent"] is True
    assert store.current()["refresh_token"] == "ms-refresh"
    assert not (Path(tmp_path) / "auth.json").exists()


# ---------------- 27. is_logged_in 真/假两态 ----------------

def test_is_logged_in_true_and_false(tmp_path):
    auth = make_auth(tmp_path)

    assert auth.is_logged_in is False
    assert auth.get_login_data() is None

    auth.offline_login("Steve")
    assert auth.is_logged_in is True

    auth.logout()
    assert auth.is_logged_in is False


# ================= 质量审查: A/B/C/D =================

# ---------------- 28. A: store.deselect 保留全部账号 + 持久化 + 可切回 ----------------

def test_deselect_keeps_all_accounts_persists_and_switch_back(tmp_path):
    s = store(tmp_path)
    steve = s.add(offline_data("Steve"), "offline")
    s.add(offline_data("Alex", uid="uuid-alex"), "offline")
    before_ids = [x["id"] for x in s.list()]

    s.deselect()

    assert s.current_id() is None
    assert s.current() is None
    after = s.list()
    assert [x["id"] for x in after] == before_ids
    assert len(after) == 2
    assert all(x["isCurrent"] is False for x in after)

    # 持久化到新实例
    reloaded = AccountStore(Path(tmp_path))
    assert reloaded.current_id() is None
    assert reloaded.current() is None
    assert [x["id"] for x in reloaded.list()] == before_ids
    assert len(reloaded.list()) == 2

    # deselect 后仍可 switch 切回, 并持久化
    assert reloaded.switch(steve["id"]) is not None
    assert reloaded.current()["name"] == "Steve"
    assert AccountStore(Path(tmp_path)).current()["name"] == "Steve"


# ---------------- 29. A: 空 store / 已无 current 时 deselect 幂等不抛 ----------------

def test_deselect_on_empty_store_is_idempotent(tmp_path):
    s = store(tmp_path)
    s.deselect()
    assert s.current_id() is None
    assert s.current() is None
    assert s.list() == []

    s.deselect()
    assert s.current_id() is None
    assert s.list() == []

    s.add(offline_data("Steve"), "offline")
    s.deselect()
    s.deselect()
    assert s.current_id() is None
    assert s.current() is None
    assert len(s.list()) == 1


# ---------------- 30. B: 未登录调 refresh_login → RuntimeError ----------------

def test_refresh_login_without_current_raises_runtime_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "minecraft_launcher_lib.microsoft_account.complete_refresh",
        lambda *args, **kwargs: {
            "name": "Ghost", "id": "ghost-uuid",
            "access_token": "t", "refresh_token": "r",
        },
    )
    auth = make_auth(tmp_path)

    with pytest.raises(RuntimeError, match="未登录"):
        auth.refresh_login("some-refresh-token")

    assert auth.get_login_data() is None
    assert AccountStore(Path(tmp_path)).list() == []
    assert not (Path(tmp_path) / "auth.json").exists()


# ---------------- 31. B: mll 异常原样传出 + ERROR(exc_info) + store 不变 ----------------

def test_refresh_login_mll_error_propagates_and_keeps_store(tmp_path, monkeypatch, caplog):
    s = AccountStore(Path(tmp_path))
    s.add(ms_data("Alex", uid="ms-uuid-1"), "microsoft")
    auth = AuthManager("test-client-id", store=s)
    before = s.list()
    before_id = s.current_id()

    def boom(*args, **kwargs):
        raise RuntimeError("refresh boom")

    monkeypatch.setattr("minecraft_launcher_lib.microsoft_account.complete_refresh", boom)

    with caplog.at_level(logging.ERROR, logger="DevLauncher"):
        with pytest.raises(RuntimeError, match="refresh boom"):
            auth.refresh_login("ms-refresh")

    errors = [r for r in caplog.records if r.name == "DevLauncher"]
    assert any(
        r.levelno == logging.ERROR and r.exc_info for r in errors
    ), "缺少 logger.error(..., exc_info=True)"

    assert s.list() == before
    assert s.current()["access_token"] == "ms-access-token"
    reloaded = AccountStore(Path(tmp_path))
    assert reloaded.current()["access_token"] == "ms-access-token"
    assert reloaded.current_id() == before_id


# ---------------- 32. C: 落盘失败上抛 + 磁盘无该账号 ----------------

def test_save_failure_propagates_and_disk_unchanged(tmp_path, monkeypatch):
    s = store(tmp_path)
    s.add(offline_data("Steve"), "offline")
    accounts_file = Path(tmp_path) / "accounts.json"
    assert accounts_file.exists()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(OSError, match="disk full"):
        s.add(offline_data("Alex", uid="uuid-alex"), "offline")

    monkeypatch.undo()

    # 契约=上抛: 磁盘保持失败前状态, 新账号不在 accounts.json
    on_disk = json.loads(accounts_file.read_text(encoding="utf-8"))
    assert len(on_disk["accounts"]) == 1
    assert on_disk["accounts"][0]["name"] == "Steve"
    assert all(a["name"] != "Alex" for a in on_disk["accounts"])

    fresh = AccountStore(Path(tmp_path))
    assert [a["name"] for a in fresh.list()] == ["Steve"]
    assert fresh.current()["name"] == "Steve"


# ---------------- 33. C: 不可序列化 data → TypeError + ERROR 日志 + 磁盘无变化 ----------------

def test_add_unserializable_data_raises_type_error(tmp_path, caplog):
    s = store(tmp_path)
    s.add(offline_data("Steve"), "offline")
    accounts_file = Path(tmp_path) / "accounts.json"
    before = accounts_file.read_text(encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="DevLauncher"):
        with pytest.raises(TypeError):
            s.add({"name": "Bad", "id": "bad-uuid", "x": object()}, "offline")

    errors = [r for r in caplog.records if r.name == "DevLauncher"]
    assert any(
        r.levelno == logging.ERROR and r.exc_info for r in errors
    ), "缺少 logger.error(..., exc_info=True)"

    assert accounts_file.read_text(encoding="utf-8") == before
    fresh = AccountStore(Path(tmp_path))
    assert [a["name"] for a in fresh.list()] == ["Steve"]


# ---------------- 34. D: complete_login 失败 → store 为空 + 无 auth.json ----------------

def test_complete_login_failure_keeps_store_empty(tmp_path, monkeypatch):
    auth = make_auth(tmp_path)
    auth._code_verifier = "test-verifier"

    def boom(*args, **kwargs):
        raise RuntimeError("login boom")

    monkeypatch.setattr("minecraft_launcher_lib.microsoft_account.complete_login", boom)

    with pytest.raises(RuntimeError, match="login boom"):
        auth.complete_login("some-auth-code")

    assert auth.get_login_data() is None
    assert auth.is_logged_in is False
    assert AccountStore(Path(tmp_path)).list() == []
    assert not (Path(tmp_path) / "accounts.json").exists()
    assert not (Path(tmp_path) / "auth.json").exists()


# ---------------- 35. D: offline_login 空白用户名 → ValueError ----------------

def test_offline_login_blank_username_raises_value_error(tmp_path):
    auth = make_auth(tmp_path)

    with pytest.raises(ValueError):
        auth.offline_login("")

    with pytest.raises(ValueError):
        auth.offline_login("   ")

    assert auth.get_login_data() is None
    assert AccountStore(Path(tmp_path)).list() == []
    assert not (Path(tmp_path) / "accounts.json").exists()
    assert not (Path(tmp_path) / "auth.json").exists()


# ================= 质量审查修复轮: 数据边界 =================

# ---------------- 36. lastUsed 非数值 → 0.0 (list 不抛, add/_now 仍成立) ----------------

def test_load_non_numeric_last_used_coerced_to_zero(tmp_path):
    payload = {
        "current_id": None,
        "accounts": [
            {
                "id": "a-1",
                "type": "offline",
                "name": "A",
                "uuid": "u1",
                "data": {"name": "A", "id": "u1", "access_token": "offline_token"},
                "created": 1.0,
                "lastUsed": 3.0,
            },
            {
                "id": "a-2",
                "type": "offline",
                "name": "B",
                "uuid": "u2",
                "data": {"name": "B", "id": "u2", "access_token": "offline_token"},
                "created": 1.0,
                "lastUsed": "yesterday",
            },
        ],
    }
    (Path(tmp_path) / "accounts.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    s = store(tmp_path)

    listed = s.list()  # 不抛 (str/float 混排比较会 TypeError)
    by_id = {a["id"]: a for a in listed}
    assert by_id["a-2"]["lastUsed"] == 0.0  # float 化失败即 0.0
    assert isinstance(by_id["a-2"]["lastUsed"], float)
    assert by_id["a-1"]["lastUsed"] == 3.0

    # add 的 _now()/list 排序逻辑仍成立
    added = s.add(offline_data(name="C", uid="uuid-c"), "offline")
    assert isinstance(added["lastUsed"], float)
    assert s.list()[0]["id"] == added["id"]


# ---------------- 37. data 非 dict → 剔除该条 + WARNING ----------------

def test_load_drops_non_dict_data_entry(tmp_path, caplog):
    payload = {
        "current_id": "bad-1",
        "accounts": [
            {
                "id": "bad-1",
                "type": "offline",
                "name": "Bad",
                "uuid": "ub",
                "data": "oops",
                "created": 1.0,
                "lastUsed": 2.0,
            },
            {
                "id": "ok-1",
                "type": "offline",
                "name": "Steve",
                "uuid": "u1",
                "data": {"name": "Steve", "id": "u1", "access_token": "offline_token"},
                "created": 1.0,
                "lastUsed": 5.0,
            },
        ],
    }
    (Path(tmp_path) / "accounts.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    with caplog.at_level(logging.WARNING, logger="DevLauncher"):
        s = store(tmp_path)

    listed = s.list()
    assert [a["id"] for a in listed] == ["ok-1"]  # data 非 dict 的条目被剔除
    assert s.current_id() is None  # 悬空 current 视同 None
    assert s.current() is None
    warnings = [r for r in caplog.records if r.name == "DevLauncher"]
    assert any(r.levelno == logging.WARNING for r in warnings), "缺少 WARNING 日志"


# ================= 终审轮: I-3 启动健壮性 =================

def test_auth_manager_init_survives_migrate_legacy_failure(tmp_path, monkeypatch, caplog):
    s = AccountStore(Path(tmp_path))

    def _boom():
        raise OSError("disk full")

    monkeypatch.setattr(s, "migrate_legacy", _boom)
    with caplog.at_level(logging.ERROR, logger="DevLauncher"):
        auth = AuthManager("test-client-id", store=s)
    assert auth.store is s  # 正常构造, 未抛 OSError
    assert any(r.levelno >= logging.ERROR for r in caplog.records), "迁移失败应记 ERROR 日志"

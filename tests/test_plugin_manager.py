"""PluginManager 插件系统核心 (TDD RED/GREEN)

- scan 摘要/排序/坏 manifest 不崩
- 启停 enabled.json 持久化与默认启用
- detail settings schema + contentHtml
- save_config 类型校验(text/toggle/number) + 失败不落盘
- load_all 单插件异常隔离(import / on_load)
- uninstall/folder_of 路径穿越防护
- 仓库内 plugins/hello-sample 真实加载
"""
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from launcher_core.plugins import PluginContext, PluginManager  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

SETTINGS = [
    {"key": "greeting", "label": "问候语", "type": "text", "default": "你好"},
    {"key": "enabled_anim", "label": "显示动画", "type": "toggle", "default": True},
    {"key": "max_items", "label": "最大条目", "type": "number", "default": 5},
]

OK_CODE = (
    "class Plugin:\n"
    "    def on_load(self, ctx):\n"
    "        cfg = ctx.get_config()\n"
    "        ctx.register_content(\n"
    "            f\"<div class='plugin-content'>{cfg.get('greeting', 'hi')}</div>\"\n"
    "        )\n"
)

RAISING_CODE = (
    "class Plugin:\n"
    "    def on_load(self, ctx):\n"
    "        raise RuntimeError('boom')\n"
)

NO_ONLOAD_CODE = "class Plugin:\n    pass\n"

BAD_SIG_CODE = "class Plugin:\n    def on_load(self):\n        pass\n"

BROKEN_IMPORT_CODE = "raise ImportError('nope-import')\n"


def make_plugin(root, plugin_id, *, name=None, code=OK_CODE, settings=SETTINGS, raw_manifest=None):
    d = root / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    if raw_manifest is not None:
        (d / "manifest.json").write_text(raw_manifest, encoding="utf-8")
    else:
        manifest = {
            "id": plugin_id,
            "name": name if name is not None else plugin_id,
            "version": "1.0.0",
            "author": "tester",
            "icon": "P",
            "description": "测试插件",
        }
        if settings is not None:
            manifest["settings"] = settings
        (d / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if code is not None:
        (d / "plugin.py").write_text(code, encoding="utf-8")
    return d


# ---------- 1. scan 正常 ----------

def test_scan_two_plugins_sorted_and_summary_fields(tmp_path):
    make_plugin(tmp_path, "zeta", name="Zeta 插件")
    make_plugin(tmp_path, "alpha", name="Alpha 插件")
    items = PluginManager(tmp_path).scan()
    assert len(items) == 2
    assert [i["name"] for i in items] == ["Alpha 插件", "Zeta 插件"]
    required = {
        "id", "name", "version", "author", "icon", "description",
        "status", "errorMsg", "hasSettings", "hasContent",
    }
    for item in items:
        assert required <= set(item.keys())
    assert items[0]["id"] == "alpha"
    assert items[0]["version"] == "1.0.0"
    assert items[0]["author"] == "tester"
    assert items[0]["hasSettings"] is True


# ---------- 2. 坏 JSON manifest ----------

def test_scan_bad_json_manifest_skipped_with_warning(tmp_path, caplog):
    make_plugin(tmp_path, "good", name="Good")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("{ not json !!!", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        items = PluginManager(tmp_path).scan()
    assert [i["id"] for i in items] == ["good"]
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


# ---------- 3. 缺 id/name 跳过 ----------

def test_scan_missing_id_or_name_skipped(tmp_path):
    make_plugin(tmp_path, "noid", raw_manifest=json.dumps({"name": "无id"}))
    make_plugin(tmp_path, "noname", raw_manifest=json.dumps({"id": "noname"}))
    make_plugin(tmp_path, "ok", name="OK")
    items = PluginManager(tmp_path).scan()
    assert [i["id"] for i in items] == ["ok"]


# ---------- 4. 新插件默认启用 ----------

def test_new_plugin_defaults_enabled(tmp_path):
    make_plugin(tmp_path, "fresh", name="Fresh")
    items = PluginManager(tmp_path).scan()
    assert items[0]["status"] == "enabled"
    assert not (tmp_path / "enabled.json").exists()


# ---------- 5. set_enabled 持久化 ----------

def test_set_enabled_false_persists_across_instances(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    make_plugin(tmp_path, "p2", name="P2")
    pm = PluginManager(tmp_path)
    pm.set_enabled("p1", False)
    assert (tmp_path / "enabled.json").exists()
    data = json.loads((tmp_path / "enabled.json").read_text(encoding="utf-8"))
    assert data["p1"] is False
    pm2 = PluginManager(tmp_path)
    items = {i["id"]: i for i in pm2.scan()}
    assert items["p1"]["status"] == "disabled"
    assert items["p2"]["status"] == "enabled"


# ---------- 6. detail settings schema + 默认 value ----------

def test_detail_settings_schema_and_defaults(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    d = pm.detail("p1")
    assert d is not None
    assert d["hasSettings"] is True
    settings = d["settings"]
    assert [s["key"] for s in settings] == ["greeting", "enabled_anim", "max_items"]
    first = settings[0]
    assert first == {
        "key": "greeting", "label": "问候语", "type": "text",
        "default": "你好", "value": "你好",
    }
    assert settings[1]["value"] is True
    assert settings[2]["value"] == 5
    assert d["contentHtml"] == ""
    assert pm.detail("nope") is None


# ---------- 7. load_all 后 contentHtml；disable 后清空 ----------

def test_load_all_then_disable_clears_content(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    pm.load_all()
    d = pm.detail("p1")
    assert d["contentHtml"] != ""
    assert "plugin-content" in d["contentHtml"]
    assert pm.scan()[0]["hasContent"] is True
    pm.set_enabled("p1", False)
    d2 = pm.detail("p1")
    assert d2["contentHtml"] == ""
    assert d2["status"] == "disabled"
    assert pm.scan()[0]["hasContent"] is False


# ---------- 8. save_config 类型校验 ----------

def test_save_config_accepts_valid_types(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    r1 = pm.save_config("p1", {"greeting": "Hi"})
    assert r1 == {"success": True, "error": None}
    r2 = pm.save_config("p1", {"enabled_anim": False})
    assert r2["success"] is True and r2["error"] is None
    r3 = pm.save_config("p1", {"max_items": 7})
    assert r3["success"] is True
    saved = json.loads((tmp_path / "p1" / "config.json").read_text(encoding="utf-8"))
    assert saved["greeting"] == "Hi"
    assert saved["enabled_anim"] is False
    assert saved["max_items"] == 7


def test_save_config_rejects_bad_types_and_keys(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    bad_number = pm.save_config("p1", {"max_items": "5"})
    assert bad_number["success"] is False
    assert bad_number["error"]
    bad_key = pm.save_config("p1", {"unknown_key": 1})
    assert bad_key["success"] is False
    assert bad_key["error"]
    bad_toggle = pm.save_config("p1", {"enabled_anim": "yes"})
    assert bad_toggle["success"] is False
    bad_text = pm.save_config("p1", {"greeting": 123})
    assert bad_text["success"] is False
    assert not (tmp_path / "p1" / "config.json").exists()


# ---------- 9. get_config 默认补齐 ----------

def test_get_config_fills_missing_defaults(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    (tmp_path / "p1" / "config.json").write_text(
        json.dumps({"greeting": "OnlyOne"}, ensure_ascii=False), encoding="utf-8"
    )
    pm = PluginManager(tmp_path)
    d = pm.detail("p1")
    values = {s["key"]: s["value"] for s in d["settings"]}
    assert values == {"greeting": "OnlyOne", "enabled_anim": True, "max_items": 5}


# ---------- 10. on_load 抛异常隔离 ----------

def test_load_all_isolates_on_load_exception(tmp_path):
    make_plugin(tmp_path, "bad", name="Bad", code=RAISING_CODE)
    make_plugin(tmp_path, "good", name="Good")
    pm = PluginManager(tmp_path)
    pm.load_all()
    items = {i["id"]: i for i in pm.scan()}
    assert items["bad"]["status"] == "error"
    assert items["bad"]["errorMsg"]
    assert items["good"]["status"] == "enabled"
    assert "plugin-content" in pm.detail("good")["contentHtml"]


def test_on_load_missing_or_bad_signature_is_error(tmp_path):
    make_plugin(tmp_path, "noload", name="NoLoad", code=NO_ONLOAD_CODE)
    make_plugin(tmp_path, "badsig", name="BadSig", code=BAD_SIG_CODE)
    pm = PluginManager(tmp_path)
    pm.load_all()
    items = {i["id"]: i for i in pm.scan()}
    assert items["noload"]["status"] == "error"
    assert items["noload"]["errorMsg"]
    assert items["badsig"]["status"] == "error"
    assert items["badsig"]["errorMsg"]


# ---------- 11. plugin.py import 抛异常 ----------

def test_import_error_marks_error_status(tmp_path):
    make_plugin(tmp_path, "boom", name="Boom", code=BROKEN_IMPORT_CODE)
    pm = PluginManager(tmp_path)
    pm.load_all()
    items = pm.scan()
    assert items[0]["status"] == "error"
    assert "nope-import" in items[0]["errorMsg"]


# ---------- 12. uninstall 真删 / 不存在 ----------

def test_uninstall_removes_dir_and_unknown_false(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    assert pm.uninstall("p1") is True
    assert not (tmp_path / "p1").exists()
    assert pm.uninstall("p1") is False
    assert pm.uninstall("ghost") is False


# ---------- 13. uninstall / folder_of 拒绝非法 id ----------

@pytest.mark.parametrize("bad_id", ["../x", "a/b", "p1/..", "..", "ghost"])
def test_uninstall_and_folder_of_reject_illegal_ids(tmp_path, bad_id):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    assert pm.uninstall(bad_id) is False
    assert pm.folder_of(bad_id) is None
    assert (tmp_path / "p1").exists()


# ---------- 14. folder_of 正常 ----------

def test_folder_of_returns_path(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    assert pm.folder_of("p1") == tmp_path / "p1"


# ---------- M2-1. folder_of 第三道防线（目录联接绕过） ----------

windows_only = pytest.mark.skipif(
    not sys.platform.startswith("win32"),
    reason="目录联接(junction/mklink)用例仅 Windows 运行——平台标记，非弱化断言",
)


def _make_dir_link(link: Path, target: Path) -> str | None:
    """创建指向 target 的目录联接；返回 'junction'/'symlink'，都失败返回 None。"""
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True,
    )
    if proc.returncode == 0 and link.exists():
        return "junction"
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
    except OSError:
        return None
    return "symlink" if link.exists() else None


@windows_only
def test_folder_of_rejects_junction_outside_plugins_dir(tmp_path, caplog):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    outside_plugin = make_plugin(tmp_path / "outside", "linked", name="Linked")
    link = plugins_dir / "linked"
    kind = _make_dir_link(link, outside_plugin)
    assert kind is not None, "无法创建目录联接(junction/symlink)"
    pm = PluginManager(plugins_dir)
    with caplog.at_level(logging.WARNING):
        items = pm.scan()
    # 断言加强：scan / folder_of / uninstall 三处都必须拒绝
    assert [i["id"] for i in items] == []
    assert pm.folder_of("linked") is None
    assert pm.uninstall("linked") is False
    assert outside_plugin.exists()
    assert (outside_plugin / "manifest.json").exists()


# ---------- M3-2. scan 拒收恶意 id ----------

def test_scan_rejects_path_traversal_ids(tmp_path, caplog):
    make_plugin(tmp_path, "evil1", name="Evil1",
                raw_manifest=json.dumps({"id": "../x", "name": "evil"}))
    make_plugin(tmp_path, "evil2", name="Evil2",
                raw_manifest=json.dumps({"id": "a/b", "name": "evil"}))
    make_plugin(tmp_path, "ok", name="OK")
    with caplog.at_level(logging.WARNING):
        items = PluginManager(tmp_path).scan()
    assert [i["id"] for i in items] == ["ok"]
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


# ---------- M3-3. number 校验补全（float 通过 / bool 拒绝） ----------

def test_save_config_number_accepts_float_rejects_bool(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    ok = pm.save_config("p1", {"max_items": 5.5})
    assert ok == {"success": True, "error": None}
    bad = pm.save_config("p1", {"max_items": True})
    assert bad["success"] is False
    assert bad["error"]
    saved = json.loads((tmp_path / "p1" / "config.json").read_text(encoding="utf-8"))
    assert saved["max_items"] == 5.5


# ---------- M3-4. reload(None) 全量分支 ----------

def test_reload_none_refreshes_all_content(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    make_plugin(tmp_path, "p2", name="P2")
    pm = PluginManager(tmp_path)
    pm.load_all()
    (tmp_path / "p1" / "config.json").write_text(
        json.dumps({"greeting": "FirstNew"}, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "p2" / "config.json").write_text(
        json.dumps({"greeting": "SecondNew"}, ensure_ascii=False), encoding="utf-8"
    )
    pm.reload()
    assert "FirstNew" in pm.detail("p1")["contentHtml"]
    assert "SecondNew" in pm.detail("p2")["contentHtml"]


# ---------- M3-5. 模块名直拼 + 重复 id ----------

def test_plugin_id_with_dash_keeps_raw_module_name(tmp_path):
    make_plugin(tmp_path, "a-b", name="Dash")
    pm = PluginManager(tmp_path)
    pm.load_all()
    assert pm.detail("a-b")["status"] == "enabled"
    assert "plugin-content" in pm.detail("a-b")["contentHtml"]
    assert "devlauncher_plugin_a-b" in sys.modules


def test_scan_duplicate_id_second_skipped_with_warning(tmp_path, caplog):
    make_plugin(tmp_path, "dir_a", name="DirA",
                raw_manifest=json.dumps({"id": "dup", "name": "First"}, ensure_ascii=False))
    make_plugin(tmp_path, "dir_b", name="DirB",
                raw_manifest=json.dumps({"id": "dup", "name": "Second"}, ensure_ascii=False))
    with caplog.at_level(logging.WARNING):
        items = PluginManager(tmp_path).scan()
    assert len(items) == 1
    assert items[0]["name"] == "First"
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


# ---------- M3-6. save_config 契约完整性（OSError 不穿透） ----------

def test_save_config_oserror_returns_failure(tmp_path, monkeypatch):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)

    def _boom(path, payload):
        raise OSError("disk full")

    monkeypatch.setattr("launcher_core.plugins._atomic_write_json", _boom)
    result = pm.save_config("p1", {"greeting": "Hi"})
    assert result["success"] is False
    assert result["error"]


# ---------- M3-1. 持久化格式断言 ----------

def test_persistence_format_indent2_and_utf8_raw(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    pm.set_enabled("p1", False)
    enabled_text = (tmp_path / "enabled.json").read_text(encoding="utf-8")
    assert enabled_text.startswith("{\n  ")
    assert "false" in enabled_text
    result = pm.save_config("p1", {"greeting": "中文问候值"})
    assert result["success"] is True
    config_text = (tmp_path / "p1" / "config.json").read_text(encoding="utf-8")
    assert config_text.startswith("{\n  ")
    assert "中文问候值" in config_text
    assert "\\u4e2d" not in config_text


# ---------- 15. 示例插件真实加载 ----------

def test_hello_sample_real_plugin_loads():
    pm = PluginManager(REPO_ROOT / "plugins")
    items = pm.scan()
    assert "hello-sample" in [i["id"] for i in items]
    pm.load_all()
    d = pm.detail("hello-sample")
    assert d["status"] == "enabled"
    assert "plugin-content" in d["contentHtml"]
    assert "你好" in d["contentHtml"]
    assert d["hasSettings"] is True


# ---------- 16. reload 后 contentHtml 更新 ----------

def test_reload_updates_content_after_config_change(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    pm.load_all()
    assert pm.detail("p1")["contentHtml"] == "<div class='plugin-content'>你好</div>"
    (tmp_path / "p1" / "config.json").write_text(
        json.dumps({"greeting": "Replaced"}, ensure_ascii=False), encoding="utf-8"
    )
    pm.reload("p1")
    assert "Replaced" in pm.detail("p1")["contentHtml"]


# ---------- 17. enabled.json 语义 ----------

def test_enabled_json_missing_means_all_enabled(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    make_plugin(tmp_path, "p2", name="P2")
    items = PluginManager(tmp_path).scan()
    assert [i["status"] for i in items] == ["enabled", "enabled"]


def test_enabled_json_partial_disable_keeps_other_enabled(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    make_plugin(tmp_path, "p2", name="P2")
    (tmp_path / "enabled.json").write_text(
        json.dumps({"p1": False}), encoding="utf-8"
    )
    items = {i["id"]: i for i in PluginManager(tmp_path).scan()}
    assert items["p1"]["status"] == "disabled"
    assert items["p2"]["status"] == "enabled"


# ---------- 附加：PluginContext set_config 直接校验 ----------

def test_context_set_config_raises_value_error(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    ctx = PluginContext("p1", tmp_path / "p1", SETTINGS)
    with pytest.raises(ValueError):
        ctx.set_config({"max_items": "5"})
    with pytest.raises(ValueError):
        ctx.set_config({"nope": 1})
    assert ctx.get_config()["greeting"] == "你好"
    ctx.set_config({"greeting": "After"})
    assert ctx.get_config()["greeting"] == "After"


# ================= 质量审查修复轮 =================

# ---------- S1. detail 被非法 settings 打崩 ----------

def test_detail_filters_illegal_settings_entries(tmp_path):
    make_plugin(tmp_path, "p1", name="P1",
                raw_manifest=json.dumps({"id": "p1", "name": "P1", "settings": ["oops"]},
                                        ensure_ascii=False))
    make_plugin(tmp_path, "p2", name="P2",
                raw_manifest=json.dumps({"id": "p2", "name": "P2", "settings": [{"label": "x"}]},
                                        ensure_ascii=False))
    make_plugin(tmp_path, "p3", name="P3",
                raw_manifest=json.dumps({"id": "p3", "name": "P3", "settings": [
                    "oops", {"label": "x"},
                    {"key": "ok", "label": "好", "type": "number", "default": 3},
                    {"key": "weird", "label": "怪", "type": "wat", "default": "d"},
                ]}, ensure_ascii=False))
    pm = PluginManager(tmp_path)
    d1 = pm.detail("p1")
    assert d1["settings"] == []
    d2 = pm.detail("p2")
    assert d2["settings"] == []
    d3 = pm.detail("p3")
    assert [s["key"] for s in d3["settings"]] == ["ok"]
    assert d3["settings"][0]["value"] == 3


# ---------- M1. 卸载顺序：先 pop 实例再删目录 ----------

def test_uninstall_oserror_pops_instance_before_rmtree(tmp_path, monkeypatch):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    pm.load_all()
    assert "p1" in pm._instances

    def _boom(path, *args, **kwargs):
        raise OSError("busy")

    monkeypatch.setattr("launcher_core.plugins.shutil.rmtree", _boom)
    assert pm.uninstall("p1") is False
    assert "p1" not in pm._instances
    assert "p1" not in pm._contexts
    assert (tmp_path / "p1").exists()


# ---------- M2. 防线下沉到 scan（junction 在扫描期即被拒绝） ----------

@windows_only
def test_scan_excludes_junction_outside_plugins_dir(tmp_path, caplog):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    outside_plugin = make_plugin(tmp_path / "outside", "linked", name="Linked")
    make_plugin(plugins_dir, "normal", name="Normal")
    kind = _make_dir_link(plugins_dir / "linked", outside_plugin)
    assert kind is not None, "无法创建目录联接(junction/symlink)"
    pm = PluginManager(plugins_dir)
    with caplog.at_level(logging.WARNING):
        items = pm.scan()
    assert [i["id"] for i in items] == ["normal"]
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
    assert pm.folder_of("linked") is None
    assert pm.uninstall("linked") is False
    assert outside_plugin.exists()


# ---------- M3. enable 立即加载 ----------

def test_set_enabled_true_loads_without_load_all(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    pm.load_all()
    pm.set_enabled("p1", False)
    assert pm.detail("p1")["contentHtml"] == ""
    pm.set_enabled("p1", True)
    d = pm.detail("p1")
    assert d["status"] == "enabled"
    assert "plugin-content" in d["contentHtml"]


def test_set_enabled_true_isolates_load_failure(tmp_path):
    make_plugin(tmp_path, "bad", name="Bad", code=RAISING_CODE)
    pm = PluginManager(tmp_path)
    pm.set_enabled("bad", False)
    pm.set_enabled("bad", True)
    d = pm.detail("bad")
    assert d["status"] == "error"
    assert d["errorMsg"]
    assert d["contentHtml"] == ""


# ---------- M4. set_enabled 错误契约：记 ERROR 日志后抛 ----------

def test_set_enabled_write_oserror_logs_error_and_raises(tmp_path, monkeypatch, caplog):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)

    def _boom(path, payload):
        raise OSError("disk full")

    monkeypatch.setattr("launcher_core.plugins._atomic_write_json", _boom)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(OSError):
            pm.set_enabled("p1", False)
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


# ---------- M5. save_config 的 TypeError 漏网 ----------

def test_save_config_unserializable_value_returns_failure(tmp_path):
    make_plugin(tmp_path, "p1", name="P1",
                settings=SETTINGS + [{"key": "blob", "label": "任意", "type": "custom",
                                      "default": "x"}])
    pm = PluginManager(tmp_path)
    literal = pm.save_config("p1", {"greeting": {1, 2}})
    assert literal["success"] is False and literal["error"]
    r = pm.save_config("p1", {"blob": {1, 2}})
    assert r["success"] is False
    assert r["error"]


# ---------- M6. scan 用统一 id 白名单 ----------

def test_scan_rejects_non_whitelisted_ids(tmp_path, caplog):
    make_plugin(tmp_path, "dir_cn",
                raw_manifest=json.dumps({"id": "中文插件", "name": "CN"}, ensure_ascii=False))
    make_plugin(tmp_path, "dir_sp",
                raw_manifest=json.dumps({"id": "has space", "name": "SP"}, ensure_ascii=False))
    make_plugin(tmp_path, "ok", name="OK")
    with caplog.at_level(logging.WARNING):
        items = PluginManager(tmp_path).scan()
    assert [i["id"] for i in items] == ["ok"]
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) >= 2


# ---------- M7. register_content 类型校验 ----------

def test_register_content_rejects_non_string(tmp_path):
    ctx = PluginContext("p1", tmp_path / "p1", SETTINGS)
    with pytest.raises(TypeError):
        ctx.register_content(12345)
    ctx.register_content("<div>ok</div>")
    assert ctx.content == "<div>ok</div>"


# ---------- M8. sys.modules 残留 ----------

def test_failed_exec_module_leaves_no_sys_modules_entry(tmp_path):
    mod = "devlauncher_plugin_boomexec"
    sys.modules.pop(mod, None)
    make_plugin(tmp_path, "boomexec", name="BoomExec",
                code="raise RuntimeError('top-level boom')\n")
    pm = PluginManager(tmp_path)
    pm.load_all()
    assert mod not in sys.modules
    items = {i["id"]: i for i in pm.scan()}
    assert items["boomexec"]["status"] == "error"
    sys.modules.pop(mod, None)


def test_disable_and_uninstall_drop_module_entry(tmp_path):
    mod = "devlauncher_plugin_modclean"
    sys.modules.pop(mod, None)
    make_plugin(tmp_path, "modclean", name="ModClean")
    pm = PluginManager(tmp_path)
    pm.load_all()
    assert mod in sys.modules
    pm.set_enabled("modclean", False)
    assert mod not in sys.modules
    pm.set_enabled("modclean", True)
    assert mod in sys.modules
    assert pm.uninstall("modclean") is True
    assert mod not in sys.modules
    sys.modules.pop(mod, None)


# ---------- B1. reload 源码级测试 ----------

def test_reload_picks_up_plugin_source_change(tmp_path):
    v1 = (
        "class Plugin:\n"
        "    def on_load(self, ctx):\n"
        "        ctx.register_content('<div>v1marker</div>' + ' ' * 64)\n"
    )
    v2 = (
        "class Plugin:\n"
        "    def on_load(self, ctx):\n"
        "        ctx.register_content('<div>v2marker_longer</div>' + ' ' * 128)\n"
        "        # 占位填充改变文件尺寸，避开 pyc 同秒同尺寸缓存\n"
    )
    make_plugin(tmp_path, "p1", name="P1", code=v1)
    pm = PluginManager(tmp_path)
    pm.load_all()
    assert "v1marker" in pm.detail("p1")["contentHtml"]
    (tmp_path / "p1" / "plugin.py").write_text(v2, encoding="utf-8")
    pm.reload()
    content = pm.detail("p1")["contentHtml"]
    assert "v2marker_longer" in content
    assert "v1marker" not in content


# ---------- B6. 示例插件 escape 生效 ----------

def test_hello_sample_escapes_greeting(tmp_path):
    import shutil as _shutil
    src = REPO_ROOT / "plugins" / "hello-sample"
    dst = tmp_path / "hello-sample"
    _shutil.copytree(src, dst, ignore=_shutil.ignore_patterns("__pycache__"))
    (dst / "config.json").write_text(
        json.dumps({"greeting": "<b>hi</b>"}, ensure_ascii=False), encoding="utf-8"
    )
    pm = PluginManager(tmp_path)
    pm.load_all()
    content = pm.detail("hello-sample")["contentHtml"]
    assert "&lt;b&gt;hi&lt;/b&gt;" in content
    assert "<b>hi</b>" not in content


# ================= 规格+质量合并修复轮 =================

# ---------- S1. 引号注入: Python 侧 key 白名单 (detail 与 PluginContext 双路径) ----------

def test_filter_unsafe_setting_keys_both_paths(tmp_path):
    bad = [
        {"key": 'bad"key', "label": "坏引号", "type": "text", "default": "x"},
        {"key": "ok key", "label": "带空格", "type": "text", "default": "y"},
        {"key": "good_key", "label": "好", "type": "text", "default": "z"},
    ]
    make_plugin(tmp_path, "p1", name="P1", settings=bad)
    pm = PluginManager(tmp_path)
    # detail 路径: 坏 key 不出现在返回 schema
    d = pm.detail("p1")
    assert [s["key"] for s in d["settings"]] == ["good_key"]
    # PluginContext 路径: 坏 key 不进入 ctx.settings
    ctx = PluginContext("p1", tmp_path / "p1", bad)
    assert [s["key"] for s in ctx.settings] == ["good_key"]
    # save_config 校验收不到坏 key → 未知配置项拒绝
    r = pm.save_config("p1", {"good_key": "v", 'bad"key': "leak"})
    assert r["success"] is False
    assert "bad" not in json.dumps(pm.detail("p1")["settings"], ensure_ascii=False)


# ---------- 规格15. detail 缺「目录」 ----------

def test_detail_includes_dir(tmp_path):
    make_plugin(tmp_path, "p1", name="P1")
    pm = PluginManager(tmp_path)
    d = pm.detail("p1")
    assert isinstance(d.get("dir"), str)
    assert d["dir"] == str(tmp_path / "p1")
    assert Path(d["dir"]).is_absolute()


# ================= 终审轮: I-4 .gitignore 卫生 =================

def test_gitignore_covers_plugin_runtime_artifacts():
    content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "plugins/enabled.json" in content, ".gitignore 缺 plugins/enabled.json"
    assert "plugins/*/config.json" in content, ".gitignore 缺 plugins/*/config.json"

    def _check_ignore(path: str) -> int:
        return subprocess.run(
            ["git", "check-ignore", "-q", path],
            cwd=str(REPO_ROOT), capture_output=True,
        ).returncode

    assert _check_ignore("plugins/enabled.json") == 0, "plugins/enabled.json 应被忽略"
    assert _check_ignore("plugins/hello-sample/config.json") == 0, "插件 config.json 应被忽略"
    assert _check_ignore("plugins/hello-sample/manifest.json") == 1, \
        "manifest.json 必须保持入库, 不得被忽略"

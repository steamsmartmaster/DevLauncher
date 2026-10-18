# -*- coding: utf-8 -*-
"""三个工具插件的分析逻辑（mods 目录体检 / 实例体积统计 / Java 运行时体检）。

三者共用一个形状：把「跑分析」拆成接受路径入参的纯函数，`Plugin.on_load`
只负责把结果渲染成 HTML。这样分析逻辑能在没有 Minecraft 安装、没有 Java、
没有 Qt 的情况下被 pytest 覆盖，而 on_load 只需要冒烟测试。
"""
import importlib.util
import json
import zipfile
from pathlib import Path

from launcher_core.plugins import PluginContext

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_plugin(plugin_id: str):
    path = REPO_ROOT / "plugins" / plugin_id / "plugin.py"
    spec = importlib.util.spec_from_file_location(f"tool_{plugin_id}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_manifest(plugin_id: str) -> dict:
    path = REPO_ROOT / "plugins" / plugin_id / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def make_jar(path: Path, entries=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in (entries or {"a.txt": b"x"}).items():
            zf.writestr(name, data)


def smoke(mod, manifest, cfg=None):
    ctx = PluginContext(manifest["id"], REPO_ROOT / "plugins" / manifest["id"],
                        manifest.get("settings"))
    if cfg:
        ctx._content = ""
    mod.Plugin().on_load(ctx)
    return ctx.content


# ---------- 通用：三个插件都必须在清单里且能渲染 ----------

def test_three_tools_shipped_with_valid_manifests():
    for pid in ("mods-doctor", "instance-size", "java-doctor"):
        m = read_manifest(pid)
        assert m["id"] == pid
        assert m["name"].strip()
        assert m["description"].strip()
        assert isinstance(m.get("settings", []), list)
        for s in m.get("settings", []):
            assert {"key", "label", "type", "default"} <= set(s), (pid, s)


def test_three_tools_render_content_without_a_real_minecraft_install():
    for pid in ("mods-doctor", "instance-size", "java-doctor"):
        html_out = smoke(load_plugin(pid), read_manifest(pid))
        assert html_out, f"{pid} 应渲染出内容"
        assert "plugin-content" in html_out


# ---------- 1. mods 目录体检 ----------

def test_mods_audit_empty_dir():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mods = Path(tmp) / "mods"
        mods.mkdir()
        out = load_plugin("mods-doctor").audit(mods)
        assert out["total"] == 0
        assert out["invalid"] == []
        assert out["leftovers"] == []
        assert out["bytes"] == 0


def test_mods_audit_counts_valid_jars():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mods = Path(tmp) / "mods"
        make_jar(mods / "sodium.jar")
        make_jar(mods / "iris.jar")
        out = load_plugin("mods-doctor").audit(mods)
        assert out["total"] == 2
        assert out["invalid"] == []
        assert out["bytes"] > 0


def test_mods_audit_flags_non_zip_and_zero_byte_and_leftover():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mods = Path(tmp) / "mods"
        make_jar(mods / "good.jar")
        (mods / "broken.jar").write_bytes(b"not a zip at all")
        (mods / "zero.jar").write_bytes(b"")
        (mods / "half.jar.part").write_bytes(b"partial")
        out = load_plugin("mods-doctor").audit(mods)
        assert out["invalid"] == ["broken.jar"], out
        assert out["empty_files"] == ["zero.jar"], out
        assert out["leftovers"] == ["half.jar.part"], out
        assert out["total"] == 1, "leftover 不该算作已安装模组"


def test_mods_audit_detects_case_insensitive_duplicates():
    # 不能在 NTFS 上建 `Sodium.jar` 与 `sodium.jar`——Windows 文件系统不区分
    # 大小写，两个名字是同一个文件。分组逻辑因此单独测。
    grouped = load_plugin("mods-doctor").group_duplicates(
        ["Sodium.jar", "sodium.jar", "iris.jar"])
    assert sorted(grouped[0]) == ["Sodium.jar", "sodium.jar"]
    assert len(grouped) == 1


def test_mods_audit_missing_dir_is_not_an_error():
    out = load_plugin("mods-doctor").audit(Path("nope/not/here"))
    assert out["total"] == 0


# ---------- 2. 实例体积统计 ----------

def build_mc(tmp_path):
    mc = Path(tmp_path) / ".minecraft"
    (mc / "mods").mkdir(parents=True)
    (mc / "mods" / "global.jar").write_bytes(b"0" * 1000)
    (mc / "config").mkdir()
    (mc / "config" / "a.txt").write_bytes(b"0" * 200)
    inst = mc / "versions" / "Alpha"
    (inst / "mods").mkdir(parents=True)
    (inst / "mods" / "x.jar").write_bytes(b"0" * 3000)
    (inst / "config").mkdir()
    (inst / "config" / "c.txt").write_bytes(b"0" * 500)
    return mc


def test_instance_size_breakdown_and_totals(tmp_path):
    mc = build_mc(tmp_path)
    out = load_plugin("instance-size").report(mc)
    assert out["global"]["breakdown"]["mods"] == 1000
    assert out["global"]["breakdown"]["config"] == 200
    inst = {i["name"]: i for i in out["instances"]}["Alpha"]
    assert inst["breakdown"]["mods"] == 3000
    assert inst["total_bytes"] == 3500


def test_instance_size_totals_include_global_and_instances(tmp_path):
    mc = build_mc(tmp_path)
    out = load_plugin("instance-size").report(mc)
    assert out["global"]["total_bytes"] == 1200
    assert out["grand_total"] == 1200 + 3500


def test_instance_size_missing_dir_returns_empty_report():
    out = load_plugin("instance-size").report(Path("nope/here"))
    assert out["instances"] == []
    assert out["grand_total"] == 0


def test_instance_size_ignores_non_directory_entries(tmp_path):
    mc = build_mc(tmp_path)
    (mc / "versions" / "stray.txt").write_text("hi", encoding="utf-8")
    out = load_plugin("instance-size").report(mc)
    assert [i["name"] for i in out["instances"]] == ["Alpha"]


# ---------- 3. Java 运行时体检 ----------

def test_parse_openjdk_line():
    assert load_plugin("java-doctor").parse_java_version(
        'openjdk 17.0.9 2023-10-17\nOpenJDK Runtime Environment') == 17


def test_parse_legacy_1_8_line():
    assert load_plugin("java-doctor").parse_java_version(
        'java version "1.8.0_392"') == 8


def test_parse_modern_21_line():
    assert load_plugin("java-doctor").parse_java_version(
        'openjdk version "21.0.1" 2023-10-17') == 21


def test_parse_garbage_is_none():
    assert load_plugin("java-doctor").parse_java_version("bash: java: not found") is None
    assert load_plugin("java-doctor").parse_java_version("") is None


def test_requirement_by_mc_version():
    fn = load_plugin("java-doctor").required_java
    assert fn("1.16.5") == 8
    assert fn("1.17.1") == 16
    assert fn("1.18.2") == 17
    assert fn("1.20.4") == 17
    assert fn("1.20.6") == 21
    assert fn("1.21.1") == 21


def test_evaluate_ok_when_sufficient():
    out = load_plugin("java-doctor").evaluate(17, 17)
    assert out["ok"] is True
    assert out["found"] == 17
    assert out["required"] == 17


def test_evaluate_fails_when_too_old():
    out = load_plugin("java-doctor").evaluate(11, 17)
    assert out["ok"] is False
    assert "11" in out["reason"] and "17" in out["reason"]


def test_evaluate_fails_when_unparsable():
    out = load_plugin("java-doctor").evaluate(None, 17)
    assert out["ok"] is False
    assert out["found"] is None

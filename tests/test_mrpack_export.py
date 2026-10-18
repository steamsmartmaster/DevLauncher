# -*- coding: utf-8 -*-
"""mrpack 导出（launcher_core.modpack_importer）与 dependencies 键名解析。

格式契约按 Modrinth 官方文档：modrinth.index.json 必须在 zip 根、UTF-8；
dependencies 只有 minecraft / forge / neoforge / fabric-loader / quilt-loader
五个键。本地导出拿不到 Modrinth 下载链接，所以模组走 overrides/mods/——
本仓 _import_modrinth 会把 overrides/* 解到版本目录，因此可以零网络往返。
"""
import json
import zipfile
from pathlib import Path

from launcher_core.modpack_importer import (
    ModpackImporter,
    loader_from_dependencies,
)

OVERRIDES_DIRS = ("mods", "config", "resourcepacks", "shaderpacks", "defaultconfigs")


def make_instance(tmp_path, name="MyPack", mc="1.20.1", loader="fabric",
                  loader_ver="0.16.5"):
    mc_dir = Path(tmp_path) / ".minecraft"
    vdir = mc_dir / "versions" / name
    (vdir / "mods").mkdir(parents=True)
    (vdir / "config").mkdir(parents=True)
    (vdir / "mods" / "sodium.jar").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    (vdir / "mods" / "iris.jar").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    (vdir / "mods" / "sodium.jar.part").write_bytes(b"half written")
    (vdir / "config" / "sodium-options.txt").write_text("quality=fast", encoding="utf-8")
    lib = {
        "fabric": f"net.fabricmc:fabric-loader:{loader_ver}",
        "forge": f"net.minecraftforge:forge:{loader_ver}",
        "neoforge": f"net.neoforged:neoforge:{loader_ver}",
        "quilt": f"org.quiltmc:quilt-loader:{loader_ver}",
    }[loader]
    (vdir / f"{name}.json").write_text(json.dumps({
        "id": name,
        "inheritsFrom": mc,
        "libraries": [{"name": lib}],
    }), encoding="utf-8")
    return mc_dir, vdir


def read_index(mrpack_path):
    with zipfile.ZipFile(mrpack_path) as zf:
        return json.loads(zf.read("modrinth.index.json").decode("utf-8"))


def test_export_writes_index_at_zip_root():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mc_dir, _ = make_instance(tmp)
        out = ModpackImporter(mc_dir).export_mrpack("MyPack")
        assert out["success"] is True, out
        with zipfile.ZipFile(out["path"]) as zf:
            assert "modrinth.index.json" in zf.namelist()


def test_export_index_uses_official_top_level_fields():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mc_dir, _ = make_instance(tmp)
        index = read_index(ModpackImporter(mc_dir).export_mrpack("MyPack")["path"])
        assert index["formatVersion"] == 1
        assert index["game"] == "minecraft"
        assert index["versionId"]
        assert index["name"] == "MyPack"
        assert isinstance(index["files"], list)


def test_export_dependencies_use_official_loader_keys():
    import tempfile
    cases = [
        ("fabric", "fabric-loader"),
        ("quilt", "quilt-loader"),
        ("forge", "forge"),
        ("neoforge", "neoforge"),
    ]
    for loader, dep_key in cases:
        with tempfile.TemporaryDirectory() as tmp:
            mc_dir, _ = make_instance(tmp, loader=loader, loader_ver="1.2.3")
            index = read_index(ModpackImporter(mc_dir).export_mrpack("MyPack")["path"])
            assert index["dependencies"]["minecraft"] == "1.20.1"
            assert index["dependencies"][dep_key] == "1.2.3", (loader, index["dependencies"])


def test_export_mods_land_in_overrides_and_skip_partial_files():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mc_dir, _ = make_instance(tmp)
        path = ModpackImporter(mc_dir).export_mrpack("MyPack")["path"]
        with zipfile.ZipFile(path) as zf:
            names = sorted(n for n in zf.namelist() if n.startswith("overrides/mods/"))
        assert names == ["overrides/mods/iris.jar", "overrides/mods/sodium.jar"]
        assert not any(n.endswith(".part") for n in names)


def test_export_config_land_in_overrides():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mc_dir, _ = make_instance(tmp)
        path = ModpackImporter(mc_dir).export_mrpack("MyPack")["path"]
        with zipfile.ZipFile(path) as zf:
            assert "overrides/config/sodium-options.txt" in zf.namelist()


def test_export_reports_counts_and_no_remote_files():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mc_dir, _ = make_instance(tmp)
        out = ModpackImporter(mc_dir).export_mrpack("MyPack")
        assert out["mod_count"] == 2
        assert out["override_count"] >= 3
        index = read_index(out["path"])
        assert index["files"] == []


def test_export_respects_explicit_output_path():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mc_dir, _ = make_instance(tmp)
        target = Path(tmp) / "out" / "pack.mrpack"
        target.parent.mkdir()
        out = ModpackImporter(mc_dir).export_mrpack("MyPack", str(target))
        assert out["success"] is True
        assert Path(out["path"]) == target
        assert target.exists()


def test_export_default_path_is_inside_minecraft_dir():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mc_dir, _ = make_instance(tmp)
        out = ModpackImporter(mc_dir).export_mrpack("MyPack")
        assert Path(out["path"]).parent == mc_dir
        assert Path(out["path"]).name == "MyPack.mrpack"


def test_export_missing_instance_fails_cleanly():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = ModpackImporter(Path(tmp) / ".minecraft").export_mrpack("NoSuchPack")
        assert out["success"] is False
        assert out["error"]


def test_export_empty_mods_still_produces_valid_pack():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mc_dir, _ = make_instance(tmp)
        for jar in (Path(tmp) / ".minecraft" / "versions" / "MyPack" / "mods").glob("*.jar"):
            jar.unlink()
        out = ModpackImporter(mc_dir).export_mrpack("MyPack")
        assert out["success"] is True
        assert out["mod_count"] == 0
        assert read_index(out["path"])["dependencies"]["minecraft"] == "1.20.1"


def test_export_round_trips_through_this_repo_importer():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mc_dir, _ = make_instance(tmp)
        importer = ModpackImporter(mc_dir)
        path = importer.export_mrpack("MyPack")["path"]

        assert importer.detect_format(path) == "modrinth"
        info = importer.read_manifest(path)
        assert info.format == "modrinth"
        assert info.name == "MyPack"
        assert info.minecraft_version == "1.20.1"
        assert info.mod_loader == "fabric"
        assert info.mod_loader_version == "0.16.5"
        assert info.mod_count == 0

        target = Path(tmp) / "restored" / "versions" / "Restored"
        target.mkdir(parents=True)
        with zipfile.ZipFile(path) as zf:
            for item in zf.infolist():
                if item.filename.startswith("overrides/") and not item.is_dir():
                    rel = item.filename[len("overrides/"):]
                    dst = target / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(zf.read(item.filename))
        assert (target / "mods" / "sodium.jar").exists()
        assert (target / "mods" / "iris.jar").exists()
        assert (target / "config" / "sodium-options.txt").exists()


def test_loader_from_dependencies_neoforge_is_not_read_as_forge():
    assert loader_from_dependencies({"minecraft": "1.20.1", "neoforge": "20.4.237"}) == (
        "neoforge", "20.4.237")


def test_loader_from_dependencies_covers_all_official_keys():
    assert loader_from_dependencies({"minecraft": "1.21.1", "fabric-loader": "0.16.5"}) == (
        "fabric", "0.16.5")
    assert loader_from_dependencies({"minecraft": "1.21.1", "quilt-loader": "0.26.3"}) == (
        "quilt", "0.26.3")
    assert loader_from_dependencies({"minecraft": "1.20.1", "forge": "47.2.0"}) == (
        "forge", "47.2.0")


def test_loader_from_dependencies_vanilla_when_no_loader_key():
    assert loader_from_dependencies({"minecraft": "1.21.1"}) == ("", "")
    assert loader_from_dependencies({}) == ("", "")
    assert loader_from_dependencies(None) == ("", "")


def test_loader_from_dependencies_ignores_unknown_keys():
    assert loader_from_dependencies(
        {"minecraft": "1.21.1", "neoforge": "20.4", "something-new": "1.0"}) == (
        "neoforge", "20.4")

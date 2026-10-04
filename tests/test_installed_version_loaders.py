# -*- coding: utf-8 -*-
"""get_installed_versions 附加 loaders 字段（版本卡右下角角标数据源）。

修复：整合包版本 id（如 "Fabulously Optimized 13.2.2 for 26.1.2"）不含
-<Loader>- 段，仅靠 id 正则会误判原版 → 列表条目附带实际安装的 loaders。
检测复用 api_modloaders.get_installed_loaders（跟随 inheritsFrom 链），
与「模组加载器」详情页同源。
"""
import json
from pathlib import Path

from launcher_core.versions import VersionManager


def _mk_version(minecraft_dir, vid, libs=None, inherits_from=None, with_cfg=False):
    vdir = Path(minecraft_dir) / "versions" / vid
    vdir.mkdir(parents=True, exist_ok=True)
    data = {"id": vid, "type": "release", "releaseTime": "2026-01-01T00:00:00+00:00",
            "libraries": libs or []}
    if inherits_from:
        data["inheritsFrom"] = inherits_from
    (vdir / f"{vid}.json").write_text(json.dumps(data), encoding="utf-8")
    if with_cfg:
        (vdir / "devlauncher.cfg").write_text("{}", encoding="utf-8")
    return vdir


FABRIC_LIB = {"name": "net.fabricmc:fabric-loader:0.19.3"}
FORGE_LIB = {"name": "net.minecraftforge:forge:47.3.0"}


def test_modpack_entry_has_loaders(tmp_path):
    _mk_version(tmp_path, "Fabulously Optimized 13.2.2 for 26.1.2",
                libs=[FABRIC_LIB], inherits_from="26.1.2")
    items = VersionManager(str(tmp_path)).get_installed_versions()
    me = [i for i in items if i["id"].startswith("Fabulously")][0]
    assert "loaders" in me, "条目应含 loaders 字段"
    assert me["loaders"][0]["type"] == "fabric"
    assert me["loaders"][0]["version"] == "0.19.3"


def test_entry_without_loader_has_empty_list(tmp_path):
    _mk_version(tmp_path, "SomePack", libs=[], inherits_from="1.20.1")
    items = VersionManager(str(tmp_path)).get_installed_versions()
    me = [i for i in items if i["id"] == "SomePack"][0]
    assert me["loaders"] == []


def test_loader_in_parent_json_detected(tmp_path):
    # 整合包自身 json 无 loader，loader 装在 inheritsFrom 的父版本 json
    _mk_version(tmp_path, "26.1.2", libs=[FABRIC_LIB])
    _mk_version(tmp_path, "ChildPack", libs=[], inherits_from="26.1.2")
    items = VersionManager(str(tmp_path)).get_installed_versions()
    me = [i for i in items if i["id"] == "ChildPack"][0]
    assert me["loaders"][0]["type"] == "fabric"


def test_old_fields_unchanged(tmp_path):
    _mk_version(tmp_path, "PlainPack", libs=[FORGE_LIB], with_cfg=True)
    items = VersionManager(str(tmp_path)).get_installed_versions()
    me = items[0]
    assert {"id", "type", "releaseTime", "inheritsFrom", "has_cfg"} <= set(me.keys())
    assert me["id"] == "PlainPack"
    assert me["has_cfg"] is True
    # forge 也能被识别（多 loader 类型不止 fabric）
    assert me["loaders"][0]["type"] == "forge"

"""版本管理页"文件目录"功能 (TDD RED/GREEN)

- get_game_dir: 隔离开启 -> versions/<id>/, 关闭 -> .minecraft 根目录
- list_version_folders: 列子目录, 识别映射为中文名, 未识别显示原名, 识别项在前
- resolve_folder: 打开前校验 (存在/是目录/不越出游戏目录)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from launcher_core.versions import VersionManager  # noqa: E402


def make_manager(tmp_path) -> VersionManager:
    mc = tmp_path / "minecraft"
    mc.mkdir(parents=True, exist_ok=True)
    return VersionManager(str(mc))


def make_version(manager: VersionManager, vid: str, isolation: bool) -> Path:
    vdir = Path(manager.minecraft_dir) / "versions" / vid
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / f"{vid}.json").write_text(json.dumps({"id": vid, "type": "release"}), encoding="utf-8")
    if isolation:
        (vdir / "devlauncher.cfg").write_text(json.dumps({"isolation": True}), encoding="utf-8")
    return vdir


# ---------------- get_game_dir ----------------

def test_game_dir_isolated(tmp_path):
    m = make_manager(tmp_path)
    vdir = make_version(m, "iso-1.20.1", isolation=True)
    assert m.get_game_dir("iso-1.20.1") == vdir


def test_game_dir_not_isolated(tmp_path):
    m = make_manager(tmp_path)
    make_version(m, "plain-1.20.1", isolation=False)
    assert m.get_game_dir("plain-1.20.1") == Path(m.minecraft_dir)


def test_game_dir_unknown_version_falls_back_to_root(tmp_path):
    m = make_manager(tmp_path)
    assert m.get_game_dir("nope") == Path(m.minecraft_dir)


# ---------------- list_version_folders ----------------

def test_list_labels_and_order(tmp_path):
    m = make_manager(tmp_path)
    vdir = make_version(m, "iso", isolation=True)
    for name in ["mods", "saves", "shaderpacks", "config", "logs",
                 "a_mod_special", "JourneyMapData"]:
        (vdir / name).mkdir()
    (vdir / "file.txt").write_text("x")  # 非目录应被忽略

    result = m.list_version_folders("iso")
    assert result["path"] == str(vdir)
    folders = result["folders"]
    names = [f["name"] for f in folders]

    # 非目录不出现, 全部子目录都出现
    assert "file.txt" not in names
    assert set(names) == {"mods", "saves", "shaderpacks", "config", "logs",
                          "a_mod_special", "JourneyMapData"}

    # 识别映射为中文名
    by_name = {f["name"]: f for f in folders}
    assert by_name["mods"]["label"] == "模组文件夹"
    assert by_name["mods"]["recognized"] is True
    assert by_name["saves"]["label"] == "世界文件夹"
    assert by_name["saves"]["recognized"] is True
    assert by_name["shaderpacks"]["label"] == "光影文件夹"
    assert by_name["config"]["label"] == "配置文件夹"
    assert by_name["logs"]["label"] == "日志文件夹"

    # 未识别显示原名
    assert by_name["a_mod_special"]["label"] == "a_mod_special"
    assert by_name["a_mod_special"]["recognized"] is False
    assert by_name["JourneyMapData"]["label"] == "JourneyMapData"
    assert by_name["JourneyMapData"]["recognized"] is False

    # 识别项按 FOLDER_LABELS 映射序在前, 未识别按字母序在后
    from launcher_core.versions import FOLDER_LABELS
    rec = [n for n in names if by_name[n]["recognized"]]
    unrec = [n for n in names if not by_name[n]["recognized"]]
    assert names == rec + unrec
    assert rec == [n for n in FOLDER_LABELS if n in rec]
    assert unrec == sorted(unrec, key=str.lower)
    assert rec[0] == "mods"  # 模组最常用, 映射表首位


def test_list_non_isolated_scans_game_root(tmp_path):
    m = make_manager(tmp_path)
    make_version(m, "plain", isolation=False)
    (Path(m.minecraft_dir) / "mods").mkdir(exist_ok=True)
    (Path(m.minecraft_dir) / "versions").mkdir(exist_ok=True)
    result = m.list_version_folders("plain")
    assert result["path"] == str(m.minecraft_dir)
    names = [f["name"] for f in result["folders"]]
    assert "mods" in names and "versions" in names
    by_name = {f["name"]: f for f in result["folders"]}
    assert by_name["mods"]["label"] == "模组文件夹"
    assert by_name["versions"]["recognized"] is False  # 未识别 → 原名


def test_list_empty_dir(tmp_path):
    m = make_manager(tmp_path)
    vdir = make_version(m, "iso2", isolation=True)
    result = m.list_version_folders("iso2")
    assert result["path"] == str(vdir)
    assert result["folders"] == []


# ---------------- resolve_folder (打开校验) ----------------

def test_resolve_valid_subfolder(tmp_path):
    m = make_manager(tmp_path)
    vdir = make_version(m, "iso", isolation=True)
    (vdir / "mods").mkdir()
    assert m.resolve_folder("iso", "mods") == vdir / "mods"


def test_resolve_root_with_empty_subfolder(tmp_path):
    m = make_manager(tmp_path)
    vdir = make_version(m, "iso", isolation=True)
    assert m.resolve_folder("iso", "") == vdir


def test_resolve_rejects_traversal(tmp_path):
    m = make_manager(tmp_path)
    vdir = make_version(m, "iso", isolation=True)
    (vdir / "mods").mkdir()
    assert m.resolve_folder("iso", "../..") is None
    assert m.resolve_folder("iso", "..") is None
    assert m.resolve_folder("iso", "mods/../../..") is None


def test_resolve_rejects_absolute(tmp_path):
    m = make_manager(tmp_path)
    vdir = make_version(m, "iso", isolation=True)
    (vdir / "mods").mkdir()
    assert m.resolve_folder("iso", str(tmp_path)) is None
    assert m.resolve_folder("iso", "C:\\Windows") is None


def test_resolve_rejects_missing_or_file(tmp_path):
    m = make_manager(tmp_path)
    vdir = make_version(m, "iso", isolation=True)
    (vdir / "afile.txt").write_text("x")
    assert m.resolve_folder("iso", "not_exists") is None
    assert m.resolve_folder("iso", "afile.txt") is None


def test_resolve_non_isolated_root(tmp_path):
    m = make_manager(tmp_path)
    make_version(m, "plain", isolation=False)
    (Path(m.minecraft_dir) / "saves").mkdir()
    assert m.resolve_folder("plain", "saves") == Path(m.minecraft_dir) / "saves"
    assert m.resolve_folder("plain", "") == Path(m.minecraft_dir)

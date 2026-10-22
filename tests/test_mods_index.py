"""模组列表快速索引（modsIndex）：先发文件名骨架，再发完整元数据。

后端在扫描 jar 之前先 emit 一份轻量列表，前端据此立刻画出占位卡片；
完整列表随后照旧通过 modsLoaded 送达并逐帧替换。
"""
import json
import os
import time
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parent.parent


def _source(name):
    return (REPO / name).read_text(encoding="utf-8")


def _make_jar(path: Path, mod_id: str, name: str, version: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({
            "id": mod_id,
            "name": name,
            "version": version,
            "description": "test mod",
            "authors": ["tester"],
        }))


class _Settings:
    def __init__(self, base: Path):
        self.base = str(base)

    def get(self, key, default=None):
        if key == "minecraft_dir":
            return self.base
        return default


class _Versions:
    def get_mods_path(self, version_id: str):
        raise AssertionError("loadMods('') should not hit VersionManager")


def _collect(tmp_path: Path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from main import LauncherBridge

    app = QApplication.instance() or QApplication([])
    bridge = LauncherBridge(
        auth=object(), versions=_Versions(), game=object(),
        settings=_Settings(tmp_path), mods=object(),
    )
    events = []
    bridge.modsIndex.connect(
        lambda s: events.append(("index", s)), Qt.ConnectionType.DirectConnection
    )
    bridge.modsLoaded.connect(
        lambda s: events.append(("full", s)), Qt.ConnectionType.DirectConnection
    )
    bridge.loadMods("")

    deadline = time.time() + 30
    while time.time() < deadline:
        if any(kind == "full" for kind, _ in events):
            break
        time.sleep(0.02)
    assert any(kind == "full" for kind, _ in events), "modsLoaded never emitted"
    assert app is not None
    return events


def test_source_emits_index_before_metadata_scan():
    src = _source("main.py")
    assert "modsIndex = pyqtSignal(str)" in src
    emit_idx = src.index("self.modsIndex.emit(")
    modinfo_idx = src.index("from launcher_core.mod_manager import ModInfo")
    assert emit_idx < modinfo_idx, "索引必须在读取 jar 元数据之前发出"
    assert "def _on_mods_index(" in src
    assert 'f"updateModIndex({index_json})"' in src
    assert "self.bridge.modsIndex.connect(self._on_mods_index)" in src


def test_index_payload_is_filename_only():
    src = _source("ui/index.html")
    assert "function updateModIndex(index)" in src
    assert "var MOD_FIRST_BATCH = 15;" in src
    assert "modItemHtml(index[i], true)" in src


def test_index_emitted_first_and_matches_mods(tmp_path):
    mods_dir = tmp_path / "mods"
    _make_jar(mods_dir / "alpha.jar", "alpha", "Alpha Mod", "1.0.0")
    _make_jar(mods_dir / "beta.jar", "beta", "Beta Mod", "2.0.0")
    _make_jar(mods_dir / "gamma.jar.disabled", "gamma", "Gamma Mod", "3.0.0")

    events = _collect(tmp_path)
    kinds = [k for k, _ in events]
    assert kinds[0] == "index", kinds
    assert kinds[-1] == "full", kinds

    index = json.loads(events[0][1])
    assert [row["filename"] for row in index] == [
        "alpha.jar", "beta.jar", "gamma.jar.disabled"
    ]
    for row in index:
        assert set(row) == {"filename", "enabled"}, row
    assert [row["enabled"] for row in index] == [True, True, False]

    mods = json.loads(events[-1][1])
    assert [m["filename"] for m in mods] == [r["filename"] for r in index]
    assert [m["name"] for m in mods] == ["Alpha Mod", "Beta Mod", "gamma"]
    assert mods[2]["enabled"] is False

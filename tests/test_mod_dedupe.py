"""客户端 jar 去重：同 mods 目录内按 mod_id 清理旧版本（修「两个 Meteor」重复）"""
import json
import zipfile
from pathlib import Path

from launcher_core.mod_manager import remove_stale_client_mods


def _mk_jar(path: Path, mod_id: str, version: str = "1.0") -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({
            "id": mod_id, "version": version, "name": mod_id, "schemaVersion": 1
        }))
    return path


def test_removes_same_mod_id_old_versions(tmp_path):
    new = _mk_jar(tmp_path / "meteor-client-1.21.6-7.jar", "meteor-client", "1.21.6-7")
    old = _mk_jar(tmp_path / "meteor-client-1.21.5-54.jar", "meteor-client", "1.21.5-54")
    removed = remove_stale_client_mods(new)
    assert removed == ["meteor-client-1.21.5-54.jar"], removed
    assert new.exists()
    assert not old.exists()


def test_keeps_other_mods(tmp_path):
    new = _mk_jar(tmp_path / "meteor-client-1.21.6-7.jar", "meteor-client")
    sodium = _mk_jar(tmp_path / "sodium-0.6.0.jar", "sodium")
    removed = remove_stale_client_mods(new)
    assert removed == [], removed
    assert new.exists() and sodium.exists()


def test_jar_without_mod_id_is_noop(tmp_path):
    plain = tmp_path / "plain.jar"
    plain.write_bytes(b"not a zip")
    other = _mk_jar(tmp_path / "meteor-client-1.21.5-54.jar", "meteor-client")
    removed = remove_stale_client_mods(plain)
    assert removed == [], removed
    assert plain.exists() and other.exists()


def test_missing_file_is_noop(tmp_path):
    assert remove_stale_client_mods(tmp_path / "nope.jar") == []


def test_multiple_stale_versions_all_removed(tmp_path):
    new = _mk_jar(tmp_path / "lb.jar", "liquidbounce")
    a = _mk_jar(tmp_path / "lb-old-a.jar", "liquidbounce")
    b = _mk_jar(tmp_path / "lb-old-b.jar", "liquidbounce")
    c = _mk_jar(tmp_path / "other.jar", "other-mod")
    removed = remove_stale_client_mods(new)
    assert sorted(removed) == ["lb-old-a.jar", "lb-old-b.jar"], removed
    assert new.exists() and c.exists()

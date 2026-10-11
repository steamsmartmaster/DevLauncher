"""客户端 jar 去重：同 mods 目录内按 mod_id 清理旧版本（修「两个 Meteor」重复）

另含官网 zip 包解包提取（LiquidBounce S3 直链产物是 zip，内含 liquidbounce.jar）。
"""
import json
import zipfile
from pathlib import Path

import pytest

from launcher_core.mod_manager import extract_client_mod_jar, remove_stale_client_mods


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


def _mk_bundle(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


def test_extract_client_mod_jar_from_bundle(tmp_path):
    """官网 zip 包（liquidbounce.jar + 推广 URL 文本）→ 提取 jar、删 zip、返回 jar 路径。"""
    jar_bytes = b"PK\x03\x04fake-jar"
    bundle = _mk_bundle(tmp_path / "liquidbounce-826ee0e.zip", {
        "liquidbounce.jar": jar_bytes,
        "README.txt": b"readme",
        "FORUM.URL": b"https://forum.liquidbounce.net",
    })
    out = extract_client_mod_jar(bundle)
    assert out == tmp_path / "liquidbounce.jar"
    assert out.read_bytes() == jar_bytes
    assert not bundle.exists(), "解包后 zip 应删除"


def test_extract_client_mod_jar_nested_entry(tmp_path):
    """zip 内条目带目录前缀 → 提取到同级平铺（mods 目录只认一层）。"""
    jar_bytes = b"PK\x03\x04nested"
    bundle = _mk_bundle(tmp_path / "pack.zip", {"sub/dir/client.jar": jar_bytes})
    out = extract_client_mod_jar(bundle)
    assert out == tmp_path / "client.jar"
    assert out.read_bytes() == jar_bytes


def test_extract_client_mod_jar_without_jar_raises(tmp_path):
    """zip 内无 .jar → 报错且保留 zip 便于排查。"""
    bundle = _mk_bundle(tmp_path / "empty.zip", {"README.txt": b"x"})
    with pytest.raises(RuntimeError):
        extract_client_mod_jar(bundle)
    assert bundle.exists()

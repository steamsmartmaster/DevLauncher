"""客户端实例化安装：ModpackImporter.install_client_instance + main.py 编排静态断言"""
import re
from pathlib import Path

import pytest

from launcher_core.modpack_importer import ModpackImporter

ROOT = Path(__file__).resolve().parents[1]


def test_install_client_instance_recipe(tmp_path, monkeypatch):
    imp = ModpackImporter(tmp_path)
    calls = []

    def fake_vanilla(mc, report):
        calls.append(("vanilla", mc))
        report(91, 100, "x")

    def fake_json(version_dir, version_name, mc, loader, loader_version):
        calls.append(("json", version_name, mc, loader, loader_version))
        (version_dir / f"{version_name}.json").write_text("{}", encoding="utf-8")

    def fake_loader(version_name, loader, loader_version, report):
        calls.append(("loader", version_name, loader, loader_version))
        return "warn-x"

    monkeypatch.setattr(imp, "_ensure_vanilla_version", fake_vanilla)
    monkeypatch.setattr(imp, "_create_version_json", fake_json)
    monkeypatch.setattr(imp, "_install_loader_for_import", fake_loader)

    reports = []
    out = imp.install_client_instance("Meteor Client", "26.3", "fabric", "0.17.2",
                                      lambda c, t, m: reports.append((c, m)))
    # 目录与隔离
    vdir = tmp_path / "versions" / "Meteor Client"
    assert (vdir / "mods").is_dir() and (vdir / "config").is_dir()
    assert (vdir / "Meteor Client.json").is_file()
    # 四件套调用顺序
    assert [c[0] for c in calls] == ["vanilla", "json", "loader"]
    assert calls[0][1] == "26.3"
    assert calls[1] == ("json", "Meteor Client", "26.3", "fabric", "0.17.2")
    assert out == {"version_name": "Meteor Client", "warning": "warn-x"}
    # 首个进度为实例准备(90)，且原版步骤(91)也已上报
    assert reports and reports[0][0] == 90 and any(r[0] == 91 for r in reports)


def test_install_client_instance_idempotent(tmp_path, monkeypatch):
    imp = ModpackImporter(tmp_path)
    monkeypatch.setattr(imp, "_ensure_vanilla_version", lambda mc, r: None)
    monkeypatch.setattr(imp, "_create_version_json", lambda *a: None)
    monkeypatch.setattr(imp, "_install_loader_for_import", lambda *a: "")
    a = imp.install_client_instance("X", "26.3", "fabric", "0.17.2", lambda *a: None)
    b = imp.install_client_instance("X", "26.3", "fabric", "0.17.2", lambda *a: None)
    assert a == b  # 同名重装幂等


def test_install_client_instance_propagates_vanilla_failure(tmp_path, monkeypatch):
    imp = ModpackImporter(tmp_path)

    def boom(mc, report):
        raise RuntimeError("无法下载原版 Minecraft 9.9.9")

    monkeypatch.setattr(imp, "_ensure_vanilla_version", boom)
    with pytest.raises(RuntimeError, match="9.9.9"):
        imp.install_client_instance("Y", "9.9.9", "fabric", "0.17.2", lambda *a: None)


def test_download_client_version_orchestration_static():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    m = re.search(r"def downloadClientVersion\(self[\s\S]{0,14000}", src)
    assert m, "downloadClientVersion 应存在"
    body = m.group(0)
    for needle in ("install_client_instance(", "resolve_client_mc_version(",
                   "get_recommended_loaders(", "modpackImportComplete.emit",
                   "clientDownloadFinished.emit", "meteor_api.get_jar",
                   "downloadModpackVersion("):
        assert needle in body, f"编排体内应含 {needle}"


def test_download_dedupes_stale_mods_static():
    """jar 落盘后按 mod_id 去重：修重复下载同一客户端累积多个 jar（双 Meteor）"""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    m = re.search(r"def downloadClientVersion\(self[\s\S]{0,14000}", src)
    assert m, "downloadClientVersion 应存在"
    body = m.group(0)
    assert "remove_stale_client_mods(" in body, "jar 下载成功后应调用同 mod_id 去重"
    dl_at = body.index("modrinth_api.download_file(url")
    dedup_at = body.index("remove_stale_client_mods(")
    assert dl_at < dedup_at, "去重应在 jar 下载成功之后调用"
    mm = (ROOT / "launcher_core" / "mod_manager.py").read_text(encoding="utf-8")
    assert "def remove_stale_client_mods(" in mm, "mod_manager 应提供 remove_stale_client_mods"


def test_latest_release_helper_available():
    import minecraft_launcher_lib.utils as mllu
    assert callable(mllu.get_latest_version)

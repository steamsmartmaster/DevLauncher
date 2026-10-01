"""frozen（PyInstaller 打包）模式路径解析：运行时数据必须落在 exe 同目录（持久），而非临时解包目录。"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_app_base_dir_dev_mode_is_repo_root(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    from launcher_core.paths import app_base_dir
    assert app_base_dir() == REPO_ROOT


def test_app_base_dir_frozen_is_exe_dir(monkeypatch, tmp_path):
    exe = tmp_path / "DevLauncher.exe"
    exe.write_bytes(b"fake")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    from launcher_core.paths import app_base_dir
    assert app_base_dir() == tmp_path


def test_plugin_manager_default_dir_frozen_next_to_exe(monkeypatch, tmp_path):
    exe = tmp_path / "DevLauncher.exe"
    exe.write_bytes(b"fake")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    from launcher_core.plugins import PluginManager
    mgr = PluginManager()
    assert mgr.plugins_dir == tmp_path / "plugins"


def test_plugin_manager_default_dir_dev_is_repo_plugins(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    from launcher_core.plugins import PluginManager
    mgr = PluginManager()
    assert mgr.plugins_dir == REPO_ROOT / "plugins"


def test_main_log_dir_uses_app_base_dir():
    src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    assert "app_base_dir() / \"logs\"" in src
    assert "Path(__file__).parent / \"logs\"" not in src

def test_main_guards_stdout_none_for_windowed_build():
    # PyInstaller --windowed 下 sys.stdout 为 None，StreamHandler 需回退
    src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    assert "sys.stdout if sys.stdout is not None" in src

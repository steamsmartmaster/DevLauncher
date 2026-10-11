# -*- coding: utf-8 -*-
"""QtWebEngine Chromium flags 内存优化（launcher_core.webengine_flags）。

背景：QtWebEngine 的 GPU/合成器内存默认挤在主进程（in-process GPU），
三个 GPU flags 把提交内存从 275MB 降到 207MB（-67.5MB，实测）。
"""
from pathlib import Path

from launcher_core import webengine_flags
from launcher_core.webengine_flags import WEBENGINE_CHROMIUM_FLAGS, merge_chromium_flags


def _no_system_proxy(monkeypatch):
    monkeypatch.setattr(webengine_flags, "_read_system_proxy", lambda: "")


def test_default_flags_contain_gpu_savings():
    for flag in ("--disable-gpu", "--in-process-gpu", "--disable-gpu-compositing"):
        assert flag in WEBENGINE_CHROMIUM_FLAGS, flag


def test_merge_when_unset_or_empty(monkeypatch):
    _no_system_proxy(monkeypatch)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(k, raising=False)
    assert merge_chromium_flags(None) == WEBENGINE_CHROMIUM_FLAGS
    assert merge_chromium_flags("") == WEBENGINE_CHROMIUM_FLAGS
    assert merge_chromium_flags("   ") == WEBENGINE_CHROMIUM_FLAGS


def test_merge_preserves_user_flags(monkeypatch):
    _no_system_proxy(monkeypatch)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(k, raising=False)
    out = merge_chromium_flags("--enable-logging --log-level=3")
    assert "--enable-logging" in out
    assert "--disable-gpu" in out
    assert out.startswith("--enable-logging")


def test_merge_idempotent_when_already_present(monkeypatch):
    _no_system_proxy(monkeypatch)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(k, raising=False)
    once = merge_chromium_flags("--enable-logging")
    assert merge_chromium_flags(once) == once


def test_parse_ie_proxy_forms():
    # 系统代理 ProxyServer 两种形态：全协议单值 / 分号键值对（https 优先）
    assert webengine_flags.parse_ie_proxy("127.0.0.1:7890") == "127.0.0.1:7890"
    assert webengine_flags.parse_ie_proxy(
        "http=127.0.0.1:7891;https=127.0.0.1:7890;socks=127.0.0.1:7892") == "127.0.0.1:7890"
    assert webengine_flags.parse_ie_proxy("http=127.0.0.1:7891") == "127.0.0.1:7891"
    assert webengine_flags.parse_ie_proxy("socks=127.0.0.1:7892") == "127.0.0.1:7892"
    assert webengine_flags.parse_ie_proxy("") == ""
    assert webengine_flags.parse_ie_proxy("  ") == ""


def test_system_proxy_fallback_when_no_env(monkeypatch):
    # 双击启动无环境变量，浏览器能开因走系统代理 → app 也必须回退读系统代理
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(webengine_flags, "_read_system_proxy", lambda: "127.0.0.1:7890")
    out = merge_chromium_flags("")
    assert "--proxy-server=http://127.0.0.1:7890" in out, out
    assert "--disable-gpu" in out


def test_env_proxy_beats_system_proxy(monkeypatch):
    # Windows os.environ 大小写不敏感：必须先删后设，否则 delenv("https_proxy")
    # 会把刚 setenv 的 HTTPS_PROXY 一起删掉
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10808")
    monkeypatch.setattr(webengine_flags, "_read_system_proxy", lambda: "127.0.0.1:7890")
    out = merge_chromium_flags("")
    assert "--proxy-server=http://127.0.0.1:10808" in out, out
    assert "7890" not in out


def test_reads_windows_registry_system_proxy():
    src = Path(webengine_flags.__file__).read_text(encoding="utf-8")
    assert "winreg" in src, "应回退读 Windows 注册表系统代理"
    assert "ProxyEnable" in src and "ProxyServer" in src, "应读 WinINET 两键"


def test_main_wires_flags_before_qapplication():
    src = Path(__file__).resolve().parent.parent.joinpath("main.py").read_text(encoding="utf-8")
    set_idx = src.index("QTWEBENGINE_CHROMIUM_FLAGS")
    app_idx = src.index("QApplication(")
    assert set_idx < app_idx, "flags 必须在 QApplication 构造前注入"
    assert "merge_chromium_flags" in src

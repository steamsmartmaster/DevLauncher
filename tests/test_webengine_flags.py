# -*- coding: utf-8 -*-
"""QtWebEngine Chromium flags 内存优化（launcher_core.webengine_flags）。

背景：QtWebEngine 的 GPU/合成器内存默认挤在主进程（in-process GPU），
三个 GPU flags 把提交内存从 275MB 降到 207MB（-67.5MB，实测）。
"""
from pathlib import Path

from launcher_core.webengine_flags import WEBENGINE_CHROMIUM_FLAGS, merge_chromium_flags


def test_default_flags_contain_gpu_savings():
    for flag in ("--disable-gpu", "--in-process-gpu", "--disable-gpu-compositing"):
        assert flag in WEBENGINE_CHROMIUM_FLAGS, flag


def test_merge_when_unset_or_empty():
    assert merge_chromium_flags(None) == WEBENGINE_CHROMIUM_FLAGS
    assert merge_chromium_flags("") == WEBENGINE_CHROMIUM_FLAGS
    assert merge_chromium_flags("   ") == WEBENGINE_CHROMIUM_FLAGS


def test_merge_preserves_user_flags():
    out = merge_chromium_flags("--enable-logging --log-level=3")
    assert "--enable-logging" in out
    assert "--disable-gpu" in out
    assert out.startswith("--enable-logging")


def test_merge_idempotent_when_already_present():
    once = merge_chromium_flags("--enable-logging")
    assert merge_chromium_flags(once) == once


def test_main_wires_flags_before_qapplication():
    src = Path(__file__).resolve().parent.parent.joinpath("main.py").read_text(encoding="utf-8")
    set_idx = src.index("QTWEBENGINE_CHROMIUM_FLAGS")
    app_idx = src.index("QApplication(")
    assert set_idx < app_idx, "flags 必须在 QApplication 构造前注入"
    assert "merge_chromium_flags" in src

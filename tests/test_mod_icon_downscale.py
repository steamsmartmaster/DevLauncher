"""模组图标压缩：列表载荷从 1.18MB 降到 289KB。

图标在列表里显示为 36 CSS px，原始 256px PNG 的 base64 占了载荷 98%，
还会让每张卡片都做一次大图解码。
"""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parent.parent


def _png(width, height, color="#3366ff"):
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QColor, QImage

    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    assert img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def test_large_icon_is_downscaled():
    from launcher_core.mod_manager import _downscale_icon
    from PyQt6.QtGui import QImage

    raw = _png(256, 256)
    out = _downscale_icon(raw)
    assert out != raw
    img = QImage.fromData(out)
    assert not img.isNull()
    assert max(img.width(), img.height()) <= 72
    assert len(out) < len(raw)


def test_small_icon_is_left_alone():
    from launcher_core.mod_manager import _downscale_icon

    raw = _png(48, 48)
    assert _downscale_icon(raw) is raw


def test_invalid_bytes_are_left_alone():
    from launcher_core.mod_manager import _downscale_icon

    raw = b"not an image"
    assert _downscale_icon(raw) is raw


def test_cache_key_is_versioned():
    src = (REPO / "main.py").read_text(encoding="utf-8")
    assert 'return f"v2|{name}|{st.st_size}|{int(st.st_mtime)}"' in src


def test_icon_data_uri_goes_through_downscale():
    src = (REPO / "launcher_core" / "mod_manager.py").read_text(encoding="utf-8")
    assert "icon_data = _downscale_icon(zf.read(name))" in src
    assert "icon_data = _downscale_icon(cache_file.read_bytes())" in src
    assert "icon_data = _downscale_icon(icon_resp.content)" in src

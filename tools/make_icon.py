"""ui/icon.svg → ui/icon.ico：多尺寸 PNG 直嵌 ICO，供 PyInstaller --icon 使用。

用法：python tools/make_icon.py
依赖：PyQt6（仓库既有运行时依赖，不引入新包）。
"""
import struct
import sys
from pathlib import Path

SIZES = [16, 24, 32, 48, 64, 128, 256]


def build_ico(svg_path: Path, ico_path: Path) -> None:
    from PyQt6.QtCore import QBuffer, QIODevice, QRectF
    from PyQt6.QtGui import QGuiApplication, QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise SystemExit(f"invalid svg: {svg_path}")

    entries = []  # (size, png_bytes)
    for size in SIZES:
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(0x00000000)
        painter = QPainter(img)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        if not img.save(buf, "PNG"):
            raise SystemExit(f"png encode failed at {size}px")
        entries.append((size, bytes(buf.data())))

    count = len(entries)
    offset = 6 + 16 * count
    dir_entries, blob = b"", b""
    for size, png in entries:
        dim = 0 if size >= 256 else size  # ICO 中 0 表示 256
        dir_entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blob += png
        offset += len(png)
    ico_path.write_bytes(struct.pack("<HHH", 0, 1, count) + dir_entries + blob)
    print(f"wrote {ico_path} ({ico_path.stat().st_size} bytes, {count} sizes)")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    build_ico(root / "ui" / "icon.svg", root / "ui" / "icon.ico")


if __name__ == "__main__":
    main()

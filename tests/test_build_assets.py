"""打包资产：自定义 exe 图标、版本资源、构建脚本接线。"""
import struct
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_icon_ico_exists_and_valid():
    ico = REPO_ROOT / "ui" / "icon.ico"
    assert ico.exists(), "缺少 ui/icon.ico（运行 python tools/make_icon.py 生成）"
    data = ico.read_bytes()
    reserved, typ, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, typ) == (0, 1), "不是 ICO 文件头"
    assert count >= 6, f"尺寸数过少: {count}"
    sizes = set()
    for i in range(count):
        w, h, _colors, _res, planes, bpp, length, off = struct.unpack_from(
            "<BBBBHHII", data, 6 + i * 16)
        assert bpp == 32, "应为 32 位色深"
        assert off + length <= len(data), "图标数据越界"
        # PNG 直嵌条目：8 字节签名
        assert data[off:off + 8] == b"\x89PNG\r\n\x1a\n", "图标条目应为 PNG 编码"
        sizes.add(w if w else 256)
    assert {16, 32, 48, 256} <= sizes, f"缺少常用尺寸: {sorted(sizes)}"


def test_version_info_resource():
    vf = REPO_ROOT / "version_info.txt"
    assert vf.exists(), "缺少 version_info.txt"
    text = vf.read_text(encoding="utf-8")
    assert "FileVersion" in text and "1.1.0.0" in text
    assert "ProductName" in text and "DevLauncher" in text
    assert "OriginalFilename" in text and "DevLauncher.exe" in text


def test_build_script_wiring():
    script = REPO_ROOT / "build_exe.ps1"
    assert script.exists(), "缺少 build_exe.ps1"
    text = script.read_text(encoding="utf-8")
    for flag in ("--onefile", "--windowed", "--name DevLauncher",
                 "--icon", "--version-file", '--add-data "ui;ui"'):
        assert flag in text, f"构建脚本缺 {flag}"
    assert "DevLauncher-b1.1-win64.zip" in text or "win64.zip" in text, "未产出发布 zip"
    assert "make_icon.py" in text, "未接图标生成"


def test_make_icon_tool_present_and_compiles():
    import py_compile
    tool = REPO_ROOT / "tools" / "make_icon.py"
    assert tool.exists(), "缺少 tools/make_icon.py"
    py_compile.compile(str(tool), doraise=True)

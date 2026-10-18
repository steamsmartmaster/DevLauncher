"""冒烟判据 + 函数遮蔽模块名的回归。

前者：build_exe.ps1 曾只验「进程存活 + 日志有新写入」，而异常对话框
让两者同时成立，放行了必然崩溃的 exe。

后者：main.py 曾 `from launcher_core.fast_install import fast_install`
（函数），把模块名遮蔽成函数，导致 `fast_install.configure(...)` 抛
AttributeError: 'function' object has no attribute 'configure'。
"""
import ast
import importlib
import inspect
import py_compile
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import smoke_check  # noqa: E402

def _b(text: str) -> bytes:
    return text.encode("utf-8")


CRASH_LOG = _b(
    "2026-10-15 20:44:50,360 [INFO] DevLauncher: MainWindow init\n"
    "2026-10-15 20:44:50,363 [INFO] DevLauncher: Minecraft 目录: D:/mc\n")
BOOT_LINE = _b(smoke_check.BOOT_MARKER + "\n")
VERSIONS_LINE = _b(
    "2026-10-15 20:44:51 [INFO] DevLauncher: 信号: versionsLoaded (length: 918)\n")
FAIL_LINE = _b(
    "2026-10-15 20:44:51 [ERROR] DevLauncher: 获取版本列表失败: timeout\n")


def test_compile_smoke_tool():
    py_compile.compile(str(REPO_ROOT / "tools" / "smoke_check.py"), doraise=True)


def test_smoke_passes_when_boot_and_page_ok():
    ok, detail = smoke_check.check(CRASH_LOG + BOOT_LINE + b"\n" + VERSIONS_LINE)
    assert ok, detail
    assert "versionsLoaded" in detail


def test_smoke_passes_on_offline_page_failure():
    ok, detail = smoke_check.check(CRASH_LOG + BOOT_LINE + b"\n" + FAIL_LINE)
    assert ok, detail
    assert "no-network" in detail


def test_smoke_fails_on_crash_before_init():
    ok, detail = smoke_check.check(CRASH_LOG)
    assert not ok, "崩溃在 configure 处时不应判定启动完成"
    assert smoke_check.BOOT_MARKER in detail


def test_smoke_fails_when_page_never_loaded():
    ok, detail = smoke_check.check(CRASH_LOG + BOOT_LINE + b"\n")
    assert not ok, "缺页面标记说明 QWebChannel/JS 未跑通"
    assert "versionsLoaded" in detail


def test_smoke_cli_reads_offset(tmp_path):
    log = tmp_path / "launcher.log"
    log.write_bytes(CRASH_LOG + BOOT_LINE + VERSIONS_LINE)
    args = ["smoke_check.py", str(log)]
    assert smoke_check.main(args + [str(len(CRASH_LOG))]) == 0
    assert smoke_check.main(args + [str(log.stat().st_size + 10)]) == 1
    assert smoke_check.main(["smoke_check.py", str(tmp_path / "nope.log"), "0"]) == 1
    assert smoke_check.main(["smoke_check.py"]) == 2


def test_build_script_wires_smoke_marker():
    text = (REPO_ROOT / "build_exe.ps1").read_text(encoding="utf-8")
    assert "smoke_check.py" in text, "构建脚本未接入启动完成判据"
    assert "beforeLen" in text, "未记录日志起始偏移"


def _imported_functions(py_file: Path) -> dict:
    """from X import Y 里 Y 若是普通函数，返回 {Y: 模块名}。"""
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("launcher_core"):
            continue
        mod = importlib.import_module(node.module)
        for alias in node.names:
            if inspect.isfunction(getattr(mod, alias.name, None)):
                out[alias.name] = node.module
    return out


def test_no_attribute_access_on_function_imports():
    """函数名同时被当作模块用，就是运行期 AttributeError。"""
    offenders = []
    for py_file in sorted(REPO_ROOT.rglob("*.py")):
        parts = set(py_file.parts)
        if parts & {"build", "dist", ".git", "__pycache__", ".venv", "venv"}:
            continue
        funcs = _imported_functions(py_file)
        if not funcs:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id in funcs:
                    offenders.append(
                        f"{py_file.relative_to(REPO_ROOT)}:{node.lineno} "
                        f"{node.value.id}.{node.attr}（{funcs[node.value.id]} 的函数）")
    assert not offenders, "函数名被当模块访问:\n" + "\n".join(offenders)

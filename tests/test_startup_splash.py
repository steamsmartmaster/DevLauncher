"""启动引导与启动画面：轻量导入、控件生命周期、main() 接线。

Qt 用 offscreen 平台，测试不弹真实窗口。
"""
import ast
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parent.parent


def _source(name):
    return (REPO / name).read_text(encoding="utf-8")


def test_splash_module_avoids_webengine():
    src = _source("launcher_core/splash.py")
    tree = ast.parse(src)
    mods = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    assert all(m.startswith("PyQt6.Qt") for m in mods), mods
    assert not any("launcher_core" in m for m in mods), mods


def test_splash_widget_lifecycle():
    from PyQt6.QtCore import QCoreApplication, Qt
    from PyQt6.QtWidgets import QApplication

    from launcher_core.splash import StartupSplash

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication([])
    splash = StartupSplash()
    assert splash.width() == 460 and splash.height() == 172
    assert splash.windowTitle()
    splash.set_status("正在加载运行库…")
    assert splash._status.text() == "正在加载运行库…"
    splash.show()
    app.processEvents()
    splash.finish()
    splash.finish()
    assert splash._finished is True
    splash.set_status("不应再更新")
    assert splash._status.text() == "正在加载运行库…"


def test_boot_defers_heavy_imports_and_sets_gl_attribute():
    src = _source("boot.py")
    tree = ast.parse(src)
    top = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            top.append(node.module or "")
    assert set(top) <= {"os", "sys", "traceback"}, top
    assert src.index("AA_ShareOpenGLContexts") < src.index("QApplication(sys.argv)")
    run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run")
    calls = [n for n in ast.walk(run) if isinstance(n, ast.Import)]
    assert any(a.name == "main" for c in calls for a in c.names), "main 应在 run() 内延迟导入"


def test_main_accepts_injected_app_and_splash():
    tree = ast.parse(_source("main.py"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    args = [a.arg for a in fn.args.args]
    assert args == ["app", "splash"], args
    assert len(fn.args.defaults) == 2
    src = _source("main.py")
    assert "window.web_view.loadFinished.connect" in src
    assert "splash.finish" in src
    assert "splash.set_status" in src


def test_smoke_markers_still_present_in_main():
    src = _source("main.py")
    assert "MainWindow 初始化完成" in src

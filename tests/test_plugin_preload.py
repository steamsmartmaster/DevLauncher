"""启动插件预加载不得阻塞 UI 线程。

实测：144 个模组时 mods-doctor 的 on_load 扫描耗时 2.75s，原先在 QTimer
回调里同步执行，窗口刚出现就整段卡死。
"""
import ast
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _source(name):
    return (REPO / name).read_text(encoding="utf-8")


def _startup_fn():
    src = _source("main.py")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_startup_load_plugins":
            return src, node
    raise AssertionError("_startup_load_plugins not found")


def test_preload_runs_on_worker_thread():
    src, _fn = _startup_fn()
    start = src.index("    def _startup_load_plugins(self):")
    end = src.index("    def _on_versions_loaded(", start)
    body = src[start:end]
    assert "threading.Thread(" in body
    assert "daemon=True" in body
    assert body.index("load_all()") > body.index("threading.Thread(") or "def _work" in body
    assert "plugin-preload" in body


def test_preload_is_deferred_and_not_inline():
    src = _source("main.py")
    assert "QTimer.singleShot(0, self._startup_load_plugins)" not in src
    assert "QTimer.singleShot(1500, self._startup_load_plugins)" in src


def test_preload_returns_immediately():
    from PyQt6.QtWidgets import QApplication  # noqa: F401  (ensures Qt available)

    src, fn = _startup_fn()
    ns = {}
    code = ast.get_source_segment(src, fn)
    exec(compile("import threading\nimport logging\nlogger = logging.getLogger('t')\n"
                 "class _Plugins:\n"
                 "    def __init__(self):\n"
                 "        self.thread = None\n"
                 "        self.done = threading.Event()\n"
                 "    def load_all(self):\n"
                 "        self.thread = threading.current_thread().name\n"
                 "        self.done.set()\n"
                 "class _Bridge:\n"
                 "    def __init__(self):\n"
                 "        self.plugins = _Plugins()\n"
                 "class Self:\n"
                 "    def __init__(self):\n"
                 "        self.bridge = _Bridge()\n"
                 + "\n".join(l[4:] if l.startswith("    ") else l for l in code.splitlines())
                 + "\nresult = Self()\n", "<preload>", "exec"), ns)
    t0 = time.perf_counter()
    ns["_startup_load_plugins"](ns["result"])
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.2, f"call blocked for {elapsed:.3f}s"
    plugins = ns["result"].bridge.plugins
    assert plugins.done.wait(5), "load_all never ran"
    assert plugins.thread != threading.main_thread().name, plugins.thread
    assert plugins.thread == "plugin-preload", plugins.thread

# -*- coding: utf-8 -*-
"""frozen 启动入口：先亮出启动画面，再导入重量级模块。

PyInstaller onefile 每次启动都要把 ~200MB 解包到 %TEMP%\\_MEI*，期间屏幕上
什么都没有；改为 onedir 后这段开销消失，剩下的耗时主要是导入 QtWebEngine
与 launcher_core（约 1s）。本模块在 import main 之前创建 Qt 启动画面，
因此这几百毫秒里用户看到的是进度提示而不是空白。

开发态仍可直接 `python main.py`，行为不变。
"""

import os
import sys
import traceback


def _log_crash() -> None:
    """windowed 模式没有控制台，把 traceback 落到 logs/launcher.log。"""
    try:
        from launcher_core.paths import app_base_dir

        log_dir = app_base_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "launcher.log", "a", encoding="utf-8", errors="replace") as fh:
            fh.write("\n=== 启动失败 ===\n")
            fh.write(traceback.format_exc())
            fh.write("\n")
    except Exception:
        pass


def run() -> None:
    from launcher_core.webengine_flags import merge_chromium_flags

    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = merge_chromium_flags(
        os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS")
    )

    # QtWebEngine 要求「导入 QtWebEngineWidgets」或「创建 QCoreApplication 前
    # 设置 AA_ShareOpenGLContexts」二选一；选后者才能把重量级导入推迟到启动
    # 画面显示之后（否则必须在 QApplication 之前 import，画面就来不及显示）。
    from PyQt6.QtCore import QCoreApplication, Qt

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    from PyQt6.QtWidgets import QApplication

    from launcher_core.splash import StartupSplash

    app = QApplication(sys.argv)
    app.setApplicationName("DevLauncher")

    splash = StartupSplash()
    splash.show()
    splash.pump()

    try:
        splash.set_status("正在加载运行库…")
        import main

        main.main(app=app, splash=splash)
    except SystemExit:
        raise
    except BaseException:
        splash.set_status("启动失败，详见 logs/launcher.log")
        _log_crash()
        raise


if __name__ == "__main__":
    run()

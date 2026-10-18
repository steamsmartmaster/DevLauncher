# -*- coding: utf-8 -*-
"""构建冒烟判据：读日志增量，判断"启动是否真的完成"。

只验「进程存活 + 日志有新写入」不够——MainWindow.__init__ 里抛异常时，
PyInstaller 弹出未处理异常对话框，进程照样存活，而崩溃前的 logger.info
已写进日志，两个条件同时成立（上一轮实测放行了一个必然崩溃的 exe）。

判据两条：
  1. 出现 BOOT_MARKER —— import/Settings/configure/信号连接全走完，与网络无关；
  2. 出现 PAGE_MARKERS 之一 —— 证明 QtWebEngine 加载了 index.html 且 QWebChannel
     回调跑通。断网时写「获取版本列表失败」，属合法环境，同样放行；
     两者都缺 = 页面根本没加载，判失败。
"""
import sys
from pathlib import Path

BOOT_MARKER = "MainWindow 初始化完成"
PAGE_MARKERS = ("versionsLoaded", "获取版本列表失败")


def check(new_bytes: bytes) -> tuple:
    text = new_bytes.decode("utf-8", errors="replace")
    missing = []
    if BOOT_MARKER not in text:
        missing.append(BOOT_MARKER)
    if not any(m in text for m in PAGE_MARKERS):
        missing.append(" 或 ".join(PAGE_MARKERS))
    if missing:
        return False, "启动未完成，缺少标记: %s" % "; ".join(missing)
    page = PAGE_MARKERS[0] if PAGE_MARKERS[0] in text else "no-network"
    return True, "boot ok (page=%s)" % page


def main(argv) -> int:
    if len(argv) < 2:
        print("usage: smoke_check.py <log_path> [start_offset]")
        return 2
    path = Path(argv[1])
    offset = int(argv[2]) if len(argv) > 2 else 0
    if not path.exists():
        print("log missing: %s" % path)
        return 1
    size = path.stat().st_size
    if offset > size:
        print("log truncated: offset=%d size=%d" % (offset, size))
        return 1
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    ok, detail = check(data)
    print(detail)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

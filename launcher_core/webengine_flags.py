# -*- coding: utf-8 -*-
"""QtWebEngine Chromium 命令行 flags。

QtWebEngine 默认把 GPU/合成器跑在应用进程内（in-process GPU），
持续吃掉约 70MB 提交内存。以下三个 flags 关闭 GPU 路径并将其迁出，
实测（PowerShell 私有内存合计）275MB → 207MB，页面软件光栅化对
本启动器这类静态 UI 无感知性能差异。
"""

WEBENGINE_CHROMIUM_FLAGS = (
    "--disable-gpu --in-process-gpu --disable-gpu-compositing"
)


def merge_chromium_flags(existing=None) -> str:
    """合并用户自定义 QTWEBENGINE_CHROMIUM_FLAGS 与本项目 flags。

    - 未设置/为空 → 返回项目 flags
    - 已含项目 flags → 原样返回（幂等）
    - 否则 → 用户 flags 在前、项目 flags 追加
    """
    base = (existing or "").strip()
    if not base:
        return WEBENGINE_CHROMIUM_FLAGS
    if WEBENGINE_CHROMIUM_FLAGS in base:
        return base
    return base + " " + WEBENGINE_CHROMIUM_FLAGS

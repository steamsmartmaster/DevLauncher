# -*- coding: utf-8 -*-
"""QtWebEngine Chromium 命令行 flags。

QtWebEngine 默认把 GPU/合成器跑在应用进程内（in-process GPU），
持续吃掉约 70MB 提交内存。以下三个 flags 关闭 GPU 路径并将其迁出，
实测（PowerShell 私有内存合计）275MB → 207MB，页面软件光栅化对
本启动器这类静态 UI 无感知性能差异。

环境代理：QtWebEngine 网络栈不读取系统/环境代理设置（requests 会），
内置网页窗口（web_download 流程）需通过 --proxy-server 注入
HTTPS_PROXY/HTTP_PROXY，否则开了系统代理仍直连失败。
"""

import os

WEBENGINE_CHROMIUM_FLAGS = (
    "--disable-gpu --in-process-gpu --disable-gpu-compositing"
)

_PROXY_ENV_KEYS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


def _env_proxy() -> str:
    for key in _PROXY_ENV_KEYS:
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    return ""


def merge_chromium_flags(existing=None) -> str:
    """合并用户自定义 QTWEBENGINE_CHROMIUM_FLAGS 与本项目 flags。

    - 未设置/为空 → 返回项目 flags（有环境代理则前置 --proxy-server）
    - 已含项目 flags → 原样返回（幂等）
    - 否则 → 用户 flags 在前、项目 flags 追加
    - 用户已自带 --proxy-server → 不注入环境代理（用户配置优先）
    """
    proxy = _env_proxy()
    flags = WEBENGINE_CHROMIUM_FLAGS
    base = (existing or "").strip()
    if proxy and "--proxy-server" not in base:
        flags = f"--proxy-server={proxy} {flags}"
    if not base:
        return flags
    if WEBENGINE_CHROMIUM_FLAGS in base:
        return base
    return base + " " + flags

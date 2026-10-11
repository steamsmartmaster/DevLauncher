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
    system = _read_system_proxy()
    if system and "://" not in system:
        system = "http://" + system
    return system


def parse_ie_proxy(raw: str) -> str:
    """WinINET ProxyServer 归一到 host:port。

    系统代理有两种形态：全协议单值 `host:port`，或分号键值对
    `http=h:p;https=h:p;socks=h:p`。键值对里按 https > socks > http 取，
    因为 QtWebEngine 只走 HTTPS 出站。"""
    s = (raw or "").strip()
    if not s:
        return ""
    if "=" not in s:
        return s
    picked = {}
    for part in s.split(";"):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        picked[k.strip().lower()] = v.strip()
    for key in ("https", "socks", "http"):
        if picked.get(key):
            return picked[key]
    return ""


def _read_system_proxy() -> str:
    """回退读 Windows WinINET 系统代理（浏览器共用的那套设置）。

    双击启动 app 时环境变量为空，而浏览器能连是因为读了注册表里的
    ProxyEnable/ProxyServer。这里补齐同一来源，否则 QtWebEngine 直连超时。"""
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return ""
            raw, _ = winreg.QueryValueEx(key, "ProxyServer")
    except OSError:
        return ""
    return parse_ie_proxy(raw)


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

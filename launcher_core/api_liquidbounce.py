# -*- coding: utf-8 -*-
"""LiquidBounce 官方构建 API 封装（api.liquidbounce.net，前端零网络约定）。

实测契约（2026-10）：
- GET api/v1/version/builds/nextgen → 200 JSON 数组，按构建时间倒序，首条即最新
- 每条含 build_id/release/mc_version/lb_version/url/skip_pid；url 指向
  liquidbounce.net/download/queue/<build_id> 单构建下载页（200 直达）
- release_only=True 取首条 release==true（正式版）；数组里没有则回退首条
- dl.liquidbounce.net/skip/<pid> 为广告跳转 HTML，无法程序化取 jar，
  因此始终打开最新构建的 queue 页而非直链
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

BUILDS_URL = "https://api.liquidbounce.net/api/v1/version/builds/nextgen"
_TIMEOUT = 10


def latest_download_url(builds, release_only: bool = True) -> str:
    """从构建数组取最新下载页 URL；无可用条目返回 ""。

    数组约定倒序（首条最新）。release_only 过滤首个正式版，
    条目缺 url 字段时按 build_id 拼 queue 页兜底。"""
    if not isinstance(builds, list) or not builds:
        return ""
    picked = None
    if release_only:
        picked = next((b for b in builds if isinstance(b, dict) and b.get("release")), None)
    if picked is None and isinstance(builds[0], dict) and (
            not release_only or builds[0].get("release")):
        picked = builds[0]
    if not isinstance(picked, dict):
        return ""
    url = (picked.get("url") or "").strip()
    if url:
        return url
    build_id = picked.get("build_id")
    if build_id:
        return f"https://liquidbounce.net/download/queue/{build_id}"
    return ""


def fetch_latest_build(release_only: bool = True) -> str:
    """网络拉取最新构建下载页 URL；任何失败返回 ""（调用方回退静态入口）。"""
    try:
        resp = requests.get(BUILDS_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        return latest_download_url(resp.json(), release_only=release_only)
    except Exception as e:
        logger.warning(f"获取 LiquidBounce 最新构建失败: {e}")
        return ""

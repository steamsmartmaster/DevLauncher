"""Meteor Client 官方下载 API 封装（meteorclient.com/api/download，前端零网络约定）

实测行为（2026-10）：
- 裸接口 GET /api/download → 200 + application/java-archive + Content-Disposition 最新 jar
- GET /api/download?version=<存在版本> → 对应版本 jar（filename=meteor-client-<v>-<build>.jar）
- GET /api/download?version=<不存在/旧版本> → 400 application/json → 回退裸接口
- /archive 页静态锚点列出全部可下载版本（href api/download?version=X + 文本）
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://meteorclient.com/api/download"
ARCHIVE_URL = "https://meteorclient.com/archive"


def meteor_download_url(version: str = "") -> str:
    """下载 URL；version 为空 → 裸接口（最新版）。"""
    if not version:
        return BASE_URL
    return f"{BASE_URL}?version={version}"


def filename_from_content_disposition(cd: str) -> str:
    """从 Content-Disposition 取文件名；无 filename= 或仅 filename* → ""。"""
    cd = (cd or "").strip()
    if not cd:
        return ""
    m = re.search(r'filename="([^"]+)"', cd) or re.search(r"filename=([^;]+)", cd)
    return m.group(1).strip() if m else ""


_ARCHIVE_RE = re.compile(
    r'href="[^"]*api/download\?version=([^"&]+)"[^>]*>\s*([^<]+?)\s*</a>', re.IGNORECASE)


def parse_archive_versions(html: str) -> list[dict]:
    """解析 /archive 页锚点 → [{"version": ..., "label": ...}]（保持页面顺序、去重）。"""
    out: list[dict] = []
    seen: set[str] = set()
    for m in _ARCHIVE_RE.finditer(html or ""):
        ver = m.group(1).strip()
        if ver in seen:
            continue
        seen.add(ver)
        out.append({"version": ver, "label": m.group(2).strip()})
    return out


class MeteorAPI:
    """Minimal Meteor download client（只读探测，不落盘）"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "DevLauncher/1.0"})

    def _probe(self, version: str) -> Optional[dict]:
        """HEAD-ish 探测：仅读响应头即关闭连接。成功返回 {"url","filename"}。"""
        url = meteor_download_url(version)
        try:
            r = self.session.get(url, timeout=20, stream=True, allow_redirects=True)
        except Exception as e:
            logger.error(f"Meteor 下载探测失败 {url}: {e}")
            return None
        if r.status_code != 200:
            r.close()
            return None
        cd = r.headers.get("content-disposition", "")
        ct = r.headers.get("content-type", "")
        r.close()
        filename = filename_from_content_disposition(cd)
        if "java-archive" not in ct and not filename.endswith(".jar"):
            return None
        if not filename:
            filename = f"meteor-client-{version}.jar" if version else "meteor-client.jar"
        return {"url": url, "filename": filename}

    def get_jar(self, version: str = "") -> Optional[dict]:
        """取某版本 jar 直链；指定版本不可用（400 等）→ 回退裸接口最新版。"""
        got = self._probe(version) if version else None
        if got:
            return got
        if version:
            logger.info(f"Meteor ?version={version} 不可用，回退最新版")
        return self._probe("")

    def get_archive_versions(self) -> list[dict]:
        """抓 /archive 页 → 可下载版本列表（解析失败返回 []）。"""
        try:
            r = self.session.get(ARCHIVE_URL, timeout=20)
            r.raise_for_status()
            return parse_archive_versions(r.text)
        except Exception as e:
            logger.error(f"Meteor archive 抓取失败: {e}")
            return []


# Singleton
meteor_api = MeteorAPI()

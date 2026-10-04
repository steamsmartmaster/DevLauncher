"""GitHub Releases API 封装（仅 releases/latest 解析，前端零网络约定）"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from launcher_core.clients_catalog import github_latest_url, github_releases_url

logger = logging.getLogger(__name__)


class GitHubAPI:
    """Minimal GitHub releases/latest client"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "DevLauncher/1.0 (contact@example.com)",
            "Accept": "application/vnd.github+json",
        })

    def get_latest_release(self, repo: str) -> Optional[dict]:
        """获取 owner/repo 最新正式 release（releases/latest 天然排除 prerelease）"""
        url = github_latest_url(repo)
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"GitHub latest release: {repo} -> {data.get('tag_name')}")
            return data
        except Exception as e:
            logger.error(f"GitHub releases/latest failed for {repo}: {e}")
            return None

    def get_releases(self, repo: str, per_page: int = 30) -> list:
        """获取 owner/repo release 列表（最新在前；排除 draft），失败返回 []"""
        url = github_releases_url(repo)
        try:
            resp = self.session.get(url, params={"per_page": per_page}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                return []
            return [r for r in data if isinstance(r, dict) and not r.get("draft")]
        except Exception as e:
            logger.error(f"GitHub releases list failed for {repo}: {e}")
            return []


# Singleton
github_api = GitHubAPI()

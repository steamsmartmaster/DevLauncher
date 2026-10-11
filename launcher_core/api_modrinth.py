"""Modrinth API client"""
import json
import logging
import os
import requests
from typing import Optional

logger = logging.getLogger("DevLauncher")

BASE_URL = "https://api.modrinth.com/v2"

# 大文件（整合包/客户端 jar+zip）中途断流的重试次数
DOWNLOAD_RETRIES = 3

# Facet types for different content
PROJECT_TYPES = {
    "modpacks": [["project_type:modpack"]],
    "mods": [["project_type:mod"]],
    "datapacks": [["project_type:datapack"]],
    "worlds": [["project_type:world"]]
}

# Loader name mapping (display name -> API name)
LOADER_NAME_MAP = {
    "fabric": "fabric",
    "forge": "forge",
    "neoforge": "neoforge",
    "quilt": "quilt",
    "liteloader": "liteloader",
    "forge/neo forge": "forge",  # NeoForge accepts Forge mods in some cases
}


# Modrinth search 的环境过滤用 client_side/server_side facet（非 categories:client，
# 实测 categories:client 恒为 0）。chip 值 client/server → 支持端 required+optional 组内 OR。
ENV_FACETS = {
    "client": ["client_side:required", "client_side:optional"],
    "server": ["server_side:required", "server_side:optional"],
}


def build_facets(
    project_type: str = "mods",
    versions: Optional[list] = None,
    loaders: Optional[list] = None,
    categories: Optional[list] = None,
    environments: Optional[list] = None,
) -> list:
    """构建 Modrinth facets：子数组内 OR、子数组间 AND。

    loaders/categories 是 categories: slug 各自独立成组；
    environments 走 client_side/server_side（每端一组，多选端间 AND）。
    """
    facets = [list(group) for group in PROJECT_TYPES.get(project_type, [["project_type:mod"]])]
    if versions:
        facets.append(["versions:" + v for v in versions])
    if loaders:
        facets.append(["categories:" + l for l in loaders])
    if categories:
        facets.append(["categories:" + c for c in categories])
    for env in environments or []:
        group = ENV_FACETS.get(env)
        if group:
            facets.append(list(group))
    return facets


class ModrinthAPI:
    """Modrinth API wrapper"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "DevLauncher/1.0 (contact@example.com)"
        })
        self._cached_loaders = None
        self._cached_game_versions = None

    def get_loaders(self) -> list[dict]:
        """Get all available loaders from Modrinth"""
        if self._cached_loaders:
            return self._cached_loaders
        try:
            resp = self.session.get(f"{BASE_URL}/tag/loader", timeout=15)
            resp.raise_for_status()
            self._cached_loaders = resp.json()
            logger.info(f"Modrinth: 获取到 {len(self._cached_loaders)} 个加载器标签")
            return self._cached_loaders
        except Exception as e:
            logger.error(f"获取 Modrinth 加载器标签失败: {e}")
            return []

    def get_game_versions(self, release_only: bool = True) -> list[str]:
        """Get all available game versions"""
        if self._cached_game_versions and release_only:
            return self._cached_game_versions
        try:
            resp = self.session.get(f"{BASE_URL}/tag/version", timeout=15)
            resp.raise_for_status()
            all_versions = resp.json()
            if release_only:
                versions = [v["version"] for v in all_versions if v.get("version_type") == "release"]
            else:
                versions = [v["version"] for v in all_versions]
            if release_only:
                self._cached_game_versions = versions
            logger.info(f"Modrinth: 获取到 {len(versions)} 个游戏版本")
            return versions
        except Exception as e:
            logger.error(f"获取 Modrinth 游戏版本失败: {e}")
            return []

    def get_mod_icon(self, mod_id: str) -> str:
        """Get mod icon URL by mod ID (slug or numeric)"""
        try:
            resp = self.session.get(f"{BASE_URL}/project/{mod_id}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                icon_url = data.get("icon_url", "")
                if icon_url:
                    return icon_url
        except Exception:
            pass
        return ""

    def search_mod_icon(self, query: str) -> str:
        """Search for mod and return first result's icon URL"""
        try:
            resp = self.session.get(f"{BASE_URL}/search", params={"query": query, "limit": 1}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                hits = data.get("hits", [])
                if hits:
                    return hits[0].get("icon_url", "")
        except Exception:
            pass
        return ""

    def search(
        self,
        query: str = "",
        project_type: str = "mods",
        index: str = "relevance",
        offset: int = 0,
        limit: int = 20,
        versions: Optional[list] = None,
        loaders: Optional[list] = None,
        categories: Optional[list] = None,
        environments: Optional[list] = None
    ) -> dict:
        """Search for projects with optional version/loader/category filtering"""
        facets = build_facets(project_type, versions, loaders, categories, environments)

        params = {
            "index": index,
            "offset": offset,
            "limit": limit
        }
        if query:
            params["query"] = query
        if facets:
            params["facets"] = json.dumps(facets)

        try:
            resp = self.session.get(f"{BASE_URL}/search", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            logger.debug(f"Modrinth search: {data.get('total_hits', 0)} hits")
            return {
                "hits": data.get("hits", []),
                "total_hits": data.get("total_hits", 0),
                "offset": data.get("offset", 0),
                "limit": data.get("limit", 0)
            }
        except Exception as e:
            logger.error(f"Modrinth search failed: {e}")
            return {"hits": [], "total_hits": 0, "offset": 0, "limit": 0}

    def get_project(self, project_id: str) -> Optional[dict]:
        """Get project details"""
        try:
            resp = self.session.get(f"{BASE_URL}/project/{project_id}", timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Modrinth get_project failed: {e}")
            return None

    def get_project_versions(
        self,
        project_id: str,
        loaders: Optional[list] = None,
        game_versions: Optional[list] = None
    ) -> list:
        """Get project versions with optional filtering"""
        params = {}
        if loaders:
            params["loaders"] = json.dumps(loaders)
        if game_versions:
            params["game_versions"] = json.dumps(game_versions)

        try:
            resp = self.session.get(
                f"{BASE_URL}/project/{project_id}/version",
                params=params,
                timeout=15
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Modrinth get_project_versions failed: {e}")
            return []

    def get_version(self, version_id: str) -> Optional[dict]:
        """Get version details"""
        try:
            resp = self.session.get(f"{BASE_URL}/version/{version_id}", timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Modrinth get_version failed: {e}")
            return None

    def download_file(self, url: str, dest_path: str, callback=None) -> bool:
        """Download a file.

        OVH/S3 预签名大文件实测会中途 IncompleteRead，单次失败不该判死，
        所以按 Range 从断点续传重试；三次仍断则删掉半截文件避免被当成品。
        """
        tmp_path = dest_path + ".part"
        for attempt in range(1, DOWNLOAD_RETRIES + 1):
            try:
                self._download_attempt(url, tmp_path, callback, attempt > 1)
                os.replace(tmp_path, dest_path)
                logger.info(f"Downloaded: {dest_path}")
                return True
            except Exception as e:
                logger.error(
                    f"Download failed (attempt {attempt}/{DOWNLOAD_RETRIES}): {e}")
        for p in (tmp_path, dest_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        return False

    def _download_attempt(self, url: str, tmp_path: str, callback,
                           allow_resume: bool):
        """One GET pass writing to tmp_path; raises on any failure."""
        start = 0
        headers = {}
        mode = "wb"
        if allow_resume and os.path.exists(tmp_path):
            start = os.path.getsize(tmp_path)
            if start:
                headers["Range"] = f"bytes={start}-"
                mode = "ab"

        resp = self.session.get(url, stream=True, timeout=60, headers=headers)
        if resp.status_code == 416:
            # Range 起点已在文件末尾之外：清空重下
            os.remove(tmp_path)
            resp.close()
            return self._download_attempt(url, tmp_path, callback, False)
        resp.raise_for_status()
        if start and resp.status_code != 206:
            # 服务器忽略 Range 回了全量，必须从头写否则拼接出坏文件
            start, mode = 0, "wb"

        total = int(resp.headers.get("content-length", 0) or 0)
        total_all = start + total
        downloaded = start
        with open(tmp_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if callback and total_all > 0:
                    callback(min(1.0, downloaded / total_all))


# Singleton
modrinth_api = ModrinthAPI()

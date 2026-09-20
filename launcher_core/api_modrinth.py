"""Modrinth API client"""
import json
import logging
import requests
from typing import Optional

logger = logging.getLogger("DevLauncher")

BASE_URL = "https://api.modrinth.com/v2"

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
        loaders: Optional[list] = None
    ) -> dict:
        """Search for projects with optional version/loader filtering"""
        facets = PROJECT_TYPES.get(project_type, [["project_type:mod"]]).copy()

        if versions:
            version_facets = [["versions:" + v] for v in versions]
            facets.append(version_facets)

        if loaders:
            loader_facets = [["categories:" + l] for l in loaders]
            facets.append(loader_facets)

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
        """Download a file"""
        try:
            resp = self.session.get(url, stream=True, timeout=60)
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            downloaded = 0

            with open(dest_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if callback and total > 0:
                        callback(downloaded / total)

            logger.info(f"Downloaded: {dest_path}")
            return True
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False


# Singleton
modrinth_api = ModrinthAPI()

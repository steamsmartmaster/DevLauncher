"""CurseForge API client"""
import json
import logging
import requests
from typing import Optional

logger = logging.getLogger("DevLauncher")

BASE_URL = "https://api.curseforge.com"

# CurseForge class IDs
CLASS_IDS = {
    "modpacks": 6,      # Modpacks (use mods class as fallback - CF modpacks API changed)
    "mods": 6,         # Mods
    "datapacks": 17,   # Data Packs
    "worlds": 17       # Worlds
}

# CurseForge class IDs for search (separate worlds and datapacks)
SEARCH_CLASS_IDS = {
    "modpacks": 6,      # Use mods class as fallback
    "mods": 6,
    "datapacks": 17,
    "worlds": 17
}

# CurseForge mod loader type IDs
# https://docs.curseforge.com/rest-api/#get-game-modloaders
LOADER_TYPE_IDS = {
    "forge": 1,
    "liteloader": 2,
    "fabric": 4,
    "quilt": 5,
    "neoforge": 6,
}

# Reverse mapping for display
LOADER_TYPE_NAMES = {v: k for k, v in LOADER_TYPE_IDS.items()}


class CurseForgeAPI:
    """CurseForge API wrapper"""

    def __init__(self, api_key: str = "$2a$10$bL4bIL5pUWqfcO7KQtnMReakwtfHbNKh6v1uTpKlzhwoueEJQnPnm"):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "Accept": "application/json"
        })

    def search(
        self,
        query: str = "",
        class_id: int = 6,
        index: int = 0,
        game_version: Optional[str] = None,
        mod_loader_type: Optional[int] = None,
        sort_field: int = 2,  # 2=Popularity
        sort_order: int = 1   # 1=Descending
    ) -> dict:
        """Search for projects"""
        params = {
            "gameId": 432,  # Minecraft
            "classId": class_id,
            "index": index,
            "pageSize": 20,
            "sortField": sort_field,
            "sortOrder": sort_order,
        }
        if query:
            params["searchFilter"] = query
        if game_version:
            params["gameVersion"] = game_version
        if mod_loader_type:
            params["modLoaderType"] = mod_loader_type

        try:
            resp = self.session.get(f"{BASE_URL}/v1/mods/search", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            total = resp.json().get("pagination", {}).get("totalCount", len(data))
            logger.debug(f"CurseForge search: {total} results")
            return {
                "hits": data,
                "total_hits": total,
                "offset": index,
                "limit": 20
            }
        except Exception as e:
            logger.error(f"CurseForge search failed: {e}")
            return {"hits": [], "total_hits": 0, "offset": 0, "limit": 0}

    def search_mods(
        self,
        query: str = "",
        game_version: Optional[str] = None,
        mod_loader_type: Optional[str] = None,
        index: int = 0
    ) -> dict:
        """Search mods with string-based loader type"""
        loader_id = LOADER_TYPE_IDS.get(mod_loader_type) if mod_loader_type else None
        return self.search(query=query, class_id=CLASS_IDS["mods"],
                          index=index, game_version=game_version,
                          mod_loader_type=loader_id)

    def search_modpacks(
        self,
        query: str = "",
        game_version: Optional[str] = None,
        index: int = 0
    ) -> dict:
        """Search modpacks"""
        return self.search(query=query, class_id=CLASS_IDS["modpacks"],
                          index=index, game_version=game_version)

    def search_worlds(
        self,
        query: str = "",
        game_version: Optional[str] = None,
        index: int = 0
    ) -> dict:
        """Search worlds"""
        return self.search(query=query, class_id=CLASS_IDS["worlds"],
                          index=index, game_version=game_version)

    def search_datapacks(
        self,
        query: str = "",
        game_version: Optional[str] = None,
        index: int = 0
    ) -> dict:
        """Search datapacks"""
        return self.search(query=query, class_id=CLASS_IDS["datapacks"],
                          index=index, game_version=game_version)

    def get_mod(self, mod_id: int) -> Optional[dict]:
        """Get mod details"""
        try:
            resp = self.session.get(f"{BASE_URL}/v1/mods/{mod_id}", timeout=15)
            resp.raise_for_status()
            return resp.json().get("data")
        except Exception as e:
            logger.error(f"CurseForge get_mod failed: {e}")
            return None

    def get_mod_files(
        self,
        mod_id: int,
        game_version: Optional[str] = None,
        mod_loader_type: Optional[int] = None
    ) -> list:
        """Get mod files"""
        params = {}
        if game_version:
            params["gameVersion"] = game_version
        if mod_loader_type:
            params["modLoaderType"] = mod_loader_type

        try:
            resp = self.session.get(
                f"{BASE_URL}/v1/mods/{mod_id}/files",
                params=params,
                timeout=15
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            logger.error(f"CurseForge get_mod_files failed: {e}")
            return []

    def get_mod_file(self, mod_id: int, file_id: int) -> Optional[dict]:
        """Get a specific mod file"""
        try:
            resp = self.session.get(
                f"{BASE_URL}/v1/mods/{mod_id}/files/{file_id}",
                timeout=15
            )
            resp.raise_for_status()
            return resp.json().get("data")
        except Exception as e:
            logger.error(f"CurseForge get_mod_file failed: {e}")
            return None

    def download_file(self, file_url: str, dest_path: str, callback=None) -> bool:
        """Download a file"""
        try:
            resp = self.session.get(file_url, stream=True, timeout=60)
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
curseforge_api = CurseForgeAPI()

"""Modrinth API client"""
import json
import logging
import os
import requests
from typing import Optional

from launcher_core import net

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


# GET /projects?ids= 走 URL，超长会被 API 拒；单批上限取 100
PROJECT_BATCH = 100


def parse_dependencies(version: Optional[dict]) -> list:
    """把 Modrinth 版本对象的 dependencies[] 归一化成可下载依赖清单。

    实测字段（2026-10-13 api.modrinth.com）：project_id / version_id /
    file_name / dependency_type ∈ required|optional|incompatible|embedded。

    version_id 为 null 的语义是"未指定版本"，调用方要拿 project_id 回退挑版本，
    所以这里保持 None 而不是空串——空串会让人误以为"已经指定了版本"。
    """
    if not isinstance(version, dict):
        return []
    raw = version.get("dependencies")
    if not isinstance(raw, list):
        return []
    deps = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        project_id = item.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            # 没有 project_id 无法定位项目，留着只会渲染出下载不了的空行
            continue
        version_id = item.get("version_id")
        file_name = item.get("file_name")
        deps.append({
            "project_id": project_id,
            "version_id": version_id if isinstance(version_id, str) and version_id else None,
            "dependency_type": item.get("dependency_type") or "required",
            "file_name": file_name if isinstance(file_name, str) and file_name else None,
        })
    return deps


def attach_project_info(deps: list, projects: dict) -> list:
    for dep in deps:
        info = projects.get(dep.get("project_id")) or {}
        dep["title"] = info.get("title") or dep.get("project_id", "")
        dep["slug"] = info.get("slug", "")
        dep["icon_url"] = info.get("icon_url", "")
    return deps


def _str_list(value) -> list:
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str)]
    if isinstance(value, str):
        return [value]
    return []


def pick_dependency_version(versions: Optional[list], game_versions=None,
                            loaders=None) -> Optional[dict]:
    """从依赖项目的版本列表里挑一个与父版本兼容的版本。

    先只认 release，全不匹配再退到 beta/alpha——依赖被装成 alpha 比直接装不上
    更难排查（游戏起不来，日志里也看不出是依赖的问题）。
    """
    pool = [v for v in (versions or []) if isinstance(v, dict)]
    want_gv = set(_str_list(game_versions))
    want_ld = set(_str_list(loaders))
    for prefer_release in (True, False):
        for v in pool:
            if prefer_release and v.get("version_type") not in (None, "release"):
                continue
            if want_gv and not (want_gv & set(_str_list(v.get("game_versions")))):
                continue
            if want_ld and not (want_ld & set(_str_list(v.get("loaders")))):
                continue
            return v
    return None


def parse_chosen_ids(raw) -> list:
    try:
        data = json.loads(raw) if raw else []
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [c for c in data if isinstance(c, str) and c]


def build_download_plan(version: dict, chosen_ids: list, resolve=None) -> list:
    """组装下载清单 [(url, filename), ...]：主文件 + 用户勾选的 optional 依赖。

    resolve(dep, parent) 由调用方注入，负责把依赖解析成版本对象——放这里是为了
    让清单组装逻辑能脱离 Qt/网络单测。
    """
    plan = []
    for f in (version.get("files") or []):
        if isinstance(f, dict) and f.get("url"):
            plan.append((f["url"], f.get("filename") or "download.jar"))
            break
    wanted = set(chosen_ids or [])
    if not wanted:
        return plan
    for dep in parse_dependencies(version):
        if dep["dependency_type"] != "optional" or dep["project_id"] not in wanted:
            continue
        resolved = resolve(dep, version) if resolve else None
        for f in ((resolved or {}).get("files") or []):
            if isinstance(f, dict) and f.get("url"):
                plan.append((f["url"], f.get("filename") or dep["project_id"] + ".jar"))
                break
    return plan


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

    def get_projects(self, ids: list) -> dict:
        """批量查项目，返回 {project_id: {title, slug, icon_url, project_type}}。

        依赖清单里只有 project_id（形如 P7dR8mSH），直接显示对用户毫无意义。
        走一次批量请求拿标题，而不是每个依赖各发一次——实测
        simple-voice-chat 一条版本就有 7 个 optional 依赖。
        """
        if not ids:
            return {}
        uniq = []
        seen = set()
        for pid in ids:
            if isinstance(pid, str) and pid and pid not in seen:
                seen.add(pid)
                uniq.append(pid)
        out = {}
        for start in range(0, len(uniq), PROJECT_BATCH):
            chunk = uniq[start:start + PROJECT_BATCH]
            try:
                resp = self.session.get(
                    f"{BASE_URL}/projects",
                    params={"ids": json.dumps(chunk)},
                    timeout=15,
                )
                resp.raise_for_status()
                for p in resp.json():
                    if isinstance(p, dict) and p.get("id"):
                        out[p["id"]] = {
                            "title": p.get("title") or p.get("slug") or p["id"],
                            "slug": p.get("slug", ""),
                            "icon_url": p.get("icon_url") or "",
                            "project_type": p.get("project_type", ""),
                        }
            except Exception as e:
                logger.error(f"Modrinth get_projects failed: {e}")
        return out

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

        断流续传、重试、原子落盘统一走 launcher_core.net（与整合包导入、
        版本安装共用一套，代理与重试次数只需配置一次）。这里只保留本类对外
        的进度契约：callback 收 0.0~1.0 的比例，而不是字节数。
        """
        def _progress(done: int, total: int) -> None:
            if callback and total > 0:
                callback(min(1.0, done / total))

        ok = net.download_file(
            url, dest_path,
            session=self.session,
            callback=_progress if callback else None,
            retries=DOWNLOAD_RETRIES,
            timeout=60,
        )
        if ok:
            logger.info(f"Downloaded: {dest_path}")
        return ok


# Singleton
modrinth_api = ModrinthAPI()

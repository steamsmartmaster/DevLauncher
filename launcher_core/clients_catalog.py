"""内置客户端 / PVP 整合包下载目录（静态 20 条 = 14 client + 6 pack，随包离线）。

条目字段：id/name/type/tags/platform/endpoint/strategy/note/kind/icon
- type:      client | pack
- tags:      标签，取值仅限 作弊/PVP/生存（可多标签，如 ["作弊","PVP"]）
- platform:  github | modrinth | curseforge | web   （endpoint 形态的托管方）
- strategy:  github_latest_jar | modrinth_latest_jar | meteor_download
           | modrinth_modpack | curseforge_search_jar | open_page | web_download
- kind:      jar | modpack | page  （决定落盘/复用哪条下载管线）
- endpoint:  github=repos owner/name；modrinth=slug；curseforge=搜索词；
              meteor_download/open_page/web_download=完整 URL
- icon:      卡片图标 URL（空串 → 前端字母兜底）
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

_BAD_SUFFIXES = ("-sources", "-dev", "-javadoc")

CATALOG: list[dict] = [
    # ---- 14 个客户端 ----
    {"id": "meteor", "name": "Meteor Client", "type": "client", "tags": ["作弊"],
     "platform": "web", "endpoint": "https://meteorclient.com/api/download",
     "strategy": "meteor_download", "kind": "jar",
     "note": "主流作弊客户端，官网 API 直下，按当前游戏版本匹配",
     "icon": "static/icons/clients/meteor.png"},
    {"id": "wurst", "name": "Wurst Client", "type": "client", "tags": ["作弊"],
     "platform": "web", "endpoint": "https://www.wurstclient.net/",
     "strategy": "open_page", "kind": "page",
     "note": "老牌作弊客户端；GitHub 无 Release，官网手动下载",
     "icon": "static/icons/clients/wurst.png"},
    {"id": "ares", "name": "Ares Client", "type": "client", "tags": ["作弊"],
     "platform": "web", "endpoint": "https://aresclient.org/",
     "strategy": "open_page", "kind": "page",
     "note": "开源作弊客户端；GitHub 无 Release，官网手动下载",
     "icon": "static/icons/clients/ares.png"},
    {"id": "bleachhack", "name": "BleachHack", "type": "client", "tags": ["作弊"],
     "platform": "github", "endpoint": "BleachDev/BleachHack",
     "strategy": "github_latest_jar", "kind": "jar",
     "note": "多 MC 版本 jar，取最新上传",
     "icon": "static/icons/clients/bleachhack.jpg"},
    {"id": "fpsmaster", "name": "FPSMaster", "type": "client", "tags": ["PVP"],
     "platform": "github", "endpoint": "FPSMasterTeam/FPSMaster-Edge",
     "strategy": "github_latest_jar", "kind": "jar",
     "note": "FPS 优化客户端（releases/latest 天然排除 prerelease）",
     "icon": "static/icons/clients/fpsmaster.png"},
    {"id": "combatant", "name": "Combatant Client", "type": "client", "tags": ["作弊", "PVP"],
     "platform": "github", "endpoint": "pivosos2007/combatant-client",
     "strategy": "github_latest_jar", "kind": "jar",
     "note": "PVP 向；需 Fabric API + Sodium 前置",
     "icon": "static/icons/clients/combatant.png"},
    {"id": "travel", "name": "Travel Client", "type": "client", "tags": ["作弊", "生存"],
     "platform": "github", "endpoint": "Trauncy209/Travel-Client",
     "strategy": "github_latest_jar", "kind": "jar",
     "note": "旅行向轻量客户端（travel-client-*.jar）",
     "icon": "static/icons/clients/travel.png"},
    {"id": "mastermind", "name": "MasterMind", "type": "client", "tags": ["作弊", "PVP"],
     "platform": "github", "endpoint": "Snowiiii/MasterMind-Fabric",
     "strategy": "github_latest_jar", "kind": "jar",
     "note": "Fabric 信息 HUD 客户端模组",
     "icon": "static/icons/clients/mastermind.jpg"},
    {"id": "payload", "name": "Payload Utility Mod", "type": "client", "tags": ["作弊", "生存"],
     "platform": "web", "endpoint": "https://github.com/franktheory/Payload-Utility-Mod",
     "strategy": "open_page", "kind": "page",
     "note": "2b2t 向负载工具；GitHub 无 Release，打开仓库页手动下载",
     "icon": "static/icons/clients/payload.png"},
    {"id": "optix", "name": "Optix Client", "type": "client", "tags": ["PVP"],
     "platform": "modrinth", "endpoint": "optixclient",
     "strategy": "modrinth_latest_jar", "kind": "jar",
     "note": "PVP 竞技客户端",
     "icon": "static/icons/clients/optix.webp"},
    {"id": "hedgehog", "name": "Hedgehog Client", "type": "client", "tags": ["PVP"],
     "platform": "modrinth", "endpoint": "hedgehog",
     "strategy": "modrinth_latest_jar", "kind": "jar",
     "note": "14 个 PVP 模块",
     "icon": "static/icons/clients/hedgehog.webp"},
    {"id": "miclient", "name": "MiClient", "type": "client", "tags": ["PVP"],
     "platform": "modrinth", "endpoint": "miclient",
     "strategy": "modrinth_latest_jar", "kind": "jar",
     "note": "轻量 PVP 辅助客户端",
     "icon": "static/icons/clients/miclient.webp"},
    {"id": "axolotlclient", "name": "AxolotlClient", "type": "client", "tags": ["PVP"],
     "platform": "curseforge", "endpoint": "AxolotlClient",
     "strategy": "curseforge_search_jar", "kind": "jar",
     "note": "轻量客户端 HUD/美化",
     "icon": "static/icons/clients/axolotlclient.png"},
    {"id": "liquidbounce", "name": "LiquidBounce", "type": "client", "tags": ["作弊", "PVP"],
     "platform": "web", "endpoint": "https://liquidbounce.net/download#manual",
     "strategy": "web_download", "kind": "jar",
     "note": "PVP 客户端；内置网页选版本，启动器接管 jar 下载",
     "icon": "static/icons/clients/liquidbounce.svg"},
    # ---- 6 个 PVP 整合包 ----
    {"id": "ultimate-pvp", "name": "The Ultimate PvP pack", "type": "pack", "tags": ["PVP"],
     "platform": "modrinth", "endpoint": "the-ultimate-pvp-modpack",
     "strategy": "modrinth_modpack", "kind": "modpack",
     "note": "PVP 整合包",
     "icon": "static/icons/clients/ultimate-pvp.png"},
    {"id": "ukupvp", "name": "uku's pvp modpack", "type": "pack", "tags": ["PVP"],
     "platform": "modrinth", "endpoint": "ukupvp",
     "strategy": "modrinth_modpack", "kind": "modpack",
     "note": "uku 的 PVP 整合包",
     "icon": "static/icons/clients/ukupvp.webp"},
    {"id": "pvp-perfect", "name": "PvP Perfect", "type": "pack", "tags": ["PVP"],
     "platform": "modrinth", "endpoint": "pvp_perfect",
     "strategy": "modrinth_modpack", "kind": "modpack",
     "note": "PVP 整合包",
     "icon": "static/icons/clients/pvp-perfect.webp"},
    {"id": "mace-plus", "name": "MACE+", "type": "pack", "tags": ["PVP"],
     "platform": "modrinth", "endpoint": "macepvp+",
     "strategy": "modrinth_modpack", "kind": "modpack",
     "note": "MACE 玩法 PVP 整合包",
     "icon": "static/icons/clients/mace-plus.webp"},
    {"id": "spunky-pvp-plus", "name": "Spunky PVP Plus", "type": "pack", "tags": ["PVP"],
     "platform": "modrinth", "endpoint": "spunky-pvp-plus",
     "strategy": "modrinth_modpack", "kind": "modpack",
     "note": "PVP 向整合包",
     "icon": "static/icons/clients/spunky-pvp-plus.webp"},
    {"id": "ath", "name": "All The Hacks (ATH)", "type": "pack", "tags": ["作弊", "生存"],
     "platform": "web", "endpoint": "https://www.modpackindex.com/modpack/149934/all-the-hacks-ath",
     "strategy": "open_page", "kind": "page",
     "note": "黑客模组大合集（ATM 系 Parody），打开 Modpack Index 页面",
     "icon": ""},
]


def get_catalog() -> list[dict]:
    """返回目录副本（20 条）"""
    return [dict(i) for i in CATALOG]


def get_entry(client_id: str) -> Optional[dict]:
    """按 id 取条目，未命中返回 None"""
    for i in CATALOG:
        if i["id"] == client_id:
            return dict(i)
    return None


def github_latest_url(repo: str) -> str:
    """归一任意 GitHub 写法到 releases/latest API URL（幂等）。

    接受: "owner/repo"、"api.github.com/repos/owner/repo/releases/latest"、
    "github.com/owner/repo/releases"、"https://github.com/owner/repo/releases" 等。
    """
    r = (repo or "").strip().strip("/")
    if r.startswith("https://"):
        r = r[8:]
    elif r.startswith("http://"):
        r = r[7:]
    if r.startswith("api.github.com/"):
        r = r[len("api.github.com/"):]
    if r.startswith("repos/"):
        r = r[len("repos/"):]
    if r.startswith("github.com/"):
        r = r[len("github.com/"):]
    if r.endswith("/releases/latest"):
        r = r[: -len("/releases/latest")]
    elif r.endswith("/releases"):
        r = r[: -len("/releases")]
    return f"https://api.github.com/repos/{r}/releases/latest"


def github_releases_url(repo: str) -> str:
    """归一任意 GitHub 写法到 releases 列表 API URL（无尾斜杠）。

    尾斜杠会导致 GitHub API 404（.../releases/?per_page=30 实测不可用）。
    """
    return github_latest_url(repo)[: -len("/latest")]


def _is_plain_jar(name: str) -> bool:
    low = (name or "").lower()
    if not low.endswith(".jar"):
        return False
    return not any(b in low for b in _BAD_SUFFIXES)


def _sorted_jars(assets: list) -> list:
    """plain jar 过滤 + updated_at 降序（无时间戳者稳定在后）。"""
    jars = [a for a in assets or [] if _is_plain_jar(a.get("name") or "")]
    return sorted(jars, key=lambda a: a.get("updated_at") or "", reverse=True)


def pick_github_asset(release: Optional[dict]) -> Optional[dict]:
    """从 GitHub release JSON 里选可下载 jar 资产。

    过滤非 jar 与 -sources/-dev/-javadoc classifier；updated_at 最新者优先
    （真实案例 BleachHack：同 release 多 MC 版本 jar，取最新而非列表首个 1.17.1）。
    返回 {"filename", "url"} 或 None。
    """
    if not release:
        return None
    jars = _sorted_jars(release.get("assets") or [])
    if not jars:
        return None
    a = jars[0]
    return {"filename": a.get("name") or "", "url": a.get("browser_download_url", "")}


_MC_SUFFIX_RE = re.compile(r"[-_]MC(\d+(?:\.\d+)+)", re.IGNORECASE)
_NUM_RE = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?:\.(\d+))?")


def parse_mc_version(text: str) -> str:
    """从 tag/文件名启发式提取 Minecraft 版本号，取不到返回 ""。

    规则：-MC<ver> 后缀优先；否则首个"年份式(≥26).x"或"1.14~1.99.x"候选。
    1.0.2 / 0.2.0 / 1.0-SNAPSHOT 等自身版本号不算 MC 版本。
    """
    t = text or ""
    m = _MC_SUFFIX_RE.search(t)
    if m:
        return m.group(1)
    for m in _NUM_RE.finditer(t):
        major, minor = int(m.group(1)), int(m.group(2))
        if major >= 26 or (major == 1 and 14 <= minor <= 99):
            return ".".join(g for g in m.groups() if g)
    return ""


_STRICT_MC_RE = re.compile(r"^(?:\d+\.\d+(?:\.\d+)?|\d+\.\d+-snapshot(?:-\d+)?)$")


def strict_mc_version(candidate: str) -> str:
    """完整匹配才视为 MC 版本 id；实例名/含杂质字符串返回 ""。"""
    c = (candidate or "").strip()
    return c if _STRICT_MC_RE.match(c) else ""


def resolve_client_mc_version(game_versions, current_version, latest_release="") -> str:
    """客户端实例安装的 MC 版本回退链：条目标注 → 当前选中 → 最新正式版。"""
    for gv in game_versions or []:
        hit = strict_mc_version(gv)
        if hit:
            return hit
    hit = strict_mc_version(current_version or "")
    if hit:
        return hit
    return strict_mc_version(latest_release or "")


def format_github_release_items(releases: Optional[list]) -> list[dict]:
    """GitHub releases → 版本选择器条目（与 getModVersions 的 versions 同形）。

    仅留 plain jar；release 内资产按 updated_at 降序；跨 release 保持输入顺序
    （GitHub API 返回最新 release 在前）。id = 资产直链 URL（可直接下载）。
    """
    items: list[dict] = []
    for rel in releases or []:
        if not isinstance(rel, dict) or rel.get("draft"):
            continue
        tag = rel.get("tag_name") or ""
        pub = rel.get("published_at") or ""
        for a in _sorted_jars(rel.get("assets") or []):
            name = a.get("name") or ""
            url = a.get("browser_download_url", "")
            mv = parse_mc_version(name) or parse_mc_version(tag)
            items.append({
                "id": url,
                "name": name,
                "version_number": tag,
                "game_versions": [mv] if mv else [],
                "loaders": [],
                "date_published": a.get("updated_at") or pub,
                "downloads": a.get("download_count", 0),
                "filename": name,
                "url": url,
                "featured": False,
            })
    return items


def pick_modrinth_file(version: Optional[dict]) -> Optional[dict]:
    """从 Modrinth version JSON 的 files 里选 jar（primary 优先）。

    返回 {"filename", "url"} 或 None。
    """
    if not version:
        return None
    jars = [f for f in (version.get("files") or []) if _is_plain_jar(f.get("filename") or "")]
    if not jars:
        return None
    primary = [f for f in jars if f.get("primary")]
    chosen = primary[0] if primary else jars[0]
    return {"filename": chosen.get("filename", ""), "url": chosen.get("url", "")}


def client_dest_dir(minecraft_dir, current_version: str, is_isolated: bool,
                    isolated_mods_path) -> Path:
    """落盘目录：选中版本且隔离 → 隔离 mods 路径；否则 minecraft_dir/mods。

    与 main.py 现行下载规则同源（main.py downloadContent 分支）。
    """
    if current_version and is_isolated and isolated_mods_path:
        return Path(isolated_mods_path)
    return Path(minecraft_dir) / "mods"

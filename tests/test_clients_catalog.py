"""客户端目录 launcher_core/clients_catalog.py（20 条 = 14 client + 6 pack）+ 解析助手"""
from pathlib import Path

import pytest

from launcher_core import clients_catalog as cc

STRATEGIES = {"github_latest_jar", "modrinth_latest_jar", "meteor_download",
              "modrinth_modpack", "curseforge_search_jar", "open_page",
              "web_download"}
PLATFORMS = {"github", "modrinth", "curseforge", "web"}
KINDS = {"jar", "modpack", "page"}
CATEGORIES = {"作弊-综合", "作弊-辅助", "作弊-PVP", "PVP-竞技", "PVP-辅助"}
FIELDS = ("id", "name", "type", "category", "platform", "endpoint",
          "strategy", "note", "kind", "icon")


def test_catalog_schema_20_entries():
    items = cc.get_catalog()
    assert len(items) == 20
    ids = [i["id"] for i in items]
    assert len(set(ids)) == len(ids), "id 应唯一"
    for i in items:
        for k in FIELDS:
            assert k in i, f"{i.get('id')} 缺字段 {k}"
        assert i["strategy"] in STRATEGIES, i["strategy"]
        assert i["platform"] in PLATFORMS, i["platform"]
        assert i["type"] in ("client", "pack"), i["type"]
        assert i["kind"] in KINDS, i["kind"]
        assert isinstance(i["icon"], str), i["id"]
        # 图标本地化（QtWebEngine 无代理直连时 GitHub 外链超时）：仅允许 本地路径 或 空
        assert i["icon"] == "" or i["icon"].startswith("static/icons/clients/"), i["icon"]
        # endpoint 形态随 strategy：open_page/meteor_download/web_download=完整URL；github=owner/repo；其余=slug/搜索词
        if i["strategy"] in ("open_page", "meteor_download", "web_download"):
            assert i["endpoint"].startswith("http"), i["endpoint"]
        elif i["strategy"] == "github_latest_jar":
            assert "/" in i["endpoint"] and not i["endpoint"].startswith("http"), i["endpoint"]
        else:
            assert i["endpoint"] and not i["endpoint"].startswith("http"), i["endpoint"]


def test_catalog_composition_14_clients_6_packs():
    items = cc.get_catalog()
    clients = [i for i in items if i["type"] == "client"]
    packs = [i for i in items if i["type"] == "pack"]
    assert len(clients) == 14
    assert len(packs) == 6
    # 7 种 strategy / 4 种 platform 全覆盖
    assert {i["strategy"] for i in items} == STRATEGIES
    assert {i["platform"] for i in items} == PLATFORMS
    by_id = {i["id"]: i for i in items}

    # ---- LiquidBounce：内置网页下载（web_download）----
    lb = by_id["liquidbounce"]
    assert lb["strategy"] == "web_download"
    assert lb["endpoint"] == "https://liquidbounce.net/download"
    assert lb["type"] == "client" and lb["kind"] == "jar"
    assert lb["platform"] == "web"
    assert lb["category"] == "作弊-PVP"
    assert lb["icon"].startswith("static/icons/clients/liquidbounce")

    # ---- 14 客户端 ----
    assert by_id["meteor"]["strategy"] == "meteor_download"
    assert by_id["meteor"]["endpoint"] == "https://meteorclient.com/api/download"
    for gid in ("bleachhack", "fpsmaster", "combatant", "travel", "mastermind"):
        assert by_id[gid]["strategy"] == "github_latest_jar", gid
        assert by_id[gid]["platform"] == "github", gid
    assert by_id["mastermind"]["endpoint"] == "Snowiiii/MasterMind-Fabric"
    for mid in ("optix", "hedgehog", "miclient"):
        assert by_id[mid]["strategy"] == "modrinth_latest_jar", mid
        assert by_id[mid]["platform"] == "modrinth", mid
    assert by_id["optix"]["endpoint"] == "optixclient"
    assert by_id["axolotlclient"]["strategy"] == "curseforge_search_jar"
    assert by_id["axolotlclient"]["platform"] == "curseforge"
    for wid in ("wurst", "ares", "payload"):
        assert by_id[wid]["strategy"] == "open_page", wid
        assert by_id[wid]["endpoint"].startswith("http"), wid

    # ---- 6 整合包 ----
    modrinth_packs = [i for i in packs if i["strategy"] == "modrinth_modpack"]
    assert {i["endpoint"] for i in modrinth_packs} == {
        "the-ultimate-pvp-modpack", "ukupvp", "pvp_perfect", "macepvp+", "spunky-pvp-plus"}
    assert by_id["ath"]["strategy"] == "open_page"
    assert "modpackindex.com" in by_id["ath"]["endpoint"]

    # ---- category：13 客户端 5 细分值，包为空 ----
    assert {i["category"] for i in clients} == CATEGORIES
    assert all(i["category"] == "" for i in packs)

    # ---- 清单外旧条目必须已移除（API 库 / 纯优化模组 / 旧包）----
    for gone in ("fabric-api", "sodium", "lithium", "iris", "entityculling",
                 "immediatelyfast", "krypton", "indium", "nvidium", "moreculling",
                 "optifine", "re-pvp", "modpack-better-pvp", "1.8-pvp-pack", "pvpoptimized"):
        assert gone not in by_id, f"旧条目 {gone} 应移除"


def test_github_latest_url_normalization():
    assert cc.github_latest_url("Snowiiii/MasterMind-Fabric") == \
        "https://api.github.com/repos/Snowiiii/MasterMind-Fabric/releases/latest"
    # 已是完整 URL/带 api. 前缀 → 幂等归一
    assert cc.github_latest_url(
        "api.github.com/repos/Snowiiii/MasterMind-Fabric/releases/latest") == \
        "https://api.github.com/repos/Snowiiii/MasterMind-Fabric/releases/latest"
    assert cc.github_latest_url(
        "https://api.github.com/repos/FPSMasterTeam/FPSMaster-Edge/releases/latest") == \
        "https://api.github.com/repos/FPSMasterTeam/FPSMaster-Edge/releases/latest"
    # github.com 网页写法（带 /releases 尾）
    assert cc.github_latest_url("github.com/Snowiiii/MasterMind-Fabric/releases") == \
        "https://api.github.com/repos/Snowiiii/MasterMind-Fabric/releases/latest"
    assert cc.github_latest_url("https://github.com/Wurst-Imperium/Wurst7/releases") == \
        "https://api.github.com/repos/Wurst-Imperium/Wurst7/releases/latest"


def test_get_entry():
    e = cc.get_entry("mastermind")
    assert e and e["name"] == "MasterMind"
    assert cc.get_entry("no-such-id") is None


def test_github_releases_url_no_trailing_slash():
    # 冒烟发现："latest" 切片残留尾斜杠 → .../releases/?per_page=30 返回 404
    assert cc.github_releases_url("BleachDev/BleachHack") == \
        "https://api.github.com/repos/BleachDev/BleachHack/releases"
    assert cc.github_releases_url("github.com/Snowiiii/MasterMind-Fabric/releases") == \
        "https://api.github.com/repos/Snowiiii/MasterMind-Fabric/releases"
    assert not cc.github_releases_url("Trauncy209/Travel-Client").endswith("/")


def test_api_github_get_releases_uses_normalized_url():
    import launcher_core.api_github as ag
    src = open(ag.__file__, encoding="utf-8").read()
    assert "github_releases_url(" in src, "get_releases 应使用归一 URL 而非手工切片"


def _release(names, with_dates=False):
    assets = []
    for idx, n in enumerate(names):
        a = {"name": n, "browser_download_url": f"https://dl/{n}"}
        if with_dates:
            a["updated_at"] = f"202{idx}-01-01T00:00:00Z"
            a["download_count"] = idx * 10
        assets.append(a)
    return {"tag_name": "v1", "published_at": "2024-01-01T00:00:00Z", "assets": assets}


def test_pick_github_asset_jar_filtering():
    # 真实案例：FPSMaster-Edge 同时有 jar+zip → 选 jar
    got = cc.pick_github_asset(_release(["FPSMaster-1.0.2-beta.1.jar",
                                         "fpsmaster-edge-aot-1.0.2-beta.1.zip"]))
    assert got["filename"] == "FPSMaster-1.0.2-beta.1.jar"
    assert got["url"] == "https://dl/FPSMaster-1.0.2-beta.1.jar"


def test_pick_github_asset_prefers_plain_jar():
    # classifier (sources/dev/javadoc) 排除，普通 jar 优先
    got = cc.pick_github_asset(_release(["MasterMind-1.0-SNAPSHOT-sources.jar",
                                         "MasterMind-1.0-SNAPSHOT.jar"]))
    assert got["filename"] == "MasterMind-1.0-SNAPSHOT.jar"


def test_pick_github_asset_prefers_newest_updated_at():
    # 真实案例 BleachHack：同 release 多个 MC 版本 jar → 取 updated_at 最新（1.19.4 而非 1.17.1）
    rel = {"tag_name": "1.2.6", "assets": [
        {"name": "bleachhack-1.17.1.jar", "updated_at": "2022-04-06T14:56:29Z",
         "browser_download_url": "https://dl/old.jar"},
        {"name": "bleachhack-1.19.4.jar", "updated_at": "2023-04-02T19:51:37Z",
         "browser_download_url": "https://dl/new.jar"},
    ]}
    got = cc.pick_github_asset(rel)
    assert got["filename"] == "bleachhack-1.19.4.jar"
    assert got["url"] == "https://dl/new.jar"


def test_pick_github_asset_empty_and_no_jar():
    assert cc.pick_github_asset(None) is None
    assert cc.pick_github_asset({"assets": []}) is None
    assert cc.pick_github_asset(_release(["a.zip", "b-sources.jar", "c-dev.jar"])) is None


def test_parse_mc_version_heuristic():
    # -MC 后缀（Wurst 风格 tag）
    assert cc.parse_mc_version("v7.56pre2-MC26.2") == "26.2"
    # 年份式版本（≥26）
    assert cc.parse_mc_version("26.1.2") == "26.1.2"
    assert cc.parse_mc_version("meteor-client-26.2-32.jar") == "26.2"
    # 1.x 文件名（minor ≥14 才算 MC）
    assert cc.parse_mc_version("bleachhack-1.19.4.jar") == "1.19.4"
    assert cc.parse_mc_version("1.21.11") == "1.21.11"
    # 非 MC 版本号 → 空
    assert cc.parse_mc_version("FPSMaster-1.0.2-beta.1.jar") == ""
    assert cc.parse_mc_version("MasterMind-1.0-SNAPSHOT.jar") == ""
    assert cc.parse_mc_version("travel-client-1.0.0.jar") == ""
    assert cc.parse_mc_version("combatant-0.2.0-full.jar") == ""
    assert cc.parse_mc_version("no-version-here") == ""


def test_format_github_release_items():
    releases = [
        {"tag_name": "1.2.6", "published_at": "2023-04-02T00:00:00Z", "assets": [
            {"name": "bleachhack-1.17.1.jar", "browser_download_url": "https://dl/1.17.1.jar",
             "updated_at": "2022-04-06T14:56:29Z", "download_count": 5},
            {"name": "bleachhack-1.19.4.jar", "browser_download_url": "https://dl/1.19.4.jar",
             "updated_at": "2023-04-02T19:51:37Z", "download_count": 9},
            {"name": "notes.txt", "browser_download_url": "https://dl/n.txt"},
        ]},
        {"tag_name": "old", "published_at": "2020-01-01T00:00:00Z", "assets": [
            {"name": "x-sources.jar", "browser_download_url": "https://dl/x-sources.jar"},
            {"name": "x.jar", "browser_download_url": "https://dl/x.jar",
             "updated_at": "2020-01-01T00:00:00Z", "download_count": 1},
        ]},
    ]
    items = cc.format_github_release_items(releases)
    # plain jar only；release 内按 updated_at 降序；跨 release 保持调用方顺序
    assert [i["name"] for i in items] == [
        "bleachhack-1.19.4.jar", "bleachhack-1.17.1.jar", "x.jar"]
    assert items[0]["id"] == "https://dl/1.19.4.jar"
    assert items[0]["filename"] == "bleachhack-1.19.4.jar"
    assert items[0]["url"] == "https://dl/1.19.4.jar"
    assert items[0]["game_versions"] == ["1.19.4"]
    assert items[1]["game_versions"] == ["1.17.1"]
    assert items[2]["game_versions"] == []
    assert items[0]["version_number"] == "1.2.6"
    assert items[0]["downloads"] == 9
    assert all(i["loaders"] == [] for i in items)
    # 空输入
    assert cc.format_github_release_items([]) == []
    assert cc.format_github_release_items(None) == []


def test_pick_modrinth_file_jar_pref():
    # primary 是 sources、普通 jar 非 primary → 仍选 .jar 主文件
    version = {"files": [
        {"filename": "cool-sources.jar", "primary": True, "url": "u1"},
        {"filename": "cool.jar", "primary": False, "url": "u2"},
    ]}
    got = cc.pick_modrinth_file(version)
    assert got["filename"] == "cool.jar"
    assert got["url"] == "u2"
    # primary jar 优先
    version2 = {"files": [
        {"filename": "b.jar", "primary": False, "url": "ub"},
        {"filename": "a.jar", "primary": True, "url": "ua"},
    ]}
    assert cc.pick_modrinth_file(version2)["url"] == "ua"
    # 无 jar → None
    assert cc.pick_modrinth_file({"files": [{"filename": "x.zip", "url": "u"}]}) is None
    assert cc.pick_modrinth_file(None) is None


def test_client_dest_dir_branches(tmp_path):
    # 与 main.py 现行规则同源：选中版本且隔离 → 隔离 mods 路径，否则 minecraft_dir/mods
    global_mods = cc.client_dest_dir(str(tmp_path), current_version="1.20.1",
                                      is_isolated=False, isolated_mods_path=None)
    assert global_mods == tmp_path / "mods"
    iso = tmp_path / "versions" / "1.20.1" / "mods"
    got = cc.client_dest_dir(str(tmp_path), current_version="1.20.1",
                             is_isolated=True, isolated_mods_path=str(iso))
    assert got == iso
    # 无选中版本 → 全局（忽略隔离路径）
    assert cc.client_dest_dir(str(tmp_path), current_version="",
                              is_isolated=True, isolated_mods_path=str(iso)) == tmp_path / "mods"


def test_strict_and_resolve_client_mc_version():
    # 严格校验：完整 id 形状才算 MC 版本（实例名带数字不误判）
    assert cc.strict_mc_version("1.21.11") == "1.21.11"
    assert cc.strict_mc_version("26.3") == "26.3"
    assert cc.strict_mc_version("26.4-snapshot-2") == "26.4-snapshot-2"
    assert cc.strict_mc_version("Meteor Client 26") == ""
    assert cc.strict_mc_version("My-1.21-Pack") == ""
    assert cc.strict_mc_version("") == ""


def test_resolve_client_mc_version_chain():
    # 条目标注 → 当前选中（严格）→ 最新正式版；全部不可用返回 ""
    assert cc.resolve_client_mc_version(["1.21.11", "26.3"], "26.1", "26.4") == "1.21.11"
    assert cc.resolve_client_mc_version([], "26.3", "26.4") == "26.3"
    assert cc.resolve_client_mc_version([], "Meteor Client", "26.4") == "26.4"
    assert cc.resolve_client_mc_version(["Fabric", "OptiFine"], "", "") == ""
    assert cc.resolve_client_mc_version(["24w14a", "1.21.9"], "", "") == "1.21.9"  # 快照 id 跳过
    assert cc.resolve_client_mc_version([], "", "") == ""


def test_client_icons_localized_and_exist():
    # 应用内 QtWebEngine 无代理直连：GitHub 头像外链超时 → 必须本地化入库
    root = Path(__file__).resolve().parents[1]
    icons_dir = root / "ui" / "static" / "icons" / "clients"
    referenced = set()
    for e in cc.get_catalog():
        icon = e.get("icon") or ""
        if not icon:
            continue  # 允许个别条目无图标（字母兜底）
        assert not icon.startswith("http"), f"{e['id']} 图标仍为外链: {icon}"
        assert icon.startswith("static/icons/clients/"), \
            f"{e['id']} 图标应为 static/icons/clients/..., 实际 {icon}"
        f = root / "ui" / icon
        assert f.is_file() and f.stat().st_size > 0, f"图标文件缺失或为空: {f}"
        assert f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg"), \
            f"不支持的图标格式: {f}"
        referenced.add(f.name)
    assert referenced, "目录应有已本地化的图标"
    on_disk = {p.name for p in icons_dir.glob("*") if p.is_file()}
    assert referenced == on_disk, \
        f"孤儿文件 {on_disk - referenced or '无'} / 盘上缺失 {referenced - on_disk or '无'}"

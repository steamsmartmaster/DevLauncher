# 2026-10-03 下载页细化筛选 + 版本卡加载器角标 + 客户端页 设计

## 需求（用户确认）

1. **筛选细化（只改模组子页签）**：参考 Modrinth 截图样式，模组页左侧筛选面板：类别（带图标 chips + 查看剩余 N 项）、加载器（4 chips 带 logo）、安装环境（Client/Server）、游戏版本（chips + 查看剩余）。
2. **版本卡片右下角加载器图标**：`createVersionCard` 卡片右下角显示加载器 logo（Fabric/Forge/NeoForge/Quilt/OptiFine）；原版（无加载器）显示 3D 草方块图标。**图标现在从网上下载入库** `ui/static/icons/`，随包离线可用。
3. **下载页新增「客户端」子页签**：内置 14 个客户端 + 6 个 PVP 模组包目录，自动从 GitHub Releases / Modrinth / CurseForge 解析最新文件并**下载到 mods 目录（隔离版本走隔离路径）**；无 API 的条目提供打开网页。

## 架构决策

- **前端零网络不变**：所有 HTTP 仍走 Python（新增 `launcher_core/api_github.py`）；JS 只渲染与调 QWebChannel 槽。
- **模组搜索改新槽** `searchMods(query, game_versions, loaders, categories, environments, source)`（逗号分隔多选），旧 `searchContentFiltered` 保留服务整合包/数据包/世界，避免签名变更破坏现有测试。
- **facets**：`launcher_core/api_modrinth.py::build_facets()` 纯函数（可 pytest）——`versions`、`loaders`（categories:loader）、`categories`、`environments`（Modrinth 环境也是 category slug: client/server）各成 OR 组、组间 AND。CurseForge 源：新维度不支持，仅沿用 game_version（降级，UI 提示不影响）。
- **类别表**：以 `api.modrinth.com/v2/tag/category` 实际 slug 为准烘焙进 `build_facets`/前端数据（首 6 按截图：Adventure/Cursed/Decoration/Economy/Equipment/Food，剩余 13 展开）。类别图标用 lucide SVG（jsdelivr 下载入库）。
- **客户端目录** `launcher_core/clients_catalog.py`：常量列表 20 条，字段 `{id,name,type,platform,endpoint,strategy,note,kind}`；strategy ∈ `github_latest_jar | modrinth_latest_jar | modrinth_modpack | curseforge_search_jar | open_page`。
  - GitHub `releases/latest`（天然排除 prerelease，解决 FPSMaster 备注）→ assets 筛 `.jar`（排除 `-sources/-dev/-javadoc`，优先无 classifier）。
  - Modrinth `/v2/project/{slug}/version` 最新 → files 筛 `.jar`；模组包走现有 `downloadContent(id,'modpacks')` 复用。
  - CurseForge（AxolotlClient）：复用内置 key `api_curseforge.py`，search 取 slug → 最新文件。
  - Modpack Index（ATH）无 API → `open_page` 打开浏览器。
- **槽**：`getClients()` → `clientsLoaded(json)`；`downloadClient(id)` → 线程解析+下载 → `clientDownloadFinished(json)` / `errorOccurred`；`openClientSite(url)`。
- **落盘**：`minecraft_dir/mods`；若 `_current_mod_version` 且隔离 → `versions.get_mods_path()`（与 main.py:1585-1599 同规则，抽小助手 `_client_dest_dir()`）。

## UI 变更（`ui/index.html`）

- `#dlMods`：顶部保留 源下拉+搜索；下方改为两列布局 `.mod-filter-layout`（左 `.mod-filter-panel` 宽 248px，右 `#modsResults`）。面板四段 `modFilterSection`（类别/加载器/安装环境/游戏版本）+ 底部「清除筛选」。chips `.mf-chip[.active]`，每段首 N 项 + `.mf-more`（▼ 查看剩余 N 项/▲ 收起）。
- 状态 `modFilters = {categories:[], loaders:[], environments:[], versions:[]}`；`toggleModFilter(kind,value)`、`clearModFilters()`、`renderModFilterPanel()`；`searchContentFiltered('mods')` 分流到 `pythonInterface.searchMods(...csv...)`，**筛选非空时允许空关键词**（空关键词+空筛选才提示）。
- 版本卡：`createVersionCard` 追加 `<img class="version-loader-icon" src="static/icons/...">`（加载器匹配沿用 `/-Forge|NeoForge|Fabric|Quilt|OptiFine-/i`，否则 `grass_block.png`）；`.version-card{position:relative}` + `.version-loader-icon` 右下绝对定位、22px、drop-shadow。
- 客户端页：`.download-tabs` 追加按钮 `data-dl-tab="clients"`；`#dlClients` 内类型 chips 行 + 搜索框 + `#clientsResults` 网格；`switchDownloadTab` 首开 `clients` → `loadClients()`（不走 trending）；卡片：名称/类型徽章/平台徽章/备注(title+副行)/下载按钮（open_page 显示「打开页面」）；下载中禁用+spinner，`clientDownloadFinished` 后 toast + 卡片标记「已下载」。

## 错误处理

- GitHub/Modrinth/CF 解析失败 → `errorOccurred` toast，卡片按钮恢复。
- 无 .jar 资产（特殊情况）→ 错误信息带 endpoint 便于排查。
- 空目录/网络超时：requests timeout 15s，复用各 API 模块既有 try/except 返回 None/[] 风格。

## 测试（红→绿 TDD）

- **pytest `tests/test_clients_catalog.py`**：目录 schema（20 条、id 唯一、type/platform/strategy 枚举、endpoint 正则）、MasterMind endpoint 归一、`pick_github_asset`（jar 过滤/排序/空列表）、`pick_modrinth_file`（jar 偏好）、`build_facets`（四组结构与 AND/OR 语义）、`_client_dest_dir` 隔离分支。
- **JS `tests/test_mod_filter_panel.js`**：静态（面板四段 id/图标 src/查看剩余/清除筛选/新槽调用 `searchMods`）+ 行为（toggle/clear/展开收起计数/csv 拼装/空关键词守卫放行筛选态）。
- **JS `tests/test_clients_ui.js`**：静态（tab 按钮、`dlClients`、`clientsLoaded→renderClientList` 接线、下载按钮调 `downloadClient`）+ 行为（渲染 20 卡片数/类型过滤/搜索/open_page 按钮形态/下载中禁用与完成恢复）+ 版本卡图标断言（gras_block/loader src、右下 CSS）。
- 回归：全量 pytest + 6 个既有 JS 套件 + 提取 `<script>` `node --check` + `py_compile`。

## 不做（YAGNI）

- 不动侧栏导航（客户端是下载页子页签，不是第 9 侧栏页）。
- 不做 CurseForge 侧类别/环境 facet（API 维度不同，降级）。
- 不做运行时图标下载/缓存（本次直接入库）。
- 客户端不自动安装 Fabric API 依赖（备注文字提示）。

# 2026-10-04 客户端下载升级为完整实例安装 设计

## 需求（4 问确认）

1. **连着版本一起下载**：版本条目 `game_versions[0]` → MC 版本、`loaders[0]` → 加载器（空默认 Fabric），自动下载 MC + 加载器 + 客户端 jar，全部装进新建隔离实例；条目无 MC 版本时回退 当前选中版本（须校验像 MC 版本）→ Mojang 最新正式版
2. **默认版本隔离**：不管当前选中什么，一律新建/复用以实例名命名的隔离实例（与整合包安装一致）
3. **实例名**：版本选择器底部名称输入框（同整合包分支），默认值 = 客户端名，可改，留空用默认
4. **按钮不锁死**：完成后回到「下载」可再点（重复下载/换版本），下载中仅临时「下载中…」，永久「已下载」状态移除——与模组卡片一致

范围：13 客户端中 9 个有 API 条目走新管线；4 个 open_page 仍打开页面；6 个整合包维持现有管线。

## 方案

**A（已选）**：`ModpackImporter` 新增公开方法复用实例化四件套，进度走整合包导入弹窗（HMCL 风格）+ `modpackImporting` 并发锁 + 完成后自动刷新/选中新实例。
备选 B（内存拼 mrpack）/ C（独立模块复制配方）否决：hack 耦合脆 / 百行重复漂移。

## 后端

### `ModpackImporter.install_client_instance(instance_name, mc_version, loader, loader_version, report)`
1. `versions/<实例名>/` + `mods/`（存在复用，同名重下幂等）
2. `VersionManager.enable_version_isolation(实例名)`
3. `_ensure_vanilla_version(mc_version, report)`（缺则下原版）
4. `_create_version_json(...)`（Fabric/Quilt 直取 meta；Forge/NeoForge 占位）
5. `_install_loader_for_import(...)`（Forge 系 installer 合并，返回 warning）

### main.py `downloadClientVersion(client_id, version_id, custom_name)` 编排
- 六 strategy 直链解析逻辑不动（先解析快速失败）→ 再走长安装
- MC 回退链：`game_versions[0]` → 当前选中版本（`parse_mc_version` 校验）→ Mojang version manifest 最新正式版
- loader_version：`api_modloaders.get_recommended_loaders(mc_version)` 取该 loader 推荐版
- 实例名 = `custom_name.strip()` 或 `entry["name"]`
- 装完下 jar → `versions/<名>/mods/` → emit `modpackImportComplete`（现有 JS：成功面板 + `loadVersions` 刷新 + 自动选中新实例）+ `clientDownloadFinished`（清卡片态 + toast）
- 进度统一 `modpackImportProgress`；并发锁前端 `modpackImporting`（与整合包一致）

## 前端（ui/index.html）

- `openVersionPicker` clients 分支：显示 `#versionPickerNameInput`，`value = 客户端名`（查 `clientsData`）；标题 `选择版本 - <客户端名>`
- clients 回调：`modpackImporting` 锁拦截 → 卡片临时「下载中…」→ `openClientImportDialog(实例名)`（复用 `#modpackImportModal` 进度模式：藏信息区/确认钮、锁取消钮）→ `downloadClientVersion(id, versionId, customName)`
- `clientCardHtml`：移除永久「已下载」分支（按钮三态：下载 / 下载中… / 打开页面）；`onClientDownloadFinished` 只清下载中态 + toast

## 测试（红→绿）

- `tests/test_clients_ui.js` 改写：名称输入框默认值、cb 传 customName、无永久已下载、完成回「下载」、并发锁拦截、`openClientImportDialog` 触发；main.py 静态窗口扩至含 `install_client_instance(`
- 新建 `tests/test_client_instance_install.py`：四件套调用顺序/目录/隔离（mock 网络）+ MC 回退链纯函数
- 回归门：`python -m pytest tests` 全量 + JS 8 套 + `py_compile` + 提取 script `node --check`

## 不做（YAGNI）

- 不动 open_page / 整合包管线 / 版本选择器 mod 分支
- 不做客户端下载队列/断点续传
- 不新造进度 UI（复用导入弹窗）

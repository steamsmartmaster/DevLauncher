# 账号管理 + 插件系统 设计文档

日期：2026-09-27 · 状态：已确认（用户选定方案 A+A）· 仓库：D:\sss-data\workplace\DevLauncher

## 背景与目标

- 背景：启动器目前是单账号模型（`launcher_core/auth.py` 单条 `_login_data` 持久化到 `~/.mc-launcher/auth.json`，微软 OAuth 与离线登录二选一）；无任何插件基础设施。
- 目标：
  1. **多账号管理**：可添加多个账号（离线 + 微软），列表展示、一键切换、删除；启动游戏用当前选中账号；每个账号登录态独立持久化。
  2. **真实插件系统**：插件 = 本地 `plugins/` 目录下的 Python 包（manifest + 入口），宿主提供稳定 API；侧栏新增「插件」页，列出全部插件，点击进入插件详情页。
- 范围外（YAGNI）：在线插件市场/下载、子进程隔离、Windows 凭据管理器、微软登录 UI 改造（流程复用）、Fabric API 类兼容卡。

## 需求（已澄清）

| 项 | 结论 |
|---|---|
| 账号范围 | 多账号（离线+微软），列表/切换/删除，令牌按账号持久化 |
| 插件能力 | 真实扩展：自定义内容区 + 设置 + 宿主 API |
| 插件来源 | 仅本地 `plugins/` 文件夹扫描 |
| 详情页内容 | 基本信息、设置表单、自定义内容区、操作按钮（启用/禁用、打开文件夹、重载、卸载） |
| 插件入口 | 侧栏第 8 个页签「插件」 |

## 架构

### 账号管理 — `launcher_core/accounts.py`

```python
class AccountStore:
    # ~/.mc-launcher/accounts.json
    # { "current_id": "...", "accounts": [ {id, type: "offline"|"microsoft",
    #   name, uuid, data: <完整 login_data 含令牌>, created, lastUsed} ] }
    list() / get(id) / current() / add(data, type) / switch(id) /
    remove(id) / update(data) / migrate_legacy()  # 旧 auth.json → 首个账号
```

- `AuthManager` 改造：`_save_login_data/_load_login_data/logout` 改为经 `AccountStore` 读写；`get_login_data()` 返回 `store.current()` 的 data → **启动链路（main.py L395-400）零改动**。
- 微软令牌过期：切换/启动时用该账号 `refresh_token` 走既有 `refresh_login`，结果写回该账号。
- 迁移：`accounts.json` 不存在而 `auth.json` 存在 → 导入为第一个账号并设为 current；保留 `auth.json` 不删（兼容回滚）。
- 新增槽/信号（main.py `LauncherBridge`）：
  - `getAccounts()` → `accountsLoaded(json)`
  - `switchAccount(id)` → 更新指针 + 触发既有 `loginComplete`（侧栏自动跟随）+ `accountsLoaded`
  - `removeAccount(id)` → 删除；若删的是当前账号则回退指针（取 lastUsed 最新者，空则无账号态）

### 插件系统 — `launcher_core/plugins.py`

```
plugins/
├── enabled.json                # {"hello-sample": true, ...}   (dict: id -> bool)
└── <plugin-id>/
    ├── manifest.json           # {id,name,version,author,icon,description,
    │                            #  settings:[{key,label,type:text|toggle|number,default,choices?}]}
    ├── plugin.py               # class Plugin: def on_load(self, ctx): ...
    └── config.json             # 用户配置（由宿主读写）
```

- `PluginManager`：`scan()`（读全部 manifest，坏 manifest 记 warning 不崩）→ `load_enabled()`（importlib 按路径加载 entry，实例化 `Plugin`，注入 `PluginContext`）→ 生命周期 `enable/disable/reload/uninstall/open_folder`。
- `PluginContext` API（稳定面）：
  - `register_content(html: str)` — 注入详情页「自定义内容区」
  - `get_config()/set_config(dict)` — 按 manifest settings schema 校验（类型/缺省补齐）
  - `logger` — 插件命名日志
- 启停状态 `enabled.json`；新发现的插件默认**启用**。
- 加载失败的插件：列表照常显示，状态标 `error` + 错误摘要，不崩宿主。
- 新增槽/信号：
  - `getPlugins()` → `pluginsLoaded(json)`（id/name/version/author/icon/description/status: enabled|disabled|error/hasSettings/hasContent/errorMsg）
  - `getPluginDetail(id)` → `pluginDetailLoaded(json)`（基本信息 + settings schema+当前值 + contentHtml）
  - `setPluginEnabled(id, bool)`、`savePluginConfig(id, json)`、`reloadPlugins()` → 回发 `pluginsLoaded`
  - `openPluginFolder(id)`（QDesktopServices，同版本目录模式）、`uninstallPlugin(id)`（删目录，信号回发）

### UI — `ui/index.html`

- 侧栏第 8 `.nav-item data-page="plugins"`（puzzle SVG + tooltip「插件」），页标题映射 `'plugins': '插件'`。
- `pluginsPage` 两个视图（复用版本管理页 列表⇄详情 结构）：
  - **列表**：卡片网格（图标、名称、版本、作者徽章、状态徽章 已启用/已禁用/加载失败、简介）；空态提示。
  - **详情**：返回按钮 + 标题；基本信息区；操作按钮行（启用/禁用、打开文件夹、重新加载、卸载[confirm]）；设置表单（按 schema 渲染 text/toggle/number 输入，保存按钮）；自定义内容区容器。
- JS：`renderPluginList/renderPluginDetail/openPluginDetail/savePluginForm/togglePluginEnabled/...`；`navigateTo('plugins')` 时拉取列表；隔离/刷新不串页（沿用现有页签模式）。
- 账户页改造：账号列表（首字母头像、名称、类型徽章、当前标记）+ 点击切换 + 删除（confirm）+ 底部「添加账号」（离线表单 + 微软按钮，复用现有 `offlineLogin/startLogin` 流程，成功后自动入列并切换）。

### 示例插件 — `plugins/hello-sample/`

manifest + `plugin.py`：`on_load` 里 `register_content()` 输出一段说明卡片、`set_config()` 预置默认值；演示 settings schema（一个文本 + 一个开关 + 一个数字）。兼作插件开发文档。

## 数据流

1. 启动 → `AccountStore.migrate_legacy()` → 现有 `checkLoginStatus` 走 current 账号 → `loginComplete`。
2. 添加账号（离线/微软）→ `AuthManager` 产出 login_data → `store.add(type)` → 设为 current → `loginComplete` + `accountsLoaded`。
3. 启动游戏 → `get_login_data()` = current 账号 data（链路不变）。
4. 打开插件页 → `getPlugins()` → 渲染列表 → 点击 → `getPluginDetail(id)` → 渲染详情（设置表单 + contentHtml）→ 操作经槽回发 `pluginsLoaded` 刷新。
5. 插件启停/卸载/重载 → PluginManager 变更 → 回发列表；详情页操作后同步刷新详情。

## 错误处理

- 坏 manifest / entry 加载异常 → 该插件 status=error + errorMsg，扫描继续；日志 logger.warning。
- 配置保存 schema 校验失败 → 返回 `{success:false, error}` → toast，不写盘。
- 删除当前账号 → 指针回退 + 无账号时 UI 进入未登录态；删除失败 toast。
- 卸载插件需 confirm；卸载后列表刷新，详情返回列表。
- 所有 JSON 信号 `ensure_ascii=False`（中文直出，与现有约定一致）。

## 测试（TDD，仓内 tests/）

| 套件 | 覆盖 |
|---|---|
| `test_accounts.py` (pytest) | CRUD、迁移 auth.json、current 指针回退、持久化往返、remove 非法 id |
| `test_plugin_manager.py` (pytest) | 扫描（含坏 manifest 不崩）、启停状态持久化、config schema 校验/默认值、uninstall、示例插件加载 + ctx API、error 状态 |
| `test_account_ui.js` | 账号列表渲染、切换/删除/添加接线、类型徽章、空态 |
| `test_plugins_ui.js` | 侧栏第 8 页签、列表渲染、详情导航与返回、设置表单 schema 渲染、按钮接线、空态/error 态 |

回归门：既有 `test_version_filters`(61) + `test_tab_result_routing`(11) + `test_version_folders_ui`(22) + `test_loader_compatibility`(82) + `test_version_folders.py`(12) + `py_compile` + 提取 `<script>` `node --check`。

## 约束

- Python 3.14 / PyQt6；不引入新第三方依赖；插件加载仅用 stdlib（importlib/pathlib/json）。
- 帧安全：插件 HTML 视为受信本地内容（与主 UI 同源同权），不做沙箱（范围外）。
- 所有新 UI 文案中文；遵循既有页面结构/样式类命名。

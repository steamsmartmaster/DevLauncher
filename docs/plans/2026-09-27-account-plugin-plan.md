# 账号管理 + 插件系统 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILLS: Use mod-agent-developer or 计划执行师 to implement.
> **Testing:** Each task MUST use mod-test-developer for TDD (RED → GREEN).
> **Review:** After completion, use mod-review-requester for code review.
> **Verification:** Before claiming complete, use mod-completion-verifier.
> **Finalization:** Use mod-branch-finisher to finish and merge.

**Goal:** 多账号管理（离线+微软，切换/删除/持久化）+ 真实插件系统（本地 plugins/ 扫描、详情页、宿主 API）+ 侧栏「插件」页。

**Architecture:** `AccountStore`（accounts.json，旧 auth.json 自动迁移，`get_login_data()` 返回当前账号使启动链路零改动）；`PluginManager`（manifest 扫描 + importlib 加载 + PluginContext API + enabled.json）；UI 复用"列表⇄详情"页面结构。设计详见 `docs/plans/2026-09-27-account-plugin-design.md`。

**Execution Path:** mod-agent-developer

**通用约定（每个 task 都适用）**
- 工作目录 `D:\sss-data\workplace\DevLauncher`（注意：路径显示层可能掩码，探针用 `[IO.File]::Exists`）
- Python 3.14 / pytest 9 / node v24；**不引入新依赖**（插件仅 stdlib）
- 所有发给 JS 的 JSON 用 `ensure_ascii=False`
- 禁止 commit（用户未要求；全部完成后由 mod-branch-finisher 询问）
- 回归门（Task 8 全量跑）：
  - `python -m pytest tests/test_version_folders.py tests/test_accounts.py tests/test_plugin_manager.py -q` → 全 PASS
  - `node tests/test_version_filters.js` `node tests/test_tab_result_routing.js` `node tests/test_version_folders_ui.js` `node tests/test_loader_compatibility.js` `node tests/test_account_ui.js` `node tests/test_plugins_ui.js` → 全 0 FAIL
  - `python -m py_compile main.py launcher_core/auth.py launcher_core/accounts.py launcher_core/plugins.py`
  - 提取 index.html 全部 `<script>`（regex `/<script(?![^>]*\ssrc=)[^>]*>([\s\S]*?)<\/script>/g`）写 `%TEMP%\dl_script.js` → `node --check`

---

### Task 1: AccountStore（多账号持久化 + 迁移）

**Files:**
- Create: `launcher_core/accounts.py`
- Test: `tests/test_accounts.py`

**接口（必须实现）：**
```python
class AccountStore:
    def __init__(self, data_dir: Path | None = None)  # 默认 Path.home()/".mc-launcher"
    # accounts.json: {"current_id": str|None, "accounts": [ {id, type, name, uuid,
    #   data: dict(完整login_data), created: float, lastUsed: float} ]}
    def list(self) -> list[dict]                 # 按 lastUsed 降序，data 不外泄(返回摘要)
    def get(self, account_id) -> dict | None
    def current(self) -> dict | None             # 返回完整 data(含令牌) 或 None
    def current_id(self) -> str | None
    def add(self, data: dict, type: str) -> dict # id=uuid4；同名同类型离线=覆盖更新；微软按 uuid 去重
    def switch(self, account_id) -> dict         # 校验存在，更新 current_id+lastUsed，持久化
    def remove(self, account_id) -> None         # 删条目；current 被删→指针回退 lastUsed 最新；全空→None
    def update_data(self, account_id, data) -> None  # 微软令牌刷新回写
    def migrate_legacy(self) -> bool             # accounts.json 不存在且 auth.json 存在→导入为首个账号
                                                 # (type 按 access_token=="offline_token" 判定)；保留 auth.json
```
- 摘要字段：`{id, type, name, uuid, lastUsed, isCurrent}`（**不含 data**）
- 存盘原子性：写临时文件再 `replace`；目录自动创建。

**Steps:**
1. 写 `tests/test_accounts.py`（≥12 用例）：add+list 摘要不含 data / current 指针与 switch / switch 非法 id 抛错或返回 None（选后者：返回 None 不改指针）/ remove 当前→回退 / remove 最后一个→current_id None / 同名离线覆盖 / 微软 uuid 去重 / 持久化往返（新实例读回）/ migrate_legacy 判定 type 离线与微软 / migrate 不覆盖已存在 accounts.json / update_data 回写 / list 按 lastUsed 降序
2. `python -m pytest tests/test_accounts.py -q` → **RED**（ImportError/全 FAIL）
3. 实现 `launcher_core/accounts.py`
4. `python -m pytest tests/test_accounts.py -q` → **GREEN 全 PASS**
5. `python -m py_compile launcher_core/accounts.py`

---

### Task 2: AuthManager 接入 AccountStore

**Files:**
- Modify: `launcher_core/auth.py`（`__init__`、`_save_login_data`、`_load_login_data`、`_clear_saved_data`、`offline_login`、`complete_login`、`refresh_login`、`get_login_data`、新增 `logout` 语义）
- Test: `tests/test_accounts.py`（追加用例，仍归 Task 1 文件）

**改造点：**
- `AuthManager.__init__(client_id, redirect_url, store: AccountStore | None = None)`：无则自建；启动时 `store.migrate_legacy()`
- `complete_login()` / `offline_login()` 成功后：`store.add(login_data, type)` 并自动 `switch` 到它（添加即切换）
- `get_login_data()` → `store.current()`；`_load_login_data` 兼容语义由 store 承担
- `refresh_login(refresh_token)` 成功 → `store.update_data(current_id, new_data)`
- `logout()` → `store.remove(store.current_id())`
- 迁移后的 `auth.json` 不再读写（store 成为唯一事实源）

**Steps:**
1. `tests/test_accounts.py` 追加（≥5 用例）：offline_login 入库并成为 current / get_login_data 返回当前 / logout=remove 当前 / refresh 回写 / migrate 在 AuthManager 构造时触发（tmp data_dir 注入——`AccountStore(data_dir=tmp)`，AuthManager 传 store）
2. RED → 实现 auth.py 改造 → GREEN
3. `python -m py_compile launcher_core/auth.py`；确认 `main.py` 无需改启动链路（`self.auth.get_login_data()` 语义不变）

---

### Task 3: Bridge 账号槽与信号（main.py）

**Files:**
- Modify: `main.py`（`LauncherBridge` 信号区 ~L107-123、新槽、`_on_*` 槽接线区 ~L1948、`checkLoginStatus` 无需动）
- Test: `tests/test_account_ui.js`（静态接线部分 + 渲染，见 Task 4）

**新增：**
```python
accountsLoaded = pyqtSignal(str)   # JSON 列表摘要
@pyqtSlot(result=str) def getAccounts(self)        # emit accountsLoaded(json.dumps(list, ensure_ascii=False))
@pyqtSlot(str) def switchAccount(self, account_id) # store.switch → emit accountsLoaded + loginComplete(current)
@pyqtSlot(str) def removeAccount(self, account_id) # store.remove → emit accountsLoaded + loginComplete(新current或未登录态)
```
- `loginComplete` 复用：`checkLoginStatus()` 逻辑抽出为 `_emit_login_status()` 供复用；无账号时 emit `{loggedOut:true}` 让 JS 进入未登录态（JS 侧处理：显示"未登录"）
- 连接注册处按既有模式挂接。

**Steps:**
1. 先做 Task 4 的测试文件骨架（静态断言：main.py 含 `accountsLoaded = pyqtSignal`、`def getAccounts`、`def switchAccount`、`def removeAccount`、`ensure_ascii=False`）→ RED
2. 实现 main.py 槽/信号 → `node tests/test_account_ui.js` 静态部分 GREEN（渲染断言留到 Task 4）

---

### Task 4: 账户页 UI 改造

**Files:**
- Modify: `ui/index.html`（`#accountPage` ~L2435-2460、CSS ~L422-481 附近新增、JS `offlineLogin` ~L4971、`updateLoginStatus` ~L5025 附近、`navigateTo` account 分支拉取）
- Test: `tests/test_account_ui.js`

**UI 结构：**
- 账号列表 `#accountList`：卡片 = 首字母头像圆、`#accountName`、类型徽章（离线/Microsoft）、当前标记（√ 亮白描边）；整卡点击 → `switchAccount(id)`（已是当前则无操作）
- 卡片悬停出删除按钮 `🗑`（inline SVG）→ `confirm()` 二次确认 → `removeAccount(id)`
- 底部添加区：复用现有离线表单（`toggleOfflineForm/offlineLogin`）+ 微软按钮（`startLogin`）；登录成功回调（`updateLoginStatus`）后追加 `getAccounts()` 刷新列表
- 空态：「暂无账号，添加一个吧」
- `navigateTo('account')` → 调 `getAccounts()`

**JS 函数（需可被 extract_func 提取、无外链）：**
`renderAccountList(accounts)`、`switchAccount(id)`、`removeAccount(id)`、`confirmRemoveAccount(id)`、`accountCardHtml(a)`。

**Steps:**
1. 完善 `tests/test_account_ui.js`（≥20 断言）：renderAccountList 卡片数/徽章文案/当前标记/isCurrent 排除 data 泄漏（断言渲染不出现 `access_token`）、空态、cardHtml 首字母、switch/remove/confirm 接线调用 stub pythonInterface、静态：nav 账户页 navigateTo 拉取 getAccounts、index.html 含 renderAccountList/switchAccount/removeAccount
2. RED（61 式：先大量 FAIL）→ 实现 index.html → GREEN
3. 回归：`node tests/test_version_filters.js` 仍 61/0（同文件改动不破坏既有函数）

---

### Task 5: PluginManager + 示例插件

**Files:**
- Create: `launcher_core/plugins.py`
- Create: `plugins/hello-sample/manifest.json`、`plugins/hello-sample/plugin.py`
- Test: `tests/test_plugin_manager.py`

**manifest.json：**
```json
{"id": "hello-sample", "name": "示例插件", "version": "1.0.0",
 "author": "DevLauncher", "icon": "👋", "description": "演示插件能力：设置与自定义内容区",
 "settings": [
   {"key": "greeting", "label": "问候语", "type": "text", "default": "你好"},
   {"key": "enabled_anim", "label": "显示动画", "type": "toggle", "default": true},
   {"key": "max_items", "label": "最大条目", "type": "number", "default": 5}
 ]}
```
**plugin.py：**
```python
class Plugin:
    def on_load(self, ctx):
        cfg = ctx.get_config()
        ctx.register_content(f"<div class='plugin-content'>…{cfg['greeting']}…</div>")
```

**接口：**
```python
class PluginContext:      # 每插件一个
    register_content(html: str)      # 详情页自定义内容区（后注册覆盖先注册）
    get_config() -> dict             # schema 默认值补齐
    set_config(dict) -> None         # 类型校验(text/toggle/number) + 存 config.json
    logger                           # logging.getLogger(f"plugin.{id}")
class PluginManager:
    def __init__(self, plugins_dir: Path | None = None)  # 项目根/plugins
    def scan(self) -> list[dict]     # 全部 manifest 摘要{id,name,version,author,icon,description,
                                     #  status: enabled|disabled|error, errorMsg, hasSettings, hasContent}
    def detail(self, plugin_id) -> dict | None  # 摘要 + settings(schema+value) + contentHtml(enabled且加载成功才有)
    def set_enabled(id, bool)        # 持久化 enabled.json；disable 时丢弃实例与 content
    def save_config(id, cfg) -> dict # {"success": bool, "error": str|None}
    def load_all(self)               # 启动用：enabled 的全部 on_load（单个异常→status=error 不崩）
    def reload(self, id=None)        # 重载单个/全部
    def uninstall(id) -> bool        # shutil.rmtree（拒绝路径穿越：id 必须匹配已扫描项）
    def folder_of(id) -> Path | None
```
- 新发现插件默认启用；`enabled.json` 缺失按全启用处理。
- 坏 manifest（缺 id/name/非法 JSON）→ 不入列表，logger.warning，不崩。

**Steps:**
1. `tests/test_plugin_manager.py`（≥16 用例，tmp_path 注入 plugins_dir）：scan 正常/坏 JSON 不崩/缺字段跳过、默认启用、set_enabled 持久化+重扫生效、detail 含 schema+默认值+contentHtml、disable 后 contentHtml 空、save_config 类型校验（text 收 str、toggle 收 bool、number 收 int/float、坏 key 拒绝）、set_config 默认补齐、on_load 异常→error 状态+errorMsg、uninstall 删目录+非存在返回 False、folder_of、卸载非法 id 拒绝、示例插件真实加载（指向仓库 plugins/）产出 contentHtml、reload 后 content 更新、list 按名称排序
2. RED → 实现 plugins.py + hello-sample → GREEN → `python -m py_compile launcher_core/plugins.py`

---

### Task 6: Bridge 插件槽与信号（main.py）

**Files:**
- Modify: `main.py`（信号区新增 `pluginsLoaded`/`pluginDetailLoaded`；槽；启动时 `plugin_manager.load_all()`（放 `checkLoginStatus` 同期的初始化区）；MainWindow 持有 `self.plugins = PluginManager()` 传给 bridge 或 bridge 直接持）
- Test: `tests/test_plugins_ui.js`（静态接线部分）

**新增槽：**
```python
pluginsLoaded = pyqtSignal(str)
pluginDetailLoaded = pyqtSignal(str)
@pyqtSlot(result=str) getPlugins()
@pyqtSlot(str) getPluginDetail(id)
@pyqtSlot(str, bool) setPluginEnabled(id, enabled)   # → pluginsLoaded
@pyqtSlot(str, str) savePluginConfig(id, jsonCfg)    # 校验结果 → pluginDetailLoaded(带success) 或 toast 由 JS 做
@pyqtSlot() reloadPlugins()                          # → pluginsLoaded
@pyqtSlot(str) openPluginFolder(id)                  # QDesktopServices（防穿越：folder_of 校验）
@pyqtSlot(str) uninstallPlugin(id)                   # → pluginsLoaded
```

**Steps:**
1. `tests/test_plugins_ui.js` 静态断言先行（main.py 含 7 个槽名 + 2 个信号 + `load_all()` 调用）→ RED
2. 实现 main.py → 静态 GREEN

---

### Task 7: 插件页 UI（列表 + 详情 + 侧栏页签）

**Files:**
- Modify: `ui/index.html`：
  - 侧栏 `.nav-items` ~L1918-1946 后追加第 8 项（puzzle SVG、`data-page="plugins"`、tooltip「插件」）
  - 页标题映射 ~L2724 加 `'plugins': '插件'`
  - 新增 `#pluginsPage`（两个视图：`.plugin-list-view` / `.plugin-detail-view`）
  - CSS：`.plugin-card`、`.plugin-badge`（状态三色：启用亮白/禁用灰/错误红点）、`.plugin-settings`、`.plugin-content-box`、操作按钮复用 `.settings-file-btn`
  - JS：`renderPluginList/renderPluginDetail/openPluginDetail/backToPluginList/savePluginForm/togglePluginEnabled/reloadPlugin/uninstallPlugin(open folder 同)`
- Test: `tests/test_plugins_ui.js`

**列表视图：** 卡片网格 = 图标(大)、名称、`v1.0.0 · 作者`、状态徽章、简介两行截断；error 卡片显示 errorMsg 悬浮提示；空态「放入 plugins/ 文件夹即可识别」。
**详情视图：** 返回按钮 + 标题；基本信息 dl（id/版本/作者/目录路径缩略）；操作行：[启用|禁用] [打开文件夹] [重新加载] [卸载(confirm)]；设置表单（text→input、toggle→checkbox、number→input[type=number]）+「保存设置」；自定义内容区 `<div id="pluginContent">` 注入 contentHtml（禁用态显示「启用插件后可用」占位）。
**导航：** `navigateTo('plugins')` → `getPlugins()`；详情打开/操作后回发的 `pluginDetailLoaded`/`pluginsLoaded` 分别刷新对应视图（带 `currentDetailId` 判定）。

**Steps:**
1. 完善 `tests/test_plugins_ui.js`（≥25 断言）：nav 第 8 项与 data-page、页标题映射、renderPluginList 卡片数/徽章文案/空态/error 态、openPluginDetail→getPluginDetail 调用、renderPluginDetail 表单按 schema 三类型渲染、保存/启停/卸载(confirm)/打开文件夹/返回 接线、静态：index.html 7 槽调用 + container ids 存在
2. RED → 实现 → GREEN
3. 回归 4 套既有 JS（同文件大改动）全绿；提取 `<script>` `node --check`

---

### Task 8: 全量回归 + 收尾

**Steps:**
1. 跑"通用约定-回归门"全部命令，逐项确认输出（pytest X passed / 各 JS XX/0 / py_compile 静默 / node --check OK）
2. `git diff` 逐块复核（重点：index.html 大文件只增不误删——参照历史教训：曾误删 commonVersions/SVG 段）
3. 手工冒烟（能起 GUI 时）：`python main.py`——账户页加/切/删离线账号、插件页示例插件详情/设置保存/禁用启用/打开文件夹
4. 汇报 + 用 mod-review-requester 走审、mod-completion-verifier 出证据后，由 mod-branch-finisher 询问提交/推送方式（**未经用户确认不 commit**）

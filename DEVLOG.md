# DevLauncher Devlog

## 2026-09-20 — 整合包导入修复 & UI 优化

### 修复：client-overrides 支持
部分 Modrinth 整合包（如 NON）使用 `client-overrides/` 目录而非标准 `overrides/`。之前 `_import_modrinth()` 只提取 `overrides/` 下的文件，导致 `client-overrides/mods/` 中的模组和 `client-overrides/config/` 中的配置未被解压。

**改动：**
- `modpack_importer.py:_import_modrinth()` — 解压逻辑同时支持 `client-overrides/` 和 `overrides/` 前缀
- `modpack_importer.py:detect_format()` — 增加 `client-overrides/modrinth.index.json` 的格式检测

### 优化：导入弹窗 HMCL 风格进度
将导入进度从简单的百分比条改为 HMCL 风格的详细文件列表：
- 步骤图标（→/✓）+ 步骤标题 + 文件计数副标题
- 每个文件显示独立进度条（下载中）或 ✓ 标记（已完成）
- 下载中文件优先显示，已完成文件按时间排序
- 导入过程中弹窗不可关闭（`modpackImporting` 锁定）

**改动：**
- `index.html` — 重构 `#modpackImportProgress` 区域，新增 `.hmcl-file-*` CSS
- `index.html:updateModpackImportProgress()` — 渲染 per-file 进度条

### 修复：侧边栏 Logo 间距
D_ logo 的 D 和 _ 符号在 48x48 尺寸下挤在一起。

**改动：**
- `index.html` — 调整 SVG `translate` 和 underscore `rect` 的 y 坐标，增加 ~2px 间距

### 新增：导入整合包 SVG 图标
替换原来的 📥 emoji 为矢量图标（箭头+碗状容器），确保在各尺寸下清晰显示。

**改动：**
- 新增 `ui/icon-modpack-import.svg`
- `index.html` — 按钮改为 inline SVG

## 2026-09-25 — 导入进度不回退 & 并发下载提速

### 修复：大整合包导入时计数"从 1 重新开始"
两个根因：
1. **刻度切换**：模组下载阶段显示 `150/150`，随后提取阶段 `report(85, 100, ...)` 变成 `85/100`，看起来像重置。
2. **重复导入**：取消按钮无法真正中止导入线程，关闭弹窗后 `modpackImporting` 被清掉，再次导入会启动第二个并发线程、计数从 1 重来。

**改动：**
- `index.html` — 新增 `modpackImportLastFileCount` 粘性计数：一旦看到文件级计数，后续提取/配置/原版阶段都保持 `X/Y` 显示，不再回落到 `current/total`
- `index.html` — 导入期间禁用「取消」按钮（文案改「导入中...」），`closeModpackImportModal` 在导入中直接 toast 拦截；`triggerModpackImport`/`onModpackFileSelected*`/`confirmModpackImport` 四处加重复导入守卫
- `modpack_importer.py` — 下载完成后的所有阶段汇报（提取 overrides/文件、创建版本配置、导入完成）统一带上 `downloaded, total, file_states`，Python 侧计数全程单调

### 修复：导入线程异常导致弹窗卡死
`main.py:importModpack` 的 `_do_import` 异常分支只发 `errorOccurred`，从不发 `modpackImportComplete` → 弹窗永远停在"导入中"。

**改动：**
- `main.py` — 异常时补发 `modpackImportComplete({success:false, error})` + `gameStateChanged("idle")`

### 优化：并发下载提速
- 线程池 8 → 16（CurseForge / Modrinth / MultiMC / redownload 四处），`future.result` 超时 120s → 180s
- 新增独立 `download_session`（连接池 32、`User-Agent: DevLauncher/1.0`），下载 CDN 不再携带 CurseForge API key / Accept 头
- `_download_file` 改用 session + 64KB chunk；`_download_missing_libraries` 改为 8 线程并行
- MultiMC 路径的模组下载重写为文件计数风格（file_states + 锁内 report），`redownload_modpack_mods` 同样补齐 file_states 与逐文件汇报

### 修复：原版安装进度回调不生效
`minecraft_launcher_lib` 的 `setStatus` 回调收到的是**字符串**而非 dict，旧的 `isinstance(status, dict)` 永远不命中。现按字符串匹配 download/extract/complete 阶段，且按阶段去重（每文件一次 setStatus，避免数百次 JS 调用）。

### 修复：overrides 目录下的 modrinth.index.json
`detect_format()` 会把 `overrides/modrinth.index.json` 路由给 Modrinth 导入器，但 `_read_modrinth_manifest` / `_import_modrinth` 只按根目录路径打开 → KeyError。新增 `_find_modrinth_index()` 三个候选位置查找（根 / overrides / client-overrides）。

### 修复：redownload 无进度、错误信息被吞
- `main.py:redownloadModpackMods` 接入 `progress_callback`，双发 `modpackImportProgress` + `gameStateChanged("installing", ...)`，结束发 `idle`
- 错误信息回退读取 `errors` 列表前 3 条，不再固定显示"未知错误"

### 自动化验证（mock 下载，不走网络）
- 4 个格式路径（mrpack 根索引 / overrides 索引 / CurseForge / MultiMC）均通过：文件计数全程单调不回退、末段阶段携带计数、done/error 状态齐全、版本 JSON 与隔离 mods 目录生成正确
- `python -m py_compile` + `node --check`（提取的 `<script>`）通过

## 2026-09-25 — 字节级实时进度 & Forge 导入修复

### 优化：导入进度条改为字节级实时
之前 `_download_file` 只在**文件完成时**汇报一次，文件条 0%→100% 直接跳变，副标题只在完成时更新计数。

**改动：**
- `modpack_importer.py` — `_download_file` 新增 `progress_cb(bytes_done, bytes_total)`（64KB chunk 逐段回调）；新增静态 `_tracked_progress_cb()`：更新对应 file_state 的 `progress`（0-100），全批共享 `throttle` 字典按 0.15s 节流发 report（16 线程并发不刷爆 UI）
- 四处下载循环（CurseForge / Modrinth / MultiMC / redownload）全部接入；CurseForge 路径补齐 file_states（此前没有）
- `index.html` — 新增弹窗整体进度条 `#modpackImportOverallFill`：`overallPct = (已完成 + Σ进行中字节%) / 总数`；副标题在下载中追加 ` · NN%`（message 已含 `X/Y` 时不重复拼接）；文件条填充宽度改用 `f.progress`；侧边栏下载面板显示 `X/Y · NN%`、文件名旁显示当前百分比

### 修复：导入 Forge 整合包后不显示加载器、启动缺库
用户导入 The Other Side（Forge1.20.1）后加载器页显示"未安装"。三个根因：
1. `_create_version_json()` 给 Forge 版本写**假** `mainClass: FMLClientTweaker` 且 `libraries: []`，真正的 Forge 从未安装
2. `_import_modrinth` 不调用 `_ensure_vanilla_version()`，父版本 `versions/1.20.1` 目录根本不存在
3. 版本 JSON 缺 `jar` 字段，classpath 不含原版 client jar

**改动：**
- `modpack_importer.py` — JSON 模板增加 `"jar": mc_version`；删除 forge/neoforge 假 mainClass 占位；新增 `_install_loader_for_import()`：forge/neoforge 走真实安装器合并（HMCL 式），fabric/quilt 仍由 JSON 模板内联（原逻辑已完整）；三条导入流程（CF/Modrinth/MultiMC）在创建 JSON 后调用并把失败转为 `warning` 透出；Modrinth 流程补调 `_ensure_vanilla_version()`
- `modpack_importer.py` — `_ensure_vanilla_version` 改为**同时检查 client jar**：有 JSON 无 jar 的半安装状态不再被短路跳过

### 修复：api_modloaders 对"整合包版本"水土不服
`install_mod_loader` 把版本 id 当 MC 版本用，整合包 id（`The Other Side-1.20.1`）会让 Forge maven 坐标、Fabric meta URL 全部404；且 `install_mod_loader` 统一传 `installer_url=` 关键字，而 Fabric/Quilt/OptiFine/NeoForge 的 `install()` 签名没有该参数 → **TypeError**（OptiFine 还有裸用 `installer_url` 的 NameError，等于一直装不上）。

**改动：**
- `api_modloaders.py` — 新增 `_resolve_mc_version()`：沿 `inheritsFrom` 链（最多5层）取真实原版版本；Forge 用它拼 maven 坐标与 `installClient` 输出目录，Fabric/Quilt 用它拼 meta URL
- `api_modloaders.py` — Forge 现代分支 forge 目录发现：构造 id 不存在时在 `versions/` 下按 `-Forge-<ver>` 后缀回退查找；合并时 `id=版本名`、`jar` 有 `inheritsFrom` 时保持父版本（不再覆盖成整合包自身）
- `api_modloaders.py` — Fabric/Quilt/OptiFine/NeoForge `install()` 全部补 `installer_url` 参数；NeoForge 从安装器 `install_profile.json` 指向的 version.json 合并 `mainClass`/`arguments`（此前只合库，缺 mainClass 起不来）
- `api_modloaders.py` — `get_installed_loaders()` 沿 `inheritsFrom` 链合并父版本 libraries 再检测（父版本装了加载器时子版本也能识别）
- `main.py` — `installModLoader()` 删除"把整合包版本解析回原版父版本"的逻辑，加载器直接装进所选版本 JSON

### 优化：模组列表加载提速
`loadMods()` 串行逐 jar 解压两次（元数据 + 图标）再 base64 进大 JSON，60+ 模组明显卡顿。

**改动：**
- `main.py` — `ThreadPoolExecutor(8)` 并行构建 `ModInfo`；持久缓存 `modcache.json`（与 mods 目录同级），键 `文件名|size|mtime`，仅写当前文件防膨胀；任一 jar 变更自动重建

### 修复：用户包 The Other Side-1.20.1（实机）
- 用修好的管线重跑：补装原版 1.20.1（json+jar+资源，libraries.minecraft.net SSL 抖动用串行回填脚本收敛）、重写版本 JSON、安装 Forge 47.4.22 并合并（29 库、`mainClass=BootstrapLauncher`、`jar=1.20.1`、检测出 forge）
- `minecraft_launcher_lib.command.get_minecraft_command` 干跑：classpath 94 项含原版 jar 与 11 个 forge 库，mainClass 正确

### 自动化验证（mock 下载，不走网络）
- 重建离线测试套件（临时文件丢失后重写）：4 条流程 + 不支持格式 全过
  - 断言字节级进度（存在 `progress=50` 的 downloading 状态快照）、文件计数单调、下载后粘性计数、`_ensure_vanilla_version` 按 MC 版本调用、`install_mod_loader` 收到 `(loader, 版本名, loader_ver, minecraft_dir)`、fabric 内联 JSON 分支不触发安装器
- `python -m py_compile`（main + 4 个 launcher_core 模块）+ `node --check`（提取 `<script>`）通过

### 修复：版本列表出现"幽灵原版"（导入多一个 1.21.11、删包又跟着消失）
导入 1.21.11 整合包后列表同时出现 `NON-1.21.11` 和 `1.21.11`；删除整合包后 `1.21.11` 条目也从列表消失（目录仍在磁盘）。根因：`get_installed_versions()` 的过滤里有一条 `elif v["id"] in parent_refs: append` —— 被某个整合包 `inheritsFrom` 引用的原版父版本会被放行显示；删包后引用消失，同一目录又被隐藏，于是"出现/消失"都跟着整合包走（实机日志：删 NON-1.21.11 时已安装计数 5→3，掉了两个）。

**改动：**
- `launcher_core/versions.py` — 过滤规则简化为：**有 `devlauncher.cfg`（用户管理）或有 `inheritsFrom`（整合包）才显示**；其余（自动补装的原版父版本）无论是否被引用一律隐藏；删除 parent_refs 引用收集逻辑
- `main.py` — `installVersion()` 成功后若版本尚无 `devlauncher.cfg` 则写入（`isolation: false`）：用户主动安装/修复的原版从此在列表可见（此前无 cfg 的原版安装同样会被误隐藏）；同时是"想单独保留这个原版"的入口——下载页点安装即转正
- 删除天然只动本体：`delete_version()` 只移动单个版本目录（回归验证：删包后父版本目录完好、`_removed` 里只有包）

**验证：**
- 新增离线测试 `version-list-filter`：引用中的父版本隐藏、孤儿父版本隐藏、带 cfg 版本可见、删包不级联、写 cfg 转正 —— 6/6 全过
- 实机 `.minecraft` 复查：可见 = 1.12.2 / 1.4.5 / Fabulously Optimized 10.2.2（1.20.1、1.20.2、1.21.11 幽灵目录保持隐藏）

### 修复：导入文件列表强制回底 & 进度 98-99% 变慢
1. 每次进度刷新（0.15s 节流）重建文件列表后执行 `scrollTop = scrollHeight`，用户往上翻立刻被拽回底部（下载面板同款问题）。
2. 整体进度按**文件个数**加权：最后 1-2 个大文件只占 1/N 条宽，进度条在 98-99% 龟速爬行；下载收尾后提取/创建配置/补装原版/安装加载器阶段又把条钉死在 100%（有文件失败则钉死 98%），体感就是"一到 98-99% 就变慢"。

**改动：**
- `ui/index.html` — 文件列表**保留 scrollTop**（先存后恢复，不再强制回底）：导入弹窗 + 下载面板两处；副标题的 `— X/Y` 计数只在下载中或"已下载/导入完成"消息时追加（补装原版/安装加载器阶段不再带模组计数）
- `ui/index.html` — 进度条**两段式 + 单调不回退**（新变量 `modpackImportLastPct`，导入开始/关闭归零）：下载阶段按**字节数**加权（有 size 时，否则回退按个数）占 0-85%；下载收尾后交给阶段值（85 提取 / 90 创建配置 / 91-93 补装原版 / 95 安装加载器 / 100 完成）；MultiMC 这种先解压(0-90)再下载的流程在 (lastPct, 99] 内继续推进，任何情况下进度条不倒退
- `launcher_core/modpack_importer.py` — Modrinth/MultiMC 流程**预注册全部文件**（`name + size + status=queued`，size 取 `primarySize`），字节分母从第一份报告起就稳定；CurseForge 从 API `fileLength` 取 size（全部文件开始后同样进入字节加权）；`_tracked_progress_cb` 用 Content-Length 兜底回填 size；状态新增 `queued`（JS 只渲染 downloading/error/done，列表内容不变）
- 失败/出错文件按"已结算"计入字节分子 → 最后一个文件重试失败也不再把进度钉死在 98%

**验证：**
- 离线套件 6/6：新增断言（终态 states 全部带 size、无 queued 残留、非 CF 流程首份 states 即预注册全量）
- `node --check`（提取全部 `<script>`）+ `py_compile` 通过

### 修复：下载重试时进度回落（"下载到某个进度会重置"）
**根因**：`_tracked_progress_cb` 每次用当前 attempt 的 `done/size` **直接覆盖** `fs.progress`——重试第 2 次从 0 字节重新计数，文件进度瞬间从 90% 跳回个位数。模态文件列表的文件条、侧栏文件行的 `%`、侧栏整体条 `(fd+frac)/ft`（无单调保护）都读这个值，于是肉眼可见"进度重置"。

**定位方法**：离线重放 4 条真实报告流（55 个报告）驱动 JS 进度函数 → 模态总条/副标题计数/侧栏公式**全部单调无 dip**（总条有 clamp），唯一能产生回落的路径就是重试覆盖 → 构造 flaky 下载复现，红→绿 TDD。

**修复：**
- `modpack_importer.py` — `fs["progress"] = max(旧值, 新值)`：重试期间显示停在已到达位置，追上后继续前进（模态总条 clamp、字节加权免疫不变）
- `ui/index.html` — 侧栏整体条把 `error` 文件按"已结算"计 1（与模态字节语义一致；不计入 fd 的 error 不再让条回退，最后一个文件失败时侧栏也能走满）

**验证**：套件 7/7（新增 `retry-progress-monotonic`：attempt-1 90% 失败 → attempt-2 从 0 重下，断言该文件 downloading 状态序列不降）；`node --check`；重放无 dip

### 修复：文件列表底部"还有 N 个文件"越下载越多
**根因**：`N = showFiles.length - 15`，而 showFiles = 已开始的文件（downloading+error+done，不含 queued）——文件一旦开始就永远留在 showFiles 里，所以 N 随下载推进从 1 涨到 total-15，方向与"剩余"语义完全相反。

**修复**：`N = trackedTotal - (done+error)`，即**剩余未完成数**（queued+未开始+下载中），随完成递减、归 0 后整行隐藏；重试中（status 仍 downloading）不计入 settled，不会假降。

**验证**：重放脚本新增 30 文件合成场景 —— 旧代码 `remSeq=[0,...,1,2,...,15]` 增长（红）→ 新代码 `[30,30,29,...,1,0]` 递减（绿）；4 条真实流 remOK=true；`node --check` + 套件 7/7

### 修复：模组启用/禁用反馈慢、模组页点击卡顿、版本页白屏（2026-09-25 修复）

**根因**：
1. 启用/禁用把文件改名（`.jar` ↔ `.jar.disabled`），modcache 键含完整文件名 → 键变化 → 缓存全失 → 重新解包 jar 元数据 + 请求 Modrinth 图标（日志：往返 3.7s、`createoreexcavation` 等坏 mod_id 404 后走 search 兜底）
2. JS 点击后等 Python 全量返回才刷新，3.5MB JSON 触发整表重渲染（肉眼可见"卡一下"）；期间重复点击用旧文件名调用 → 日志连报 `模组不存在: ....jar.disabled`
3. `enableMod/disableMod/deleteMod/deleteWorld/deleteResourcepack` 在 GUI 线程同步执行文件操作；`loadMods` 快速连发时并发扫描同一目录
4. 版本模组/版本世界/版本资源包页切换时不显示骨架屏，白屏直到数据返回

**修复**：
- `main.py`：新增 `ModLoadScheduler`（同一时间只跑一次扫描，最新请求链式补跑，杜绝并发扫描/结果串版本）；`_mod_cache_key` 把 `.disabled` 从键中剥掉——改名不再破坏缓存，启用/禁用命中缓存、零网络；`_cached_mod_entry` 读缓存时按当前文件名刷新 `enabled`（缓存里存的是构建时旧值）；`enableMod`/`disableMod`/`deleteMod`/`deleteWorld`/`deleteResourcepack` 全部改为后台线程执行
- `ui/index.html`：`toggleMod` 乐观更新——本地立刻翻转 `enabled`/`filename`、就地修补该行（复选框、禁用/启用按钮、`data-filename`），再调 Python；`applyLocalToggle` 纯函数双向改名，连点时发给后端的文件名永远正确；`deleteModConfirm` 乐观移除行；`renderModList` 保留滚动位置 + 30 个一批分帧渲染（大列表不再冻结）+ 渲染代次防旧批次续写；`navigateTo` 对版本模组/世界/资源包页先出骨架屏；按钮 HTML 抽成 `modActionsHtml` 供渲染与就地修补共用

**验证**：红→绿 TDD —— Python 先 2 FAILED（`_mod_cache_key` 改名稳定性、`ModLoadScheduler` 合并/链式）再实现；node `applyLocalToggle` 先 RED（marker not found）后绿；套件 9/9 ALL PASS；`py_compile`；提取 `<script>` `node --check`；进度重放 5 场景无 dip、remOK=true

### 新增：收起按钮（窗口 → 细条）（2026-09-25 新增）**【已废弃：2026-09-25 当日被"弹窗原位缩小"方案替代，细条代码已全部移除，见文末】**

**需求**：版本页工具栏"导入整合包"左侧、导入弹窗底栏"导入中..."左侧各放一个"收起"按钮；点击把主窗口收成细条（当前选择 + 启动游戏），后台任务（导入/下载）继续。

**实现**：
- `ui/index.html`：`body.app-collapsed` 隐藏背景层与 `.app-container`、显示 `.window-strip`（展开按钮 ⤢ / 当前选择 label+版本名 / 启动游戏按钮，固定铺满视口）；`collapseAppWindow()`/`expandAppWindow()` 切换类并调 Python 槽；`syncStripLaunch()` 把主启动按钮的 class/innerHTML/disabled/onclick 镜像到细条副本，在 `updateLaunchButton` 末尾与收起时调用；`selectVersion` 同步细条版本名；工具栏与弹窗底栏各插入一个"收起"按钮（minimize-2 图标，沿用 `settings-file-btn` 样式）
- `main.py`：`LauncherBridge.collapseWindow/expandWindow` 槽 → `MainWindow.collapse_to_strip/restore_from_strip`（首次收起保存 geometry，最小尺寸 1200×700 ↔ 440×78，展开时 `setGeometry` 恢复原位）

**验证**：`py_compile`；提取 `<script>` `node --check`；`test_toggle_local.js`（applyLocalToggle）PASS；git diff 逐块复核——期间曾误删导入按钮 SVG 第二段圆弧（`A 2 2 0 0 0 18 21`），已还原并与 `ui/icon-modpack-import.svg` 一致

**注意（测试资产丢失）**：`%TEMP%\opencode` 下的历史测试资产（`test_import_flows.py` 9 用例、`replay_progress.js`、`dump_reports.py`、`replay_reports.json`）被系统清理删除，回收站无副本。

### 重建：离线测试套件（2026-09-25 恢复）

- `test_import_flows.py` 已按源码侦察报告（`import_modpack` 6 参回调/各格式解析/网络接缝 + `versions.py` 过滤规则）完整重建：4 条导入流程（Modrinth/CurseForge/MultiMC/client-overrides）全离线跑通——原版父版本预置走 fast-path、`download_session`/CF 文件 API 假会话、`install_mod_loader` 捕获为 `(loader, 版本名, loader_ver)`；断言含预注册 queued+size、85/90/100 阶段值、overrides 提取、retry 进度不回退（seq 非降）、版本过滤/删除不连带/cfg 认领显形，外加本会话新增的 `_mod_cache_key`、`ModLoadScheduler` 两用例
- **结果：9/9 ALL PASS**（一次性通过——用例基于完整源码侦察重建，非新特性 TDD）
- `test_toggle_local.js`（applyLocalToggle）凭本会话内容原样重建并 PASS
- 未重建：`replay_progress.js` / `dump_reports.py` / `replay_reports.json`（依赖真实整合包归档生成的报告流；JS 进度单调性断言已部分由套件的 retry/states 断言覆盖，需要时可再重建）

### 收起重定义：弹窗原位缩小 + 转圈修复（2026-09-25，替代"窗口细条"）

**需求**（用户澄清）：收起 = 把导入整合包弹窗变成内置下载器那样的小面板（"下载模组 N/M" + 转圈文件列表），**原位缩小**；顶栏"收起"与窗口细条方案移除。另修：下载模组的转圈圆圈每次进度更新角度重置。

**实现**：
- **移除细条**：`index.html` 删 `.window-strip`/`body.app-collapsed` CSS、顶栏收起按钮、`#windowStrip`、`selectVersion`/`updateLaunchButton` 挂接、`collapseAppWindow`/`expandAppWindow`/`syncStripLaunch`；`main.py` 删 `collapseWindow`/`expandWindow` 槽与 `collapse_to_strip`/`restore_from_strip`/`_strip_geometry`
- **弹窗原位缩小**：`modal-content` 内包 `importFullView`（原 header/body/footer），新增 `importMiniView`——`download-progress-header`（"下载模组" + `N/M · pct%`）+ 细进度条 + `download-file-list` 转圈列表 + 底部阶段消息/展开按钮；`collapseImportModal` 受 `modpackImporting` 门控（未开始导入点收起 → toast"导入开始后才能收起"），加 `.import-collapsed` 收窄至 420px；`onModpackImportComplete`/`closeModpackImportModal` 自动 `expandImportModal` 复位
- **进度双写**：`updateModpackImportProgress` 尾部同步 mini 的 count/fill/msg/list（保滚动、上限 15 条），完整视图逻辑不动
- **转圈修复**：新增共享 `dlFileItemHtml(f)`——downloading 图标内联 `animation-delay:-(Date.now()%800/1000)s` 把旋转相位锚定墙钟，innerHTML 整体重建不再重启动画；内置下载面板（`updateLaunchButton` installing 分支）与 mini 列表共用，done ✓/error ✗ 行为不变

**验证**：红→绿 TDD —— `test_collapse_spin.js` 先 RED（`dlFileItemHtml` not found）；绿：delay ∈ [0,0.8)、收起门控/幂等切换、mini 进度 43→86→100% 无回退、mini 列表无"还有"行；`test_toggle_local.js` PASS；套件 9/9 ALL PASS；`py_compile`；提取 `<script>` `node --check`；grep 确认细条引用 0 残留

### 下载→版本页 4 项需求（2026-09-26）

**需求**：①进入"下载→版本"卡一下；②模组/整合包/选择器三个版本下拉统一排序（正式版 → 愚人节 → 其他，选中置顶，组内保持降序）；③类型筛选下拉默认"正式版"；④头部 全部/正式版/快照版 筛选标签仅在 下载页+版本子tab 显示（搜索框保留）。

**实现**（全部在 `ui/index.html`）：
- **防卡顿**：`renderDownloadGrid` 改分片渲染——顶部 `dlRenderGen++` 记代次，同步渲染首批 40 张，余下通过 `requestAnimationFrame(appendBatch)` 分批追加；每批先判 `gen !== dlRenderGen` 直接放弃（新渲染/空结果清场后旧批次不再续写）；卡片 onclick 用 IIFE 闭包绑定 id；空结果先 `innerHTML=''` 再写提示文案（同样先记代次）
- **统一排序**：新增 `versionRank(v)`（release→0；`releaseTime` 含 `-04-01`→1（愚人节，日期两种格式均容）；其他→2）；`populateGameVersionDropdowns` 内按 base 版本聚合 `rankByVer`（同 base 取贡献版本的最小秩，未见的 commonVersions → 0），在原 `sort().reverse()` 降序基础上做稳定秩排序，`selectedVersion` 的 base 置顶（正则同 base 提取，无数字前缀时用全 id）；`commonVersions` 列表与降序行为原样保留
- **默认正式版**：`selectIds` 移除 `dlVersionFilter`（类型下拉完全不再被 populate 触碰，选中值天然保全）；HTML `<option value="release" selected>`；`onchange` 从 `filterDownloadVersions()` 改为 `setFilter(this.value)`（标签/下拉/网格单一来源同步）；`currentFilter` 仍初始 `'all'`（否则已安装页的快照/自定义版本会被藏掉且标签不可见），头部标签 `active` 从"全部"移到"正式版"以反映下载页默认筛选
- **标签显隐**：新增 `var currentDlTab = 'versions'` + `syncHeaderTags()`（`currentPage==='download' && currentDlTab==='versions'` 时显示 `.filter-btn`，否则隐藏，不碰搜索框），在 `navigateTo` 末尾、`switchDownloadTab`（同时写 `currentDlTab = tab`）、DOMContentLoaded 三处调用
- **选中联动**：`selectVersion` 末尾补 `populateGameVersionDropdowns()`（选中版本置顶随选择更新）；modGameVersion/modpackGameVersion/pickerGameVersion 重建时捕获并恢复选中值（`applyValue`）

**验证**：红→绿 TDD —— 新建仓库内 `tests/test_version_filters.js`（61 断言：静态检查、versionRank 分级、排序单调/位置/末尾 `25w14craftmine,b1.7.3,25w18a`、选中置顶、selectVersion 重填充、dlVersionFilter 保全、分片渲染/代次守卫/空结果清场/类型筛选、标签显隐 5 场景、setFilter 回归）；RED 25/28 FAIL → 实现后 **61/0 ALL PASS**；期间修复 3 处仅测试自身的桩错误（`env.state` 挂接、gen 守卫用错 env 的 grid、`'none;'.slice` 削弱断言）；`py_compile`；提取 `<script>` `node --check`；`git diff` 逐块复核（曾误删 `commonVersions` 块，已还原）

**注意（测试资产丢失）**：`%TEMP%\opencode` 历史套件（`test_import_flows.py` 9 用例、`test_toggle_local.js`、`test_collapse_spin.js` 等）已被系统第三次清理删除；本次新测试落在仓库 `tests/` 内不再受影响；旧套件未重建（与本任务无关，需要时按 DEVLOG 重建记录恢复）

### 修复：搜索/热门结果串页签（2026-09-27）

**现象**（用户提供日志）：请求在途时切换下载子页签，先前页签永远显示"正在从Modrinth加载模组列表..."，内容或写错容器（例：选模组后未出结果就切整合包 → 模组不显示）。

**根因**：`displaySearchResults`（`ui/index.html`）按**结果到达时**的 `.download-tab.active` 决定写入哪个容器；Python 两个结果载荷（`loadTrendingContent` / `searchContentFiltered` 的 `result_json`）不含 `content_type`/页签，JS 无从得知结果属于哪个请求——请求时的页签信息在传输中丢失。

**实现**：
- `main.py`：两处 `result_json` 增加 `"tab": content_type`（trending L687 附近、search L1011 附近）
- `ui/index.html` `displaySearchResults`：优先 `results.tab` 路由到 `tabType + 'Results'`（无论该页签当前是否可见，隐藏页签照常写入，切回即见内容）；无 `tab` 字段时回退旧的活动页签行为（向后兼容）

**验证**：红→绿 TDD —— 新建 `tests/test_tab_result_routing.js`（11 断言：结果写回请求页签且不污染当前页签、空结果同路由、无 tab 回退兼容、两侧静态检查 `results.tab` 与 2 处 `"tab": content_type`）+ 共享抽取器 `tests/extract_func.js`；RED 2/9 FAIL（精确复现占位符不消失/串容器）→ 实现后 **11/0 ALL PASS**；回归 `test_version_filters.js` 61/0；`py_compile`；提取 `<script>` `node --check`；`git diff` 复核（改动仅 3 处：2 个载荷字段 + 路由逻辑）

### 新增：版本管理页"文件目录"（2026-09-27）

**需求**（用户提出 + 两轮确认）：版本管理页新增"文件目录"区块——自动识别该版本游戏目录下的所有子文件夹，识别得出的（mods、saves 等）显示中文名（模组文件夹、世界文件夹…），识别不出的（模组特殊文件夹）显示原名，点击用资源管理器打开；扫描基准=**跟随版本隔离的游戏目录**（隔离开→`versions/<id>/`，关→`.minecraft` 根）。

**实现**：
- `launcher_core/versions.py`：模块级 `FOLDER_LABELS` 映射（键序即排序序：mods→模组、saves→世界、config→配置、resourcepacks→资源包、shaderpacks→光影、screenshots→截图、crash-reports→崩溃报告、logs→日志）；`get_game_dir(version_id)`（隔离判定复用 `is_version_isolated`，未知版本回退根目录）；`list_version_folders`（列子目录、映射命名、识别项按映射序在前 + 未识别字母序在后，附 `path`）；`resolve_folder`（打开前校验：空串=根、拒绝绝对路径、`resolve()` 后必须 `is_relative_to` 游戏目录、必须存在且是目录，否则 None——防路径穿越）
- `main.py`：`versionFoldersLoaded` 信号 + `getVersionFolders(version_id)` 槽（emit `ensure_ascii=False` JSON）+ `openVersionFolder(version_id, subfolder)` 槽（`QDesktopServices.openUrl(QUrl.fromLocalFile(...))`，失败走 `errorOccurred` toast）；`_on_version_folders` 回调 `renderVersionFolders(...)`，在连接区注册
- `ui/index.html`：版本管理页隔离开关下新增 `.version-folders-section`（CSS 一并新增）——头部"文件目录"+ 实际路径小字（`versionFoldersPath`）+"打开版本文件夹"按钮（`openVersionFolder('')`），列表 `versionFoldersList`；JS `renderVersionFolders`（按载荷顺序建行，`recognized` 类区分，闭包点击 `openVersionFolder(f.name)`，空列表提示"此文件夹内没有子文件夹"）、`loadVersionFolders`、`openVersionFolder`；`openVersionManager` 与 `toggleVersionIsolation`（隔离切换后目录会变）均刷新列表

**验证**：红→绿 TDD —— `tests/test_version_folders.py` **RED 12/12 FAIL**（AttributeError 缺方法；修掉一处测试桩 `mkdir` 缺 `exist_ok` 的自伤）→ 实现后 **12/12 PASS**；`tests/test_version_folders_ui.js` **RED 0/9**（缺函数/容器/槽/接线）→ **22/22 PASS**（渲染识别与未识别行、顺序保持、点击传参、空列表、刷新传 selectedVersion、两侧静态接线）；回归 `test_version_filters.js` 61/0 + `test_tab_result_routing.js` 11/0；`py_compile`；提取 `<script>` `node --check`；`git diff` 复核（3 文件 235 行全为新增）

### 修复：加载器兼容矩阵按 HMCL 规则重写（2026-09-27）

**需求**（用户确认）：模组加载器的兼容关系不正确，按 HMCL 的规则实现（截图取自 HMCL 的模组加载器选择界面）。

**规则提取**：拉取 HMCL 源码，`HMCL/src/main/java/org/jackhuang/hmcl/ui/InstallerItem.java` `InstallerItemGroup`（L172-178）为权威矩阵——`mutualIncompatible(forge, fabric, quilt, neoforge, ...)` 四者两两互斥；`addIncompatibles(optiFine, fabric, quilt, neoforge, ...)` OptiFine 与三者互斥但与 Forge 兼容；Fabric API/Quilt API 各自与对方生态加载器互斥、与本族加载器兼容（本仓库无 fabricapi 卡片，暂不适用）；已安装状态优先于不兼容状态。

**BUG**：旧 `LOADER_INCOMPATIBLE` 只记了一半配对（`forge:['neoforge']`、`fabric:['quilt']`…），且 optifine 单向声明破坏对称——装了 Forge 后 Fabric/Quilt 仍可点安装，装了 Fabric 后 Forge/NeoForge/OptiFine 仍可装，装了 OptiFine 后 Fabric/Quilt/NeoForge 可装；另外 `markIncompatibleLoaders` 用朴素首字母大写生成冲突名（"Neoforge"/"Optifine" 错拼）。

**实现**（`ui/index.html`）：
- `LOADER_INCOMPATIBLE` 按 HMCL 重写为对称矩阵：forge↔{fabric,quilt,neoforge}；fabric/quilt/neoforge 两两互斥 + 各自↔optifine；optifine↔{fabric,quilt,neoforge}（与 forge 兼容），注释标注来源
- `markIncompatibleLoaders` 冲突名改用 `displayNames` 映射（NeoForge/OptiFine 正确大小写），与安装行 `names` 映射一致
- 安装弹窗按钮与模组加载器页安装行共用同一矩阵，两处行为一致

**验证**：红→绿 TDD —— 新建 `tests/test_loader_compatibility.js`（82 断言：矩阵逐项对照 HMCL、全对称性、弹窗三场景行为、加载器页安装行 HTML、静态接线）；**RED 61/21**（失败全为缺配对/对称破坏/漏标灰）→ 修矩阵 + 冲突名映射 → **82/0 ALL PASS**；回归 `test_tab_result_routing` 11/0、`test_version_filters` 61/0、`test_version_folders_ui` 22/0、pytest 12/12；`py_compile`；提取 `<script>` `node --check`；`git diff` 复核（仅 index.html 两处 + 新测试文件）

### 功能：多账号管理（2026-09-27）

**需求**（用户确认）：多账号管理——离线与 Microsoft 账号并存，支持列表/切换/删除，按账号持久化令牌；单点登录的 `auth.json` 升级为多账号存储并自动迁移。

**实现**：
- `launcher_core/accounts.py`（新增）：`AccountStore` 持久化到 `~/.mc-launcher/accounts.json`（原子写 tmp+replace、utf-8、`ensure_ascii=False`）；`list()` 摘要 `{id,type,name,uuid,lastUsed,isCurrent}` 按 lastUsed 降序且**绝不含 data/令牌**；`add` 校验 type∈{offline,microsoft} 否则 ValueError（校验先于任何落盘）、离线按 name/微软按 uuid 去重；`switch/remove/update_data/deselect`；`migrate_legacy` 读旧 auth.json 导入首个账号并保留原文件（损坏 JSON 返回 False 不崩）；`_load` 剔除非 dict/缺键/非数值 lastUsed 条目并 WARNING；`_save` 失败记日志后**上抛**（不吞成假成功）
- `launcher_core/auth.py`：`AuthManager` 改造为 `store` 注入（构造即 migrate）；`complete_login/offline_login` → `store.add`；`get_login_data`→`store.current()`；**登出=取消选中（deselect）不删账号**（删除是账户页独立操作）；`refresh_login` 未登录 → RuntimeError、mll 异常记日志后 re-raise；`offline_login("")` → ValueError；auth.json 写入逻辑全删
- `main.py`：`accountsLoaded` 信号 + `getAccounts/switchAccount/removeAccount` 槽（payload 构建与 emit 全在 try 内，异常 → errorOccurred）；`checkLoginStatus` 抽出 `_emit_login_status(silent=False)` 供复用，无账号时 emit `{loggedOut:true}`；**切号/删除走 `silent=True`** 防止触发欢迎 toast 与跳页；`logout` 补 emit 刷新列表 isCurrent
- `ui/index.html`：账户页重构为卡片列表（首字母头像、离线/Microsoft 徽章、当前 ✓ 白描边、整卡点击切换、悬停 🗑 + confirm 二次确认、空态、底部复用离线表单+微软按钮）；`updateLoginStatus` 增 `loggedOut` 分支（登录态正确复位，修"欢迎, 未登录!"误报）与 `silent` 分支；登录成功/离线登录后 `getAccounts()` 刷新；`accountsLoaded → _on_accounts_loaded → renderAccountList` 按 versionsLoaded 同款接线；`escapeAttr` 属性上下文转义（引号注入防护，账号/插件页共用）

**验证**：红→绿 TDD —— `tests/test_accounts.py` **37 用例**（RED 模块缺失 → GREEN；含类型校验/损坏文件/迁移/登出回退/refresh 契约/落盘失败上抛等审查补测）；`tests/test_account_ui.js` **122 断言**（RED 38 FAIL → 修 silent/缓存/冗余拉取后 GREEN → 审查修复轮 16 FAIL → 118 → escapeAttr 3 FAIL → 122）；全套回归 pytest **97**、`test_version_filters` 61/0、`test_tab_result_routing` 11/0、`test_version_folders_ui` 22/0、`test_loader_compatibility` 82/0、`test_plugins_ui` 191/0；`py_compile`；提取 `<script>` `node --check`；启动冒烟 15s 存活；`git diff` 复核 index.html 删除行仅 12 行且全为计划内（accountPage 旧结构+标题映射）

### 功能：插件系统与插件页（2026-09-27）

**需求**（用户确认）：真实扩展系统——Python 插件包（manifest + plugin.py + 宿主 API），本地 `plugins/` 目录扫描，侧栏新增第 8 个"插件"页签，列表→详情两级页面（基本信息/设置表单/自定义内容区/操作按钮）。

**实现**：
- `launcher_core/plugins.py`（新增）：`PluginManager` 扫描 `plugins/*/manifest.json`（坏 manifest/恶意 id `^[A-Za-z0-9._-]+$` 白名单/重复 id/穿越 junction 一律拒收+WARNING 不崩）；摘要 `{id,name,version,author,icon,description,status,errorMsg,hasSettings,hasContent,dir}` 按名排序；`enabled.json` 启停持久化（缺失=全启用、新插件默认启用）；`load_all` 单插件异常隔离成 error 状态；`detail` 返回 settings（schema+value，非法元素与坏 key 过滤）与 contentHtml（仅启用且加载成功）；`set_enabled(True)` 立即加载；`save_config` 类型校验（text/toggle/number、拒 bool 与不可序列化值）返回 `{success,error}`；`uninstall` 三重防线（格式白名单+命中已扫描+resolve 父目录）先释放实例再 rmtree；`folder_of` 同防；`PluginContext`（register_content/get_config/set_config/专属 logger）；模块经 `importlib` 独立加载（exec 失败/禁用/卸载不留 sys.modules 残留）
- `plugins/hello-sample/`：manifest（3 个设置项）+ plugin.py 示范（`html.escape` 转义、docstring）
- `main.py`：`pluginsLoaded/pluginDetailLoaded` 信号 + 7 槽（getPlugins/getPluginDetail/setPluginEnabled/savePluginConfig/reloadPlugins/openPluginFolder/uninstallPlugin），全槽 try 兜底 → errorOccurred（含 savePluginConfig 后半段与 openPluginFolder，防 Qt 槽异常逃逸致进程 abort）；启动 `QTimer.singleShot(0)` 延后 `load_all()` 且 try 包裹；`_on_plugins_loaded/_on_plugin_detail_loaded` → runJavaScript 字面量注入
- `ui/index.html`：侧栏第 8 项（puzzle SVG、data-page="plugins"、tooltip）+ 标题映射；`#pluginsPage` 双视图（列表/详情）；列表卡片（图标/名称/`v1.0.0 · 作者`/启用·禁用·错误三色徽章/简介两行截断/errorMsg title 悬浮/空态）；详情（返回按钮、基本信息含目录、启停/打开文件夹/重新加载/卸载 confirm、三类型设置表单+保存、`#pluginContent` 注入或占位）；`currentDetailId` 判定（卸载成功回列表、列表不含当前 id 自动回退、详情空 id 提示"插件不存在"、navigateTo 重置子视图）；同 id 重渲染保留未保存表单输入；`escapeAttr` 全属性上下文转义

**验证**：红→绿 TDD —— `tests/test_plugin_manager.py` **48 用例**（RED 模块缺失 → 25 → 审查修复 8 项 33 → 质量修复 13 项 46 → S1/dir 48；junction 用例 `mklink /J` 真实生效、B1 源码级 reload 钉死、B6 escape）；`tests/test_plugins_ui.js` **191 断言**（RED Task6 静态 31 → Task7 55 FAIL → harness 修桩 144 → 合并修复轮 29 FAIL → 191）；全套回归 pytest 97、JS 6 套 61/11/22/82/122/191 全 0 FAIL；`py_compile`；提取 `<script>` `node --check`；启动冒烟 15s 存活；两轮规格+质量审查（含 S1 引号注入、S2 槽异常逃逸、卸载回列表等必修项）闭环

### 打包：Windows 单文件版 + b1.1 Release（2026-10-01）

**需求**：构建可直接双击运行的 exe（免安装 Python 与依赖），作为 b1.1 release 上传 GitHub。

**实现**：
- `launcher_core/paths.py`（新增）：`app_base_dir()` —— frozen（PyInstaller）时返回 **exe 所在目录**（持久、用户可见），开发态返回仓库根；解决打包后 `Path(__file__)` 落在一次性临时解包目录（`_MEIPASS`）导致 logs/plugins 每次启动被清空的问题
- `main.py`：`LOG_DIR = app_base_dir()/"logs"`，exe 目录不可写（如 Program Files）时回退 `~/.mc-launcher/logs`；`StreamHandler` 加 `sys.stdout is not None` 守卫（`--windowed` 下 stdout 为 None）
- `launcher_core/plugins.py`：默认插件目录改走 `app_base_dir()/"plugins"`（frozen → exe 同目录，开发态仓库根不变；`scan` 对缺失目录已有 `is_dir` 守卫）
- `.gitignore` 补 `build/`、`dist/`、`*.spec`；打包命令 `pyinstaller --onefile --windowed --name DevLauncher --add-data "ui;ui" main.py`（WebEngine 由 PyInstaller 内置 hook 收集）；发布 zip = DevLauncher.exe + plugins/hello-sample + CHANGELOG

**验证**：红→绿 TDD —— `tests/test_frozen_paths.py` **6 用例**（RED 4 failed → 实现 paths.py + 接入 → 5 绿 → stdout 守卫 RED 1 failed → GREEN 6）；全套回归 pytest **105**、JS 6 套 61/11/22/82/128/196 全 0 FAIL、`py_compile`、提取 `<script>` `node --check`；**exe 冒烟 35s 存活**（日志落 exe 旁 `logs/launcher.log`、背景图加载、拉取 917 个版本、QtWebEngineProcess 正常）；exe 197.8MB

### 构建完善：自定义图标 + 版本资源 + 可复现构建脚本（2026-10-01）

**需求**（用户提供 SmartScreen 截图）：exe 仍是 PyInstaller 默认图标——替换为软件自身图标；同时完善构建流程。附带结论：SmartScreen"已保护你的电脑"由**未签名 + 网络下载 MOTW** 导致，与图标无关，换图标不消除；未购买代码签名证书前只能用户侧放行（已在 CHANGELOG 与 release 说明指引"更多信息→仍要运行"或右键属性解除锁定）。

**实现**：
- `tools/make_icon.py`（新增）：PyQt6 `QSvgRenderer` 把 `ui/icon.svg` 渲染为 16/24/32/48/64/128/256 七档 PNG，纯 Python 手工组装 PNG 直嵌 ICO 容器 → `ui/icon.ico`（21455 字节，零新增依赖）
- `version_info.txt`（新增）：VSVersionInfo，FileVersion/ProductVersion=1.1.0.0，ProductName/OriginalFilename=DevLauncher（ASCII 规避编码坑）
- `build_exe.ps1`（新增）：一键流水线——图标缺失自动从 SVG 生成 → `pyinstaller --clean --onefile --windowed --icon --version-file` → 组装发布 zip（exe+hello-sample+CHANGELOG.txt）→ 冒烟（30s 存活 + 日志新写入，杀软扫描窗口期早退自动重试 3 次）；去掉冗余的 `--add-data launcher_core`（PYZ 已含，避免源码影子）
- `CHANGELOG.txt`（入库）：zip 内更新日志单一事实源，含【首次运行提示】SmartScreen 放行指引

**验证**：红→绿 TDD —— `tests/test_build_assets.py` **4 用例**（RED 4 failed → 三件套落地 → GREEN 4：ICO 头/7 尺寸/32 位/PNG 签名/数据越界、版本资源字段、构建脚本 6 项接线、make_icon 可编译）；回归 pytest **109**、JS 128/196 全 0 FAIL；端到端跑通 `build_exe.ps1`（BUILD OK）；**图标双重实证**：`VersionInfo` 读出 1.1.0.0/DevLauncher + `ExtractAssociatedIcon` 与 `ui/icon.ico` 32px 条目 8×8 网格采样 **pixel_match=121/121**；稳定性：连跑 exe 3×45s 全存活（构建后即测的两次早退 exit=0 定位为杀软扫描窗口瞬态，Defender 检测记录无 DevLauncher 相关项）；诊断副产物 `dist/DevLauncherDbg.exe`（--console 版，stderr 空）

### 内存优化：QtWebEngine GPU flags（2026-10-01）

**问题**：任务管理器合计内存 160MB+（HMCL 对照 98MB）。按进程分解（PowerShell WorkingSet/PrivateMemorySize64 + Win32_Process 命令行识别角色）：主进程（Python+QtWebEngine 浏览器侧）~205MB、渲染进程 ~97MB、父 bootloader ~11MB，合计提交内存 **275MB**。

**根因**：QtWebEngine 默认 in-process GPU——GPU/合成器内存挤在主进程；渲染进程另有 ~31MB 私有。**顺带重大发现：C 盘可用空间一度为 0GB**，%TEMP% 积 29 个强杀残留 `_MEI*`（4.8GB）——这才是此前 exe「间歇性 25~40s exit=0 早退/解包 decompression -1」的真正根因（磁盘满→PyInstaller 解包失败），杀软瞬态只是表象；清理后 5/5 启动成功。

**方案**：`launcher_core/webengine_flags.py` 提供 `WEBENGINE_CHROMIUM_FLAGS = --disable-gpu --in-process-gpu --disable-gpu-compositing` 与 `merge_chromium_flags()`（用户自定义 flags 合并、幂等）；`main.py` 在 QApplication 构造前注入 `QTWEBENGINE_CHROMIUM_FLAGS`。

**实验矩阵**（`dist/mem_probe.ps1`，每变体 40s 起 3 次采样，TOTAL_PRIV 已提交内存）：V0 基线 275 → V1 仅 `--single-process` 237（-38，但 QtWebEngine 非官方支持模式，登录 WebView 弹窗风险）→ **V2 三 GPU flags 207.5（-67.5，采用）** → V4 single+GPU 196.7（仅比 V2 多 11，不值）→ V3/V5/V7 `--disable-features` 批量与 `--js-flags` 上限均无叠加增益（206.9~261）。

**验证**：红→绿 TDD —— `tests/test_webengine_flags.py` **5 用例**（RED ModuleNotFoundError → 实现 + main.py 接线 → GREEN）；全套回归 pytest **114** + JS 6 套 128/82/196/11/61/22=**500** 全 0 FAIL + `py_compile`；重打包 BUILD OK（冒烟含在内）；**烧入版终测（无环境变量）TOTAL_PRIV 210.6MB（基线 275，-64MB/-23%）**，渲染进程命令行实测含 `--disable-gpu-compositing`，页面正常渲染（日志 versionsLoaded 新写入）。

### 下载页细化筛选 + 版本卡加载器角标 + 客户端子页签（2026-10-03）

**需求**（用户 4 问确认）：① 模组页加 Modrinth 风格左侧筛选面板（类别带图标/加载器/安装环境/游戏版本，折叠「查看剩余 N 项」，只改模组子页签）；② 版本卡片右下角加载器 logo（原版显示 3D 草方块），图标现在从网上下载入库、随包离线；③ 下载页新增「客户端」子页签——14 客户端 + 6 PVP 模组包目录，自动解析最新文件下载到 mods 目录（隔离版本走隔离路径），无 API 条目打开网页；④ 内存优化先单独提交（`67e2a3c`）。

**实现**：
- `launcher_core/api_modrinth.py`：`build_facets()` 纯函数——versions/loaders/categories 各成 OR 组、组间 AND；**环境组走 `client_side`/`server_side`（required+optional）**——实测 `categories:client` 恒 0、`/v2/tag/category` 无 Environment 项，是 API 真实语义而非设计假设；`search()` 扩展 versions/loaders/categories/environments 参数
- `main.py`：新槽 `searchMods(query, versions, loaders, categories, environments, source)` 六参逗号分隔多选（Modrinth 走新 facets；CurseForge 源降级仅 game_version）；旧 `searchContentFiltered` 原样保留服务整合包/数据包/世界，签名不变
- `ui/index.html`：`#dlMods` 改两列 `.mod-filter-layout`——左 `.mod-filter-panel` 四段 chips（`MF_CATEGORIES` 19 类别带 lucide 图标、`MF_LOADERS` 4 加载器带 logo、`MF_ENVS`、游戏版本由 populate 动态灌入）+「清除筛选」，折叠「▼ 查看剩余 N 项」/「▲ 收起」；移除旧 `modGameVersion`/`modLoaderFilter` 下拉；`toggleModFilter` 有筛选时允许空关键词自动重搜（空关键词+空筛选才提示）；`createVersionCard` 追加 `<img class="version-loader-icon">`（版本 ID 匹配加载器 → `static/icons/loaders/<name>.png`，原版 → `grass_block.png`，onerror 隐藏兜底）
- `ui/static/icons/`（入库随包）：loaders 5 png（fabricmc 官方 logo、MinecraftForge/NeoForged/QuiltMC 头像、OptiFine favicon 转 png）、`grass_block.png`（minecraft.wiki 300×300，程序化验证 ~40% 绿像素）、cat 19 lucide SVG（jsdelivr+代理抓取）、env 2 SVG
- 客户端目录：`launcher_core/clients_catalog.py`——20 条静态目录（14 client + 6 pack，strategy 五枚举 github_latest_jar/modrinth_latest_jar/modrinth_modpack/curseforge_search_jar/open_page），`github_latest_url()` 幂等归一（owner/repo、api 前缀、完整 URL 三种写法）、`pick_github_asset()` jar 过滤排除 `-sources/-dev/-javadoc`、`pick_modrinth_file()` primary 优先、`client_dest_dir()` 隔离三分支（与现行下载规则同源）；`launcher_core/api_github.py`——`releases/latest`（天然排除 prerelease）
- `main.py`：信号 `clientsLoaded/clientDownloadFinished` + 槽 `getClients/downloadClient/openClientSite` + `_on_*` runJavaScript 字面量注入，接线两行；`downloadClient` 线程解析（GitHub→jar asset / Modrinth→最新 version jar / CurseForge→search+files / 模组包→复用 `downloadContent(slug,'modpacks')`）→ `client_dest_dir` 落盘 → `{id, ok, message}` 回执；`openClientSite` 校验 http 前缀
- `ui/index.html` 客户端页：`.download-tabs` 第 6 页签「客户端」（monitor SVG）；`#dlClients` 类型 chips（全部/客户端/PVP 模组包）+ `#clientSearch` 即输即滤 + `#clientsResults` 网格；8 函数 `loadClients/renderClientList/setClientFilter/filterClients/clientCardHtml/downloadClient/openClientSite/onClientDownloadFinished`；`switchDownloadTab` 首开 clients 走 `loadClients()` 不走 trending（`tabLoadedFlags` 补 `clients:false`）；卡片下载中「下载中…」禁用、完成「已下载」标记、`open_page` 条目显示「打开页面」
- **目录条目全部代理实测真实**：Modrinth 20 slug 200（ferritecore 404 → 换 moreculling，正确 slug 实为 ferrite-core）、`Snowiiii/MasterMind-Fabric`、`FPSMasterTeam/FPSMaster-Edge`（latest 同时有 jar+zip，正好验证挑选逻辑）、6 个 PVP 包 slug 均在 `/v2/search` PVP 榜单中

**验证**：红→绿 TDD —— `tests/test_download_refine.js` RED 0/29 → GREEN **68**（测试桩两轮修缮：函数白名单补 mf* 辅助、元素惰性物化）；`tests/test_mod_facets.py` 6→**7 用例**（环境语义修正）；`tests/test_clients_catalog.py` RED ImportError → GREEN **9**（schema 20 条/归一/挑选/落盘）；`tests/test_clients_ui.js` RED 1/29 → GREEN **52**；全套回归 pytest **130** + JS 8 套 52/68/82/128/11/196/61/22=**620** 全 0 FAIL + `py_compile` + 提取 `<script>` `node --check`；**网络冒烟**（代理）：组合筛选（1.21.11+fabric+optimization+client）**990 hits** 首位 sodium/iris/entityculling/lithium、双端 AND 46981、GitHub 挑出 `FPSMaster-1.0.2-beta.1.jar`（排除 zip）与 `MasterMind-1.0-SNAPSHOT.jar`、Modrinth sodium 最新 jar 解析成功

### 客户端目录整体替换（19 条）+ Meteor 官网 API + 卡片新排版 + 下载前选版本（2026-10-04）

**需求**：用户给新清单，客户端子页签整体替换为 **19 条 = 13 客户端 + 6 PVP 整合包**（旧 20 条全部作废），并要求：① 新增 `category`（作弊-综合/作弊-辅助/作弊-PVP/PVP-竞技/PVP-辅助，5 值；pack 空串）与 `icon`（头像 URL，空则字母兜底）字段；② Meteor 改走官网下载 API（`/api/download` + `?version=`），版本列表来自 `/archive` 页；③ 卡片按新示意图排版——左图标右名称+徽章、备注一行、按钮右下角；④ 点「下载」先弹**版本选择器**（与其他下载页一致），整合包复用带实例名输入的 modpacks 分支。

**实现**：
- `launcher_core/clients_catalog.py`：19 条全量重写（5 种 category、18 个 icon URL——github owner avatar×9 / Modrinth CDN×8 / CF logo×1，ATH 无搜到头像走 `""`）；strategy 六枚举新增 `meteor_download`（分布 github_latest_jar×5 / modrinth_latest_jar×3 / meteor_download×1 / curseforge_search_jar×1 / modrinth_modpack×5 / open_page×4）；`github_latest_url()` 扩展接受 `github.com/.../releases` 写法；新增 `parse_mc_version()`（`-MC<ver>` 后缀优先，否则年份式 ≥26.x 或 1.14~1.99.x；1.0.2/0.2.0 不算）、`format_github_release_items()`（releases 列表 → 选择器条目，**id=资产直链**，release 内按 `updated_at` 降序、跨 release 保持 API 顺序；真实案例 BleachHack 同 release 多 MC 版本 jar，取最新而非列表首位 1.17.1）；新增 `github_releases_url()`（**修冒烟发现的 404**：`latest` 切片残留尾斜杠 `.../releases/?per_page=30` 不可用，必须 `.../releases?per_page=30`）
- `launcher_core/api_meteor.py`（新）：`meteor_download_url()`/`filename_from_content_disposition()`/`parse_archive_versions()`（archive 页锚点正则去重）/`MeteorAPI._probe()`（**只读响应头不拉包体**）；`get_jar(version)` 指定版本 400 等不可用→回退裸接口最新版；`api_github.get_releases(repo)` 新增（list 排除 draft，失败 `[]`）
- `main.py`：新槽 `getClientVersions(client_id)`（先定义 `_emit` 闭包复用 `modVersions` 信号→`updateModVersions` 渲染；六 strategy 各自映射；成功前置 `最新版本`（id=""）条目、失败保底也发 `[latest]`，线程执行）+ `downloadClientVersion(client_id, version_id, custom_name)`（open_page 报错；**modrinth_modpack 委托 `downloadModpackVersion`** 不设卡片下载中态避免卡死；meteor→`meteor_api.get_jar`；github→version_id 以 http 开头直下否则 latest 流程；modrinth→`get_version`/`versions[0]`+`pick_modrinth_file`；curseforge→files 按 id 匹配否则 files[0]；落盘沿用 `client_dest_dir` 隔离三分支，回执 `clientDownloadFinished`）；`downloadClient` 改为委托 `downloadClientVersion(id,"","")` 快速最新版
- `ui/index.html`：客户端卡 CSS 重排（`.client-card-top/.client-icon(56px,relative)/.client-icon-img(object-fit:cover,inset:0)/.client-icon-fallback/.client-title-col/.client-badge.cat`）；`clientCardHtml` 新结构（icon+名称+分类/类型/平台徽章 → 备注 → 右对齐按钮；icon `<img onerror="this.remove()">` 自愈，空 icon 仅字母；open_page→`openClientSite`，else→`downloadClientWithPicker`）；`filterClients` haystack 补 `category`；新 `downloadClientWithPicker(id)`（open_page 直开页面；pack→`openVersionPicker(id,'modpacks',…,platform)`；client→`openVersionPicker(id,'clients',…)` 选中后设下载中态）；`openVersionPicker` 首分支加 `contentType==='clients'`→`getClientVersions`
- **目录端点全部代理实测**：4 仓库无任何 GitHub Release（wurst→wurstclient.net、ares→aresclient.org、payload→仓库页、meteor→官网 API）；GitHub latest×5 可用；Modrinth 8 slug（`pvp_perfect` 下划线、`macepvp+` 含 + 均直接可通，5 包主文件均 `.mrpack`）；CF `search_mods("AxolotlClient")` 1 命中 13 files（图标在 `logo.url`）；`/archive` 8 版本；18 个 icon URL 全 200

**验证**：红→绿 TDD —— `tests/test_clients_catalog.py` 重写 RED 6F/6P → GREEN；`tests/test_api_meteor.py` 新建 RED ImportError → 合计 **19 passed**（schema 19 条/13+6 组成/归一/updated_at 挑选/`parse_mc_version`/`github_releases_url` 尾斜杠回归/静态断言 get_releases 用归一 URL）；`tests/test_clients_ui.js` 重写 RED 36F/17P → GREEN **95/0**（19 卡渲染/新排版/分类搜索「作弊」3 命中/picker 双分支/open_page 安全分支/main.py 槽静态；测试桩两轮修缮：白名单补 `escapeHtml`/`escapeAttr`、createElement 模拟 textContent→innerHTML 转义）；全套回归 pytest **144** + JS 8 套 128/95/71/82/196/11/61/22=**666** 全 0 FAIL + `py_compile` + 提取 `<script>` `node --check`；**网络冒烟（代理）ALL PASS**：`get_releases`×5（BleachHack 30 releases/75 items）、Modrinth 8 slug、CF search+files、Meteor archive 8 + `get_jar` 三态（裸→`meteor-client-26.2-32.jar`、`1.21.11`→`-1.21.11-86.jar`、无效→回退最新）、18 icon 全 200

### 客户端下载升级为完整实例安装（MC+加载器+jar 进隔离实例，2026-10-04）

**需求**：用户 4 问确认 —— jar 客户端「下载」不再只落 mods，而是**自动下载 MC 版本 + 加载器 + jar，全部装进新建隔离实例**（可直接在版本页启动）；选版本弹层**带实例名输入框，默认=客户端名**；MC/加载器跟随所选条目 `game_versions[0]`/`loaders[0]`（加载器空默认 fabric；无 MC 版本 → 当前选中**须严格形如 MC id** → Mojang 最新正式版）；卡片按钮**不永久锁死**（仅临时「下载中…」，完成回「下载」可重复下，与模组卡片一致）；**始终**新建/复用同名隔离实例，不并入当前选中。方案 A：复用整合包导入器 + HMCL 导入弹窗进度（设计/计划文档见 `docs/plans/2026-10-04-client-instance-install-*.md`）

**实现**：
- `launcher_core/clients_catalog.py`：新 `strict_mc_version()`（严格 id 形状 `x.y[.z]` / `x.y-snapshot[-n]`，实例名/含杂质字符串不误判）+ `resolve_client_mc_version(game_versions, current, latest)` 回退链（快照 id 如 24w14a 跳过）
- `launcher_core/modpack_importer.py`：新 `install_client_instance(name, mc, loader, lv, report)` —— `versions/<名>/`+mods 先建（同名幂等）→ `VersionManager.enable_version_isolation` → `_ensure_vanilla_version` → `_create_version_json` → `_install_loader_for_import`，返回 `{version_name, warning}`，任一步失败向上抛
- `main.py` `downloadClientVersion` 编排改造：六 strategy 解析时同步填 `picked_meta`（github 直链回查 release 条目 game_versions、latest 解析文件名；modrinth version 字典；CF `fileInfo.gameVersions`；meteor `[version_id]`+`["fabric"]`）→ candidates+文件名解析走回退链（`minecraft_launcher_lib.utils.get_latest_version()` 离线容错 `""`）→ `get_recommended_loaders(mc)` 取 loader 版本（缺→报错）→ 实例名 = `custom_name or 客户端名` → `report` 闭包（`modpackImportProgress` + `gameStateChanged` 双驱动）→ `install_client_instance` → jar 直链下进 `versions/<名>/mods`（**88→100 单调进度**，防回跳）→ **成功/失败均双发** `modpackImportComplete`（导入弹窗永锁防护，沿 importModpack 先例）+ `clientDownloadFinished`；成功后 `getVersions`+`loadMods`；旧 `client_dest_dir` 落盘路径自本管线移除（函数保留）
- `ui/index.html`：`openVersionPicker` clients 分支**显示实例名输入框**（默认值=客户端名，占位同名）；`downloadClientWithPicker` clients 回调（`modpackImporting` 并发锁 → 临时下载中 → `openClientImportDialog(实例名)` → 透传 customName）；新 `openClientImportDialog(name)`（弹窗直接进进度态、跳确认页、锁取消钮「导入中...」、标题「安装客户端 - 名」、复位 HMCL 文件计数）；`clientCardHtml` **删「已下载」永久禁用分支**（三态：打开页面/下载中…/下载）；`onClientDownloadFinished` 不再置 `clientsDownloaded`；`closeModpackImportModal` 重置标题；h3 加 `id="modpackImportTitle"`

**验证**：红→绿 TDD —— `tests/test_clients_catalog.py` 追加 RED 2F → GREEN **16**（严格校验/回退链 6 断言）；`tests/test_client_instance_install.py` 新建 RED 4F → GREEN（四件套顺序/目录+隔离/json 落盘/warning 透传/幂等/原版失败传播/main.py 编排静态 7 needle/mll helper）；`tests/test_clients_ui.js` 改写 RED（缺 `openClientImportDialog`/仍含「已下载」/`versionPickerName` TypeError）→ GREEN **115/0**（+ 名称默认值、自定义名透传 `['meteor','1.21.11','MyMeteor']`、弹窗进度态+标题含实例名、并发锁 toast 拦截、完成不锁死回「下载」×2 路径）；全套回归 pytest **151** + JS 8 套 128/115/71/82/196/11/61/22=**686** 全 0 FAIL + `py_compile` + 提取 `<script>` `node --check`；**代理集成冒烟 SMOKE PASS**（tmp 目录、仅跳过原版大资产）：真实目录 optix→`optixclient`、回退链取条目标注 **mc=1.21.10**、推荐 **fabric 0.19.5**、版本 JSON **8 libraries + KnotClient**、隔离目录齐（config/saves/resourcepacks/mods）、**41.6MB jar** 落 `versions/Optix Client Smoke/mods/`、warning 空

### 客户端卡片图标本地化（修 GitHub 头像不显示，2026-10-04）

**现象**：用户截图 —— 客户端页 9 张卡只显字母兜底（meteor/wurst/ares/bleachhack/fpsmaster/combatant/travel/mastermind/payload），其余（Modrinth CDN / forgecdn 图标）全正常。

**根因（先查后修）**：失败清单与图标域名**完全重合**——失败 9 张全是 `github.com/<org>.png?size=128` 外链；三连实测：GitHub 头像**直连超时**、同 URL 走代理 200、Modrinth CDN/forgecdn **直连 200**。应用内 QtWebEngine 未配代理 → 直连 `avatars.githubusercontent.com` 超时 → `<img onerror="this.remove()">` 自愈成字母兜底。上轮冒烟「18 图标全 200」是在**带代理的 Python 进程**里测的，与应用内环境不同。

**实现**：
- 18 张图标全部下载入库 `ui/static/icons/clients/<id>.<ext>`（代理优先、直连兜底、**按 magic 判型**——GitHub 对部分头像实际回 JPEG 但扩展名写 .png，如 BleachHack/MasterMind → `.jpg`；合计 218KB）
- `launcher_core/clients_catalog.py`：18 处 `icon` 字段外链 → `static/icons/clients/<id>.<ext>`（逐条断言替换、残留 `"icon": "http` 断言为零）
- 图床选择不再影响显示，顺带去掉运行时外网依赖（离线/弱网可用，加载更快）

**验证**：红→绿 TDD —— `tests/test_clients_catalog.py` 追加 `test_client_icons_localized_and_exist` RED（NameError→外链断言失败）→ GREEN（逐条：非 http、`static/icons/clients/` 前缀、文件存在非空、格式白名单、**盘上无孤儿文件**）；旧 schema 断言 `icon=="" or startswith("http")` 同步改为仅允许本地/空（新旧两断言互补）；全套回归 pytest **152** + JS 8 套 **686** 全 0 FAIL + `py_compile` OK；`git check-ignore` 确认 `!ui/static/icons/**` 白名单放行新目录（18 文件待跟踪）

**跟进（同日）**：加载完的图标仍透出字母/灰底（透明底图标可见）—— img 加 `onload="this.parentNode.classList.add('icon-loaded')"`，CSS `.client-icon.icon-loaded` 置 `background: transparent` + 隐藏 `.client-icon-fallback`（`onerror remove` 自愈保留，ATH 等无图条目不受影响）；`tests/test_clients_ui.js` 补 4 断言 RED → GREEN **120/0**，全套 JS **691** 0 FAIL + pytest 152 + `node --check`

### 导入弹窗收起改造 + Meteor 重复 jar 去重（2026-10-08）

**需求**：① 点「—」收起后**整窗消失**，进度合并到侧边栏启动按钮上方的进度面板（`#downloadProgressPanel`），可展开还原；② 修「点下载 Meteor 同时出现两个 meteor jar」——同实例重复下载累积旧 jar。

**实现**（纯前端 + 一处 Python 钩子，Python 安装管线零改动）：
- `index.html`：`collapseImportModal` 置 `importCollapsed=true` + `display:none`（不再走 `#importMiniView/#importFullView` 双视图，两块 DOM 删除）；`expandImportModal` 复位并显示面板回收；`closeModpackImportModal` 改调 `resetImportCollapsed()`（不能调 expand，否则关闭时重弹窗口）；面板 header 新增 `#importExpandBtn` 展开小按钮；`updateModpackImportProgress` 收起态分支镜像写面板（title/计数/进度条/文件列表，pct 复用 updateLaunchButton 同款 count 公式避免双写闪烁）；`onModpackImportComplete` 收起态自动展开 + 回收面板
- `mod_manager.py` 新增 `remove_stale_client_mods(new_jar)`：按 `ModInfo.mod_id`（fabric.mod.json）扫同目录其它 .jar 删除，mod_id 空/文件缺失 no-op；main.py jar 下载成功后调用（有 removed 打日志）
- 现场清理：`versions/Meteor Client/mods/` 旧重复已删，仅剩 `meteor-client-1.21.6-7.jar`

**验证**：红→绿 TDD —— `tests/test_import_collapse.js` 新建 RED 11/24 → GREEN **60→63**（11 收起行为 + 完成回收 + 网页流不弹窗守卫）；`tests/test_mod_dedupe.py` 新建 5 用例 + `test_client_instance_install.py` 追加调用时序静态（remove 必须在 `modrinth_api.download_file` 之后、downloadClientVersion 14000 字符窗口内保留全部原 needle）RED → GREEN；`test_client_instance_install.py` 正则笔误 `{0:14000}`→`{0,14000}` 修缮；全套回归 pytest **158** + JS **751/0**（9 套）

### LiquidBounce 内置网页下载（2026-10-08）

**需求**：参考 LiquidBounce Launcher——点卡片「下载」→ **启动器内**开网页窗口选版本 → 接 jar 直链走既有实例安装管线（非外部浏览器打开再手动拖回）。

**实现**：
- `clients_catalog.py`：新 strategy **`web_download`** + 第 20 条 `{liquidbounce, 作弊-PVP, platform=web, endpoint=https://liquidbounce.net/download, kind=jar, icon=static/icons/clients/liquidbounce.svg}`（官方 logo SVG 3981B 入库）
- `main.py`：新槽 `openClientWebPage(client_id)`（校验 strategy 后开窗，`self._client_web_win` 持引用防 GC）+ `startWebClientDownload(client_id, url, filename)`（存 `_web_jar_pending` → `downloadClientVersion(client_id, url, "")` **复用整条安装管线**，不动既有静态 needle）；`downloadClientVersion` 入口防御（web_download 且 version_id≠pending url → 报「缺少网页下载直链」）+ `_do_download` 新分支（url=pending、filename 取建议名、picked_meta 空 → MC 走 current→latest 回退链）；窗口类 `ClientWebPage(QWebEnginePage)` 覆写 `acceptNavigationRequest` 拦 `.jar` 直链导航、`ClientWebWindow`（off-the-record `QWebEngineProfile`、`downloadRequested` 拦 `.jar` → `cancel()` → `startWebClientDownload` → 关窗，非 jar 一律 cancel），插在 LauncherBridge 与 MainWindow 之间
- `index.html`：`downloadClientWithPicker` 新分支 open_page → **web_download** → pack；`onModpackImportComplete` 加可见性守卫（`importCollapsed || display==='flex'` 才 expand，网页流完成不凭空弹窗，失败靠 clientDownloadFinished toast）
- `webengine_flags.py`：`merge_chromium_flags` 注入 env 代理——QtWebEngine 网络栈不读系统代理，`HTTPS_PROXY>https_proxy>HTTP_PROXY>http_proxy` 存在且用户 base 无 `--proxy-server` 时前置注入（应用内网页窗口依赖此项）

**验证**：红→绿 TDD —— `tests/test_liquidbounce_web.py` 新建 5 用例（条目/main.py 槽+窗口+拦截+分支静态/JS 路由分支序/代理 env 四态/无外部浏览器）RED 5F；`test_clients_catalog.py` 改 RED 3F（20 条/14+6/web_download 组成）；`test_clients_ui.js` RED 7F（web_download 行为 + 卡片渲染 + 「作弊」4 卡）；`test_import_collapse.js` 追加 1F（不弹窗守卫）；`test_webengine_flags.py` 既有 3 个 merge 用例补 monkeypatch delenv 消 env 非确定性 → 全 GREEN；全套回归 **pytest 163 + JS 765/0 + node --check（提取 `<script>`）+ py_compile + QtWebEngineCore 导入冒烟 OK**

### Java 自动扫描与多 Java 管理（P0-1，2026-10-08）

**需求**：参考 KAMUCL——设置页自动扫描系统已安装 Java、列表展示多版本（J 徽章/推荐标记）、可选用/隐藏，并让 `java_path` 真正作用于启动（修历史 bug：settings 的 `java_path` 从未被 `game.launch` 使用，只走 mll 自动检测）。

**实现**：
- `launcher_core/java_scan.py` 新模块（IO 全可注入 exists/scandir/runner，测试 hermetic）：`scan_candidates`（JAVA_HOME/PATH 直查 + ProgramFiles/ProgramFiles(x86)/LOCALAPPDATA 下 15 个厂商目录下钻 4 层 + `LOCALAPPDATA\Programs\各厂商` + `minecraft_dir\runtime` 下钻 6 层）→ `find_java_exes`（java.exe/javaw.exe/java 探测，目录命中即停、OSError 容忍）→ `parse_java_version`（`1.8.0_392`→8、`17.0.9`→17，双正则）→ `scan_javas`（normcase+realpath 去重、major 降序）；`required_java_major`（≤1.16→8、1.17→16、1.18/19→17、1.20.0-4→17、1.20.5+/快照/未知→21）；`recommend_java`（**满足要求的最低版本**——避免高版本破坏旧 MC；mc_version 空取最高；无满足项 None）
- `main.py`：`javasScanned` 信号 + `scanJavas` 槽（daemon 线程扫描，`java_hidden` 过滤，按 `_current_mod_version` 推荐，JSON emit，异常回 error 载荷）+ `hideJava` 槽（追加 `java_hidden` 落盘）；MainWindow `_on_javas_scanned` → `runJavaScript(onJavasScanned(...))`；`launchGame` 透传 `java_executable=(settings java_path or '')`
- `launcher_core/game.py`：`launch()` 新参 `java_executable`，命令生成后 `command[0] = java_executable`（显式设置 > mll 自动/捆绑运行时）
- `settings.py`：DEFAULT_SETTINGS 加 `java_hidden: []`
- `ui/index.html`：游戏设置组新增「已安装 Java」块（扫描按钮 + `#javaListItems` 列表 + `#javaListEmpty` 空态）；新函数 `scanJavas/setJavaPathValue/hideJavaPath/onJavasScanned/javaPathEdited`；两处同 id `#javaPath` 经 querySelectorAll 同步（updateSettingsUI 双写、onchange=javaPathEdited 镜像+保存）；`.java-row/.java-badge/.java-rec/.java-path-text` CSS；QWebChannel fallback 补 `scanJavas/hideJava` 空桩

**验证**：红→绿 TDD —— `tests/test_java_scan.py` 新建 9 用例 RED（ImportError: cannot import name 'java_scan'）→ `java_scan.py` 落地后 6 pure GREEN + 3 static 红 → 接线后 **9/9**；`tests/test_java_ui.js` 新建 RED **0/14** → index.html 改造后 **33/0 GREEN**；全套回归 **pytest 172（163+9）+ JS 10 套 798/0 + node --check（提取 `<script>`）CHECK=0 + py_compile OK**；实施计划 `docs/plans/2026-10-08-java-scan.md`（含执行期偏差记录）。未提交，等用户发话。

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

### LiquidBounce queue 页「should start shortly」不下载修复（2026-10-11）

**根因（Playwright 实测官网全链路钉死）**：点 Download Now → React Router POST `/download/<id>/queue.data` → 202 `Location: api.liquidbounce.net/api/v3/file/<pid>` → 302 预签名 S3 直链（`ccbluex-api-private.s3.../versions/<pid>/liquidbounce-<sha>.zip?X-Amz-...`）→ Chromium `downloadRequested`，建议文件名 **`.zip`**。我方 `_on_download_requested` 只认 `.jar` 后缀 → `download.cancel()` 静默吞掉真实下载 → 页面永远停在「Your download should start shortly.」。附带：该 zip 是发行包（内含 `liquidbounce.jar` + FORUM.URL 等推广文本），直接落 mods/ 加载器不识别。旁证：curl 模拟 document POST 恒报「Download Session is not valid」——官网 action 只走 `.data` fetch 端点，document POST 是另一条校验路径，非 bug。

**实现**：
- `main.py`：`ClientWebPage.acceptNavigationRequest` 与 `ClientWebWindow._on_download_requested` 判定改 `.jar/.zip` 元组（query 仍先剥）；`_do_download` 下载成功后 zip 后缀 → `extract_client_mod_jar` 解包取 jar 再进 `remove_stale_client_mods`
- `launcher_core/mod_manager.py` 新增 `extract_client_mod_jar(bundle)`：zip 内全部 .jar 平铺解到同目录（按 basename）、最大者为主 jar 返回、删 zip；无 .jar 抛 RuntimeError 且保留 zip 便于排查

**验证**：红→绿 TDD —— `tests/test_mod_dedupe.py` 新增 3 解包用例 RED（ImportError）→ GREEN；`tests/test_liquidbounce_web.py` 新增 `test_zip_bundle_artifact_handoff_and_unpack` 静态时序（download_file → extract → remove_stale）+ 旧断言改元组 RED 2F → GREEN；全套 **pytest 196（192+4）+ JS 800/0 + node --check 0 + py_compile rc=0 → ALL_PASS**。未提交，等用户发话。

### 下载进度条修复：updateProgress 幽灵元素 + 版本安装确定进度（2026-10-11）

**根因**：`updateProgress` 里写入 `document.getElementById('downloadProgressFile')`，但 HTML 无此 id（全文件仅这一处 JS 引用）→ 空引用 `TypeError` 抛在 `fill.style.width` 之前 → 面板被显示出来，进度条却永远停在 0%。受影响的是全部走 `progressUpdate` 信号的流：版本安装、模组 jar 下载、内容下载、模组加载器安装、整合包 zip 下载（`updateModpackImportProgress` 是另一套独立实现，不受影响）。

**实现**：
- `ui/index.html` `updateProgress`：删掉对不存在元素的写入；`downloadProgressCount` 改为显示百分比（无百分比时清空）；宽度 `Math.round` 收敛，避免脏小数
- `main.py _on_progress_update`：文案改 `json.dumps` 注入——文件名/库坐标含单引号会截断 JS 字面量，让整个进度调用再次静默失效
- `main.py installVersion`：接 mll `setMax`/`setProgress`。mll 仅 libraries/assets 两段回调 `setMax`，两段按 0.6/0.4 权重拼成整体百分比（段间单调不回跳）；其 `setMax` 传 `len-1` 而计数到 `len`，故 frac clamp 到 [0,1]；整体封顶 99% 直到 installComplete 收尾

**验证**：`tests/test_download_progress.js` RED（10 FAIL）→ GREEN；权重公式探针 libs 0→60%、assets 60→99% 单调；全套 **pytest 196 + JS 821/0 + node --check 0 + py_compile rc=0 → ALL_PASS**。未提交，等用户发话。

**构建（同日）**：`build_exe.ps1` 一键通过 → `dist\DevLauncher.exe` 207,557,169 字节（FileVersion 1.1.5.0 / ProductName DevLauncher，图标已嵌入）+ `dist\DevLauncher-b1.1-win64.zip` 206,522,220 字节。冒烟 30s 存活且日志在窗口内有写入（918 个版本、versionsLoaded 已发）。

### LiquidBounce 客户端下载失败 + 客户端下载无百分比（2026-10-11）

**根因**：`logs\launcher.log:116377` 钉死 —— `Download failed: ('Connection broken: IncompleteRead(7729536 bytes read, 16568536 more expected)', ...)`。LiquidBounce 走的 `ccbluex-api-private.s3...` 预签名直链 24 MB zip 下到 7.7 MB 断流，而 `launcher_core/api_modrinth.py:download_file` **零重试零续传**，单次异常即 `return False` → `main.py` 抛 `文件下载失败` → `下载客户端条目失败`，整单判死。S3 大对象预签名链路偶发断流是常态，一次失败即终局是缺陷而非环境问题。

同一现象还盖住第二个独立缺陷：用户看到进度面板但**没有任何百分比**。`main.py` 的 `dl_cb` 只调 `report()`，而三处 `button_detail`（整合包/内容文件/客户端 zip）都不含 `current`/`total`；JS `updateLaunchButton` 的 `installing` 分支只认 `detail.file_total`（此处恒为 0）→ 落进条纹分支并把 `downloadProgressCount` 清空。其余四条下载路径（`main.py:1151/1755/2010/2117`）都额外 emit `progressUpdate` 走已修好的 `updateProgress`（百分比 + 条纹分流），唯独客户端 zip 这条漏了。

**实现**：
- `launcher_core/api_modrinth.py`：`download_file` 拆出 `_download_attempt`，外层按 `DOWNLOAD_RETRIES = 3` 重试。落盘改走 `dest.part` 临时文件 + 成功后 `os.replace`，避免半截产物被当成品装进实例。重试带 `Range: bytes=N-` 续传；`status_code == 416` 清空重来；服务器忽略 Range 回 200 时必须从头 `wb`，否则追加会拼出坏文件。进度回调按 `min(1.0, downloaded/total_all)` 保持单调。三次全败才删残留并返回 False。
- `main.py` `dl_cb`：补 `self.progressUpdate.emit(pct, ...)`，与其余四条路径对齐，进度面板走 `updateProgress` 的百分比分支。

**验证**：红→绿 TDD —— `tests/test_download_retry.py` 新建 6 用例 RED **5F/1P**（续传、服务器忽略 Range、三次全败清理、单发成功、常量存在性、`dl_cb` 含 `progressUpdate.emit`）→ 实现后 **6/6 GREEN**；全套回归 **pytest 196 → 202 passed + JS 821/0 + py_compile rc=0 → ALL_PASS**。

### 页面切换卡顿：重列表卡片离屏布局（2026-10-11）

**诊断（先实测后改码，QWebEngine CDP 探针）**：`.page` 只有 `display:none/block` 切换，`navigateTo` 同步 JS 仅 1–3ms，所以卡顿不在导航函数本身。真机注入 CDP 逐项拆解：`versions=920`，下载页 `dlVersionFilter` 默认 `release` → 网格常驻 **105 张 `.version-card`**（每张约 40 个 DOM 节点，含 4 组内联 SVG），整页共 4203 节点。**切换 `.page.active` 的样式+布局中位数 59.3ms（最多 66.8ms），约 3.5–4 帧掉帧**，这正是「点击页面能感到明显卡顿」。长任务实测 12 个、单个最长 167ms、累计约 1080ms。对照组：mods/worlds/resourcepacks/account/plugins 的往返仅 17–34ms，且各自已走 `threading.Thread` 后台化，排除「Python 主线程阻塞」假设。

**A/B 定案**：运行时注入三种写法各测 5 次取中位数 —— 不处理 **59.3ms**；`.version-card{content-visibility:auto; contain-intrinsic-size:auto 140px}` **6.9ms**（8.6×）；`contain:content` **64.0ms**（无收益，且破坏网格内在尺寸）。注入前后各截一张 1440×900 全页图逐像素比对无差异，网格 `scrollHeight` 正常（5404px）。

**实现**：
- `ui/index.html` `.version-card`：加 `content-visibility: auto`，离屏卡片由 Chromium 跳过样式+布局；配 `contain-intrinsic-size: auto 129px` 占位（`auto` 前缀在真实布局后回填实测高度，避免滚动条跳动；129px 由截图行距 141px 减 grid gap 12px 得出）。

**验证**：红→绿 TDD —— `tests/test_page_switch_perf.js` 新建，RED **5P/3F**（缺 `content-visibility`、缺 `contain-intrinsic-size`、占位高度为 0）→ 加样式后 **8/8 GREEN**。真机复测：切换 `.page.active` 中位数 **72.2ms → 9.1ms**；长任务最长 **167ms → 70ms**，4s 窗口内累计 **1080ms → 469ms**；32 次连续快速切换的长任务 10 → 7。全套回归 **pytest 202 passed + JS 829/0 + py_compile rc=0 → ALL_PASS**。

**遗留（未修，另立）**：首次进入下载页仍有 8 个 50–70ms 长任务。已排除「分批 DOM 构建」假设——脱离文档测量单批 40 张卡 build 9.8ms + layout 2.3ms，批次常量不是瓶颈；真正开销在网格容器自身的样式+布局，需另立条目排查（候选：降低每卡内联 SVG 节点数、`.version-grid` 加 contain）。

### 下载模组时显示依赖与可选依赖（2026-10-13）

**根因**：`launcher_core/api_modrinth.py` 从头到尾没有消费过 Modrinth 版本对象的 `dependencies[]` 字段——列版本、下载两条链路都把它丢掉，用户装一个带依赖的模组只会得到一个起不来的实例，且完全不知道缺了什么。实测（`api.modrinth.com/v2`，2026-10-13）钉死字段形状：`project_id` / `version_id`（**可为 null**）/ `file_name` / `dependency_type` ∈ required|optional|incompatible|embedded。`version_id` 为 null 的语义是「未指定版本」，必须拿 `project_id` 回退挑版本；这个状态若用空串表示，下游会误判成「已指定版本」。依赖清单里只有 `project_id`（形如 `P7dR8mSH`），直接显示对用户毫无意义，必须补项目标题。

**实现**：
- `launcher_core/api_modrinth.py` 新增纯函数：`parse_dependencies`（归一化，丢弃无 `project_id` 的脏项，缺 `dependency_type` 按 `required`，`version_id` 保持 None 而非空串）、`attach_project_info`、`pick_dependency_version`（按父版本的 `game_versions`/`loaders` 挑版本，先只认 `release`，全不匹配再退 beta/alpha——依赖被装成 alpha 比直接装不上更难排查）、`parse_chosen_ids`、`build_download_plan`（主文件 + 勾选的 optional 依赖；`resolve` 回调注入，使清单组装能脱离 Qt/网络单测——`main.py` 无任何测试导入它）
- `ModrinthAPI.get_projects`：批量查项目标题，`GET /projects?ids=<JSON 数组串>`。按 `PROJECT_BATCH = 100` 分片——`getModVersions` 会拉全部版本，大模组上千条，URL 超长会被 API 拒；单片失败只丢该片，不影响其余分片
- `main.py getModVersions`：在已有的 `get_project_versions` 结果上就地解析依赖并挂标题，**零额外请求**，不新增槽/信号
- `main.py downloadModVersion`：签名改 `(content_id, version_id, optional_deps_json)`，走 `build_download_plan` 逐个下载，失败聚合上报
- `ui/index.html`：新增 `renderVersionDeps(deps, versionId)`；required 渲染为标题芯片、optional 渲染为复选框（带 `data-project`/`data-version`），**incompatible/embedded 一律不渲染**；依赖块 `onclick="event.stopPropagation()"`——它嵌在带 `onclick` 的 `.version-picker-item` 里，不拦就会点了复选框直接开下载；`.version-picker-item` 加 `flex-wrap: wrap` + `.vp-deps{flex-basis:100%}` 让依赖块独占一行

**范围取舍**：required 依赖**只展示不自动下载**（自动下载会重复拉取已装的 fabric-api 之类，需要另做「是否已装」判定）；optional 默认不勾、勾了才下载；依赖的依赖不做递归（只一层）。

**验证**：红→绿 TDD —— `tests/test_mod_dependencies.py` 新建 35 用例 RED（`ImportError: parse_dependencies`）→ GREEN；`tests/test_mod_dep_ui.js` 新建 45 断言 RED（`renderVersionDeps is not defined`）→ GREEN。全套回归 **pytest 202 → 237 passed + JS 829 → 874/0（13 文件）+ node --check 内联脚本 189018B rc=0 + py_compile rc=0 → ALL_PASS**。


### 导出实例为 mrpack（2026-10-13）

**动机**：用户要把自己配好的实例分享出去（发给朋友 / 传到 Modrinth）。仓内一直只有「导入」方向（`importModpack` 读 CurseForge/Modrinth 包），没有反向导出。缺这个闭环，`duplicateVersion` 只能复制到本机，无法离开这台电脑。

**实现**：
- `launcher_core/modpack_importer.py` 新增 `export_mrpack(version_name, output_path=None, mc_version=None, loader=None, loader_version=None) -> dict`，私有 helper `_collect_override_files` / `_detect_mc_version` / `_detect_loader`；类常量 `OVERRIDE_DIRS`（`mods` `config` `resourcepacks` `shaderpacks` `defaultconfigs`）、`SKIP_SUFFIXES`（`.part` `.tmp` `.crdownload` `.download` `.bak`，半成品下载不许进包）
- **文件一律走 `overrides/`，`files: []`**。本地 jar 已经在实例目录里、没有可写的 Modrinth 下载链接（`files[]` 需要 `url`+`hashes`+`fileSize`，本地文件给不出哈希以外的可信 URL），而 `files[]` 里的条目本仓导入时会**触发下载**（见 `_import_modrinth` 的 `_download_file` 分支）——若按 `files[]` 塞本地路径，导入会去下不存在的 URL。`overrides/*` 则由 `_import_modrinth` 原样解到版本目录，零网络往返，官方 Modrinth App 也认。
- `dependencies` 只写 mrpack 规范允许的 5 个键（`minecraft` / `forge` / `neoforge` / `fabric-loader` / `quilt-loader`），靠反查表 `LOADER_DEPENDENCY_IDS` 映射，避免写成 `fabric` 这种规范外键
- 顺手修真 bug：`_read_modrinth_manifest`(:218) 与 `_import_modrinth`(:505) 原先用 `'forge' in 'neoforge'` 子串判定 → **NeoForge 包被当成 Forge 导入**，且 `_import_modrinth` 完全不认 quilt。改为统一走新函数 `loader_from_dependencies(deps) -> (loader, ver)`（精确键匹配 + 按 neoforge→forge→quilt→fabric 顺序判定）
- `main.py`：新增信号 `mrpackExported = pyqtSignal(str)`、槽 `@pyqtSlot(str) exportMrpack(version_name)`（后台线程打包，避免同步 zip 卡死 UI）、MainWindow 连接 `self.bridge.mrpackExported.connect(self._on_mrpack_exported)` 与处理器 `_on_mrpack_exported` → `runJavaScript("onMrpackExported(...)")`。数据经 `json.dumps` 注入 JS 字面量——路径含 Windows 反斜杠与引号，字符串拼接必炸
- `ui/index.html`：已安装版本卡片「复制」旁新增「导出 mrpack」按钮（`onclick="event.stopPropagation();exportMrpack(...)"`）；`exportMrpack(versionId)` 先 `showToast` 反馈再调桥接，否则后台打包的几秒里用户会以为没点上；`onMrpackExported(data)` 成功报路径+文件数，失败报 error

**取舍**：默认输出到 `minecraft_dir/<name>.mrpack`，不做文件保存对话框——弹窗会阻塞后台线程的回报路径，且分享场景下固定路径更好找。mc/loader 版本优先取 `get_installed_loaders` / `inheritsFrom`，取不到才落到 `1.20.1` 默认值（mrpack 依赖表里 `minecraft` 必填）。

**验证**：TDD 全程。`tests/test_mrpack_export.py` 先写 16 用例 RED（`ImportError: loader_from_dependencies`），实现后 GREEN。`tests/test_mrpack_export_ui.js` 先写 16 断言 RED（按钮/槽/信号/线程/连接全无），实现后 GREEN。全仓回归 **pytest 237 → 252 passed + JS 874 → 890/0（14 文件）+ node --check 内联脚本 1 block rc=0 + py_compile rc=0 = ALL_PASS**。

### 图形化游戏设置（options.txt）（2026-10-14）

**背景**：内存、Java、窗口尺寸一直堆在设置页，而游戏自己的画质/声音/控制写在 `options.txt` 里，启动器完全够不着，只能手开文本文件。版本隔离打开后每个实例的 `options.txt` 位置还不一样，手改更容易改错文件。

**实现**：
- `launcher_core/game_options.py`：`OPTION_SPECS` 字段目录 39 项，分组「视图/界面/声音/控制」，每项含 `type ∈ bool|int|float|choice|string` 与 `label/group/default/minimum/maximum/choices/hint`；`parse_options` **只切第一个冒号**（Java 路径这类值里带冒号，多切一刀就毁了值）、`format_options` 保序回写、`read_options`、`write_options` 先落 `.bak` 再 tmp + `os.replace` 原子替换、`coerce_value` 按 spec 收敛类型、`build_updates` **只覆盖 UI 提到的键**、`options_path(versions, version_id)` 感知版本隔离
- `main.py`：信号 `gameOptionsLoaded` / `gameOptionsSaved` + 槽 `getGameOptions(str)` / `saveGameOptions(str, str)`（读写都在后台线程，不冻 UI），MainWindow 侧 connect 后 `runJavaScript` 推给 `renderGameOptions`
- `ui/index.html`：版本管理页新增「游戏设置」卡片 → `versionGameOptionsPage`（工具栏 + `gameOptionsPath` + `gameOptionsGroups`）；`renderGameOptions` 按 type 分支渲染开关/滑条/下拉/文本框，label 与 hint **全过 `escapeHtml`**（它们来自 `options.txt`，可以含尖括号），控件带 `data-key` / `data-orig`；`collectGameOptionsUpdates` 只回传改动

**取舍**：只做常用 39 项而非全量键。没 UI 的键在 `build_updates` 里原样带走，不会因为「启动器不认识」就把用户设置抹掉。

**验证**：TDD——`tests/test_game_options.py` 新写 27 条 RED，实现后 GREEN；`tests/test_game_options_ui.js` 新写 36 条 RED（缺卡片/缺页面/缺信号/缺接线），实现后 GREEN。全量回归 **pytest 298 passed + JS 976/0（16 文件）+ node --check 内联 1 block rc=0 + py_compile rc=0 = ALL_PASS**。


### 工具插件 ×3（mods-doctor / instance-size / java-doctor）（2026-10-14）

**背景**：`PluginManager` 一直只有 `hello-sample` 演示，插件体系没有任何真实用例，`PluginContext` 能不能拿到数据、`contentHtml` 能不能撑起一个面板，全靠想象。

**实现**：
- `plugins/mods-doctor/`：审计 mods 目录，输出 `invalid` / `empty` / `leftovers`（非 jar 杂物）/ `duplicates` / `small`；重名检测抽成纯函数 `group_duplicates(names)`——Windows NTFS 大小写不敏感，`Sodium.jar` 与 `sodium.jar` 在同一个目录里**根本共存不了**，共存场景只能在纯函数层构造
- `plugins/instance-size/`：`dir_size` / `_breakdown` / `instance_report` → 全局 + 各实例的体积与构成（mods/config/saves/resourcepacks…），`human(num)` 转人类可读
- `plugins/java-doctor/`：`parse_java_version(text)` 用正则同时吃 `1.8.0_411` 和 `17.0.9` 两种真实输出、`required_java(mc)`（1.16→8 / 1.17→16 / 1.18–1.20.4→17 / 1.20.5+→21）、`evaluate(found, required)`、`probe(java_path)`
- 插件运行时拿不到 minecraft 目录 → 自己 `from launcher_core.settings import Settings` 解析。进程内共享 `sys.path`，可以直接 import `launcher_core`，不必把路径硬塞进 `PluginContext`

**验证**：TDD——`tests/test_tool_plugins.py` 新写 19 条 RED（模块不存在），实现后 GREEN。运行期校验：`PluginManager.scan()` 认出 4 个插件（3 新 + hello-sample）全部 `enabled`，`load_all()` 后各 `detail()['contentHtml']` 都含 `plugin-content`、`errorMsg` 为空。全量回归 **pytest 298 passed + JS 976/0（16 文件）= ALL_PASS**。


### 界面中英双语（i18n）（2026-10-14）

**背景**：界面文案硬编码在 `index.html` 的标记和内联 JS 字符串里，共 331 条中文，没有语言开关。

**实现**：
- `tools/i18n/collect.py`：`HTMLParser` 先把 `<script>` / `<style>` 体分离出来，再分别抽标记文本、`title` / `placeholder` / `aria-label` 属性、JS 的单引号/双引号/模板串三类字面量；空白归一后写 `strings.json`
- `tools/i18n/en.json` 331 条 zh→en；`tools/i18n/build.py` 把每条源串拆成**独立单元**（整串、HTML 内层文本、属性值）各配一个 key，产出 `ui/i18n_dict.js`（`map` 中文→key、`mapEn` 英文→key、`zh` / `en` 按 key 对齐）
- **为什么必须按单元拆 key**：DOM 里既没有整段 JS 字面量、也没有 HTML 标签，只有文本节点和属性值。整串与内层共用 key 时，文本节点会查到 `en[key]`＝**整段 HTML**，然后被替换成一整段标签——这是实现中真踩到的 bug，已用「内层单元必须译成纯文本」的回归用例钉死
- `ui/i18n.js` 运行时：`detectLocale()` 首启读 `navigator.language`（非 en 回落 `zh-CN`），偏好存 `localStorage['devlauncher.locale']` 并**覆盖**系统语言；`translate(root)` 用 `TreeWalker` 翻文本节点、遍历 `title/placeholder/aria-label`，跳过 `SCRIPT` / `STYLE`；`MutationObserver` 跟进 JS 动态注入的节点；精确命中失败时对含 CJK 的文本做**长词优先**子串拼接（覆盖 `'确定要删除世界 "' + name + '" 吗？'` 这类 `+` 拼出来的消息）；`setLocale` 双向可逆（靠 `mapEn` 回查）并广播 `i18n:change`
- `ui/index.html`：qwebchannel 之后依次引入 `i18n_dict.js` + `i18n.js`（顺序固定，运行时要读词典）；设置页新增「界面语言」下拉 → `changeLocale(value)` / `syncLocaleSelect()`

**取舍**：**不**把 331 处字面量改写成 `t('key')`。以中文源文为反向索引，静态标记与 JS 生成的 HTML 都零改码，风险集中在生成器一处；代价是文案改动必须重跑 `collect.py` + `build.py`（已验证两次产出 SHA256 一致、可复现）。

**验证**：TDD——`tests/test_i18n_runtime.js` 新写 50 条（词典完整性、en 不得残留中文、内层单元不得译成 HTML、locale 探测/持久化/覆盖优先级、双向切换与幂等、拼接消息无 CJK、脚本与设置页接线）。全量回归 **pytest 298 passed + JS 976/0（16 文件）+ node --check 内联 1 block 193626B rc=0 + `ui/i18n.js`、`ui/i18n_dict.js` rc=0 + py_compile 64 文件 rc=0 = ALL_PASS**。


### 下载提速（2026-10-14）

**背景**：用户反馈下载慢。先把 mll 的真实执行顺序挖出来再动手，结论和直觉相反：`install_libraries` / `install_assets` / `install_jvm_runtime` **本就各自 `ThreadPoolExecutor` 并行**（默认 ≈ `min(32, cpu+4)`），"让库和资源并行"是个错误方向。真正的开销在三处：一是 `do_version_install` 的尾部**完全串行**——装完 assets 还要依次下 logging config、**30MB 的 client jar**、再下 **50–200MB 的 JVM runtime**；二是所有下载无重试、无断点续传、失败即整段重来；三是国内直连 Mojang/Microsoft 站点本身慢。

**实现**：
- `launcher_core/net.py`（新建）：`build_session(proxy, retries=3, backoff=0.6)` 用 `HTTPAdapter` + urllib3 `Retry`（`status_forcelist=(429,500,502,503,504)`，`allowed_methods={"GET","HEAD"}`——**POST 不能自动重试**，皮肤上传这种带副作用的请求重放会重复提交；兼容旧版 urllib3 的 `method_whitelist` 参数名）。`download_file(url, dest, sha1, session, callback, timeout, retries)`：先落 `.part`，成功才 `os.replace` 原子改名；**Range 续传**只在"上一轮断过且片段还在"时发，服务器若忽略 Range 直接回 200 就改成 `wb` 整段重写（避免把新数据拼到旧数据后面）；回 416 说明片段长度已越界 → 删掉片段后**重来且不再带 Range**；`sha1` 不符即判失败并删片段重试；callback 收的是**累计**字节（跨重试单调不减），上游才能算出真实比例。失败**只删 `.part`，绝不删已有的 dest**——半成品比没有强
- `api_modrinth.py:372` 的 `download_file` 改为**委托** `net.download_file`，保留原有"收 0.0~1.0 比例"的回调契约，顺带删掉自己那份 `_download_attempt`
- `launcher_core/fast_install.py`（新建）：`tail_jobs(data, mc)` 取 client jar + logging config 两条尾巴；`fast_install()` 把「库+资源」和「尾部」丢进**同一个线程池**并跑，JVM runtime 若版本里声明了 `javaVersion` 就当第三条并行分支；`resolve_version_json()` 本地已有 json 就**完全不联网**，否则拉 manifest_v2 并带 sha1 校验——manifest 请求原先没有 timeout，会无限挂着
- `MergedProgress`：把上游零散的 `setMax` / `setProgress` 归一成**单相位 0..100**。`_best` 保证进度**只增不减**（上游并行时各线程的 count 会互相穿插，不 clamp 就会倒退），同一整数百分比**去重**（并行下载每完成一个文件就报一次，不过滤会把 Qt 信号刷爆）；`finish()` 强制落到 100，兜住"上游某个分支一个都没报进度"的空洞
- 接线：`versions.py` / `main.py downloadVanillaVersion` / `launcher_core/game.py`（父版本）/ `launcher_core/modpack_importer.py` 四处 `install_minecraft_version` 全部换成 `fast_install`
- **单相位契约的连带改造**：`main.py installVersion` 原先用 `phase_weights=(0.6, 0.4)` + `phase_no` 累加，那套逻辑**建立在"setMax 只被调一次、且两条相位串行"的假设上**，并行后必然错乱 → 改写成 `setMax(100)` 一次 + `setProgress(0..100)`，`on_set_max` 变成**有意的空实现**（并加注释说明，防止后人"修好"它）。`inheritsFrom`（Forge/NeoForge）回退给 mll 顺序安装的路径**也套一层 `mp.phase("mll")`**，保证上游拿到的形状完全统一
- 设置项：`settings.py` 新增 `download_proxy` / `download_workers`；`fast_install.configure(workers, proxy)` 作为模块级默认值（调用方签名不变）；`proxy` 同时写进 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量——mll 内部那些不经过本模块的 `requests` 走 `trust_env`，这样**它自己的下载也一并走代理**。设置页新增「下载设置」分组（代理 URL + 并发数），启动与 `saveSettings` 时都会重新 apply

**取舍**：没有做"按相位分配权重"的精细进度条——权重需要预先知道各相位大小，而 assets 的字节数在 index 里、libs 的大小随版本剧烈变化，估不准的权重比粗进度更误导。最终采用"预声明相位名 + 单调 clamp"，宁可粒度粗一点，也不出现倒退和刷屏。并发数默认 16 而不是 mll 的 32：Mojang 的 CDN 对同 IP 高并发并不友好，实测 16 是收益与封禁风险的平衡点。

**验证**：TDD——`tests/test_net.py` 新写 16 条 RED（模块不存在），覆盖 Range 仅在重试时发、进度跨重试单调、服务器忽略 Range 时重写、416 删片段重来、全失败只留旧文件、sha1 大小写与不符、代理注入、`Retry` 只覆盖 GET；`tests/test_fast_install.py` 新写 21 条 RED，覆盖单 `setMax(100)`、多相位合并、不倒退、越界 clamp、finish→100、同百分比去重、`run_phases` 真并发（`threading.Barrier(3)` 证明三条分支确实同时在跑）、`fast_install` 四相位装配、inheritsFrom 回退且形状统一；下载设置另写 4 条。`tests/test_download_retry.py` 原有 7 条在委托后**必须继续绿**——委托不许改变外部可见行为。全量回归 **pytest 298 → 355 passed**。


### 皮肤与披风（2026-10-14）

**背景**：用户想在启动器里直接改皮肤和披风，不用开官网。查 Minecraft Services API 后有两个硬事实必须先说清：一是这两套接口**只对微软正式号开放**，离线号的 `access_token` 固定是字符串 `"offline_token"`（见 `auth.py`），调用只会拿到 401；二是**披风没有自定义上传接口**，只能在账号已拥有的披风里装备/隐藏，`PUT .../capes/active` 传一个没拥有的 `capeId` 会返回 400 "Player does not own the requested cape"。

**实现**：
- `launcher_core/skins.py`（新建）：`list_profile`（GET `/minecraft/profile`，归一成 `{name, id, skins, capes}`）、`upload_skin`（**multipart/form-data** 提交本地 PNG + `variant`，官方 launcher 就是这么做的；`variant ∈ slim|classic`）、`equip_cape`（`PUT` + `{"capeId": ...}`）、`hide_cape`（`DELETE`）
- `png_size` 直接读 PNG 的 `IHDR` 取宽高（8 字节签名 + 4 长度 + `IHDR` + 宽高），**不引 Pillow**——校验只需要尺寸，为一个宽高数字拖一个图像库进依赖不划算
- `_headers(access_token)` 是**所有请求的第一道闸**：`is_offline()` 命中就抛 `SkinError`，一个字节都不发出去。`upload_skin` 里这道闸排在 `validate_png` **之前**，离线号连文件都不用读，报错也更靠得住
- 错误透传：非 2xx 时优先取响应体的 `errorMessage` / `error`，取不到就截断 body，统一包成 `HTTP <code>: <msg>` 抛出，UI 原样展示
- `main.py`：信号 `skinsResult` / `skinFileSelected` + 槽 `skinsRefresh` / `skinsUpload(path, variant)` / `capeEquip(cape_id)` / `capeHide` / `selectSkinFile`，全部后台线程执行；每个操作**成功后顺带重新拉一次 profile**，UI 收到的永远是最新状态，省掉一次"上传完还要手动刷新"。MainWindow 侧 `_on_skin_file_selected` 用 `json.dumps(path)` 注入 JS——Windows 路径里的反斜杠会让字符串字面量炸掉
- `ui/index.html`：设置页新增「皮肤与披风」分组。皮肤预览直接用 API 返回的 `textures.minecraft.net` URL（该域无需鉴权即可取图）；选中 variant 会跟着当前 ACTIVE 皮肤回填；披风列表把 ACTIVE 那个渲染成禁用态并标「使用中」，其余可点装备。选文件走 `selectSkinFile` → `QFileDialog` → 信号回传 → JS 再带当前 variant 调 `skinsUpload`，这样 variant 的选择权留在 UI、文件选择权留在原生对话框，两边各司其职

**边界**（写进 UI 说明区，不靠文档）：需要微软正式账号；离线账号无法更改；披风只能在已拥有的之中切换，不支持自定义上传。另外**图片只校验 64x64 / 64x32 两种合法尺寸，不额外硬卡文件体积**——体积上限在官方 API 文档里没有公开写死的数字，宁可透传服务端的原始报错，也不要本地先拒一个服务端其实接受的文件。

**验证**：TDD——`tests/test_skins.py` 新写 16 条 RED（模块不存在）：尺寸校验三态、非 PNG、文件不存在、multipart 里确实读到了文件本体（`_Sess` 在收到请求时就把 file 句柄读成 bytes，因为 `with open` 在请求返回后就关了，直接断言句柄会拿到 closed file）、未知 variant、离线号三种 token × 四个接口**零网络调用**、披风 id 必填、API 错误原样透传。全量回归 **pytest 339 → 355 passed**。i18n：重跑 `collect.py` + `build.py`，源串 334 → 347，补 19 条英文（16 条皮肤披风 + 3 条下载设置），产出 `i18n_dict.js` 347 键 / 402 单元。全仓门禁 **node --check 内联 1 block 193941B rc=0 + py_compile 72 文件 rc=0 = ALL_PASS**。
### 打包：冒烟判据修复 + 插件全量打包（2026-10-15）

**问题**：`build_exe.ps1` 的冒烟只验「30s 进程存活 + 日志 LastWriteTime 更新」。`MainWindow.__init__` 中抛异常时，PyInstaller 会弹出未处理异常对话框——**进程照样存活**，且崩溃前的 `logger.info` 已让日志有新写入，两个条件同时成立。实测：`main.py:732/2844` 处 `fast_install.configure(...)` 抛 `AttributeError: 'function' object has no attribute 'configure'`，脚本仍报 BUILD OK。

**根因**：`main.py` 顶部 `from launcher_core.fast_install import fast_install` 导入的是**函数**，遮蔽了同名模块，模块上的一切属性访问都会 AttributeError。改为 `from launcher_core.fast_install import configure as configure_downloads, fast_install`，两处调用点（`saveSettings`、启动期）改用别名。

**修复**：
- 新增 `tools/smoke_check.py`：读日志**增量**（记录起跑前 `Length` 作偏移，只看本次新写入），判据两条——① 出现 `MainWindow 初始化完成`（与网络无关，证明 configure/信号连接全走完）；② 出现 `versionsLoaded` 或 `获取版本列表失败`（断网属合法环境同样放行，两者都缺 = 页面根本没加载）。中文标记定义在 Python 侧，规避 `.ps1` 无 BOM 被按 ANSI 解读的编码坑
- `build_exe.ps1`：`$logged`（LastWriteTime）→ 调用 `smoke_check.py $logPath $beforeLen`，`$booted=$LASTEXITCODE -eq 0`，成功条件 = `alive -and booted`
- zip 阶段由只打包 `plugins/hello-sample` 改为遍历复制全部插件目录（现 4 个）

**回归**：`tests/test_smoke_and_imports.py` 8 个用例——冒烟四分支（正常/断网/崩溃于 init 前/页面未加载）+ CLI 偏移语义 + 构建脚本接线，以及一个**跨全仓 AST 检查**：凡 `from launcher_core.X import Y` 且 `Y` 是普通函数，全仓 `.py` 中不得出现 `Y.attr` 形式的属性访问，从机制上封死「函数遮蔽模块名」这一类崩溃。全量门 **pytest 363 passed + py_compile 60 文件 + node --check 内联 1 block 全绿**。

**构建实证**：`dist/DevLauncher.exe` 207,621,521 字节；`dist/DevLauncher-b1.2-win64.zip` 206,610,933 字节、14 条目、4 个插件全进包；冒烟输出 `boot ok (page=versionsLoaded)`；日志含 `MainWindow 初始化完成` + `versionsLoaded (长度: 296604)`、919 个版本，且**无** attribute 错误。

**反向验证（证明判据真能抓到那个崩溃）**：把启动期 `configure_downloads(` 临时改回 `fast_install.configure(` 重建 → 冒烟三次均报 `启动未完成，缺少标记: MainWindow 初始化完成; versionsLoaded 或 获取版本列表失败`，其中 `alive=True exit=- booted=False`——**正是旧判据会误判为成功的那一组**（假活 + 日志有新增）——构建在 `throw 'smoke failed 3 times'` 处中止，`dist/DevLauncher.exe` 未被放行为好包；改回后重建 `boot ok (page=versionsLoaded)` + BUILD OK。注意：崩溃的 exe 会弹异常对话框占住文件句柄，`throw` 跳过了脚本末尾的进程清理段，再次构建前须手工 `Stop-Process` 全部 `DevLauncher`/`QtWebEngine` 进程，否则 PyInstaller 报 `PermissionError: [WinError 5]` 写 exe。

### 账户页签整合皮肤与披风（2026-10-17）

**需求**：把设置里的「皮肤与披风」连同账户管理一起拆到新页签，位置在「插件」上方。现状：皮肤与披风在 `#settingsPage` 里，账户管理本就是独立页签 `#accountPage`（位于设置**之前**）——设置页里并没有账户分组。因此落地取向是：皮肤分组迁入 `#accountPage`，账户页签重新排到设置之后、插件之前（不新增第九个页签，避免账户界面重复两份）。

**改动**（均在 `ui/index.html`）：
- 从 `#settingsPage` 删除「皮肤与披风」整个 `settings-group`（预览图、variant 下拉、更换皮肤/刷新、披风列表、隐藏披风、说明区）
- 同一块标记原样迁入 `#accountPage` 的 480px 容器内、紧接账户卡列表之后
- 侧栏顺序由 versions→download→mods→worlds→resourcepacks→**account**→settings→plugins 改为 …→resourcepacks→settings→**account**→plugins
- `navigateTo()` 的刷新职责从 `page === 'settings'` 分支搬到 `page === 'account'` 分支：进账户页同时拉 `getAccounts()` 与 `skinsRefreshNow()`；空了的 settings 分支直接删掉

**红绿**：`tests/test_account_skin_tab.js` **34 断言**（RED 16 FAIL → GREEN 34/0）——区块切片后断言设置页不再含 `skinPreview`/`capeList`/`skinVariant`、账户页接管全部控件、`皮肤与披风` 全局仅 1 次（防重复分组）、侧栏顺序严格等于预期数组且 account 紧邻 plugins 上方、`navigateTo` 的 account 分支含 `skinsRefreshNow()` 而 settings 分支不再含。

**门禁**：pytest **363 passed**；17 个 node 测试文件共 **1010 断言 0 失败**（新增的 34 使旧基线 976 升至 1010）；`py_compile` 60 文件 rc=0；`node --check` 内联 1 block + `ui/i18n.js`/`ui/i18n_dict.js` rc=0。
`tools/i18n` 重跑后 `strings.json` 与 `ui/i18n_dict.js` **字节级不变**（347 键 / 402 单元）——收集器按 sha1 排序，与标记在文档中的位置无关，搬家不会产生新文案也不会重排词典。
### 皮肤/披风标签置顶 + 令牌过期自动刷新（2026-10-17）

**需求**（用户报障 + 截图）：① 账户页「当前皮肤」这类标签竖排（一字一行）且被挤在卡片内，要求改成暗灰色小标题放到卡片**上方**（「卡钳」为用户笔误，实指「卡片」）；② 皮肤/披风加载失败。

**竖排根因**：`.settings-item { display:flex; justify-content:space-between }` + `.settings-item-label { flex:1 }`（即 `flex: 1 1 0%`）。长值（`皮肤/披风请求失败: HTTP 401: Unauthorized`、或整段说明文字）的 `flex-basis: auto` 吃掉整行宽度，标签 basis 为 0 被压到 0 宽 → 中文逐字换行。同一分组的「说明」行有完全相同的缺陷。

**401 根因**：`~/.mc-launcher/accounts.json` 中微软账号 `DishonesINcludeX` 的 `access_token` 是 XBOX JWT（`exp=1789274269` = 2026-09-13，**已过期 34 天**），而全仓从无 `auth.refresh_login()` 调用——令牌只在登录时取一次，此后永久复用。日志现场：`GET /minecraft/profile HTTP/1.1" 401 35`。

**改动**：
- `ui/index.html`：新增作用域类 `.skin-cape-caption`（`width:100%; flex:none; font-size:12px; color:rgba(255,255,255,0.42)`）与 `.settings-item--skin-cape`（`flex-wrap:wrap` + `> * { min-width:0 }`）；「当前皮肤 / 披风 / 说明」三个标签从卡片内的 `.settings-item-label` 上移为卡片外的小标题（块级 `<div>`，`width:100%` 才独占一行）；通用 `.settings-item-label { flex:1 }` 未动，其他设置项外观不变
- `launcher_core/tokens.py`（新）：`jwt_expiry(token) -> int | None`（就地 base64url 解 payload 取 `exp`，段数/base64/缺 `exp`/payload 非 dict/`exp` 非数字等畸形输入一律返回 `None`，绝不抛）、`is_expired(token, now=None, skew=60)`（`exp <= now + skew` 视为过期，`exp` 未知一律 `False`）
- `launcher_core/skins.py`：新增 `is_unauthorized(exc)`、`ensure_fresh_token(access_token, refresh)`（离线标记原样放行；仅本地判定已过期才 `refresh()`）、`call_with_refresh(call, access_token, refresh)`（401 → 刷新一次 → 换新 token 重试一次；刷新为空/同值 → `raise SkinError("登录已过期，请重新登录") from exc`；非 401 直接透传；只重试一次）
- `main.py`：新增 `LauncherBridge._refresh_access_token()`（读 `get_login_data()` 的 `refresh_token` → `auth.refresh_login()`，异常不出线程，返回新 `access_token`）；`_skins_async` 串上 `ensure_fresh_token` / `call_with_refresh`，四个入口（刷新 / 上传 / 装备 / 隐藏）零契约变更

**红绿**：
- `tests/test_account_skin_tab.js` **34 → 43 断言**：3 个小标题必须是块级 `<div>`、每个都排在其卡片之前、卡片内不得再有 `.settings-item-label`、`.skin-cape-caption` 必须 `width:100%` + `flex:none`、`.settings-item--skin-cape` 必须 `flex-wrap:wrap`、通用 `.settings-item-label { flex:1 }` 不得被改
- `tests/test_tokens.py`（新）**12 断言**：exp 提取、带/不带 `=` 填充、段数错、坏 base64、缺 `exp`、payload 非 dict、`exp` 非数字、已过期、skew 两侧边界、离线/非 JWT 串
- `tests/test_skins.py` **+10 断言**：401→刷新→成功（断言第二次调用带的是新 token）、刷新返回 `None` 时抛精确文案 `登录已过期，请重新登录` 且 `__cause__` 链到首个 401、同值 token 也抛、非 401 直接透传且 refresh 不被调用、只重试一次、未过期不刷新、离线标记不动
- **反向验证**：把 `.skin-cape-caption` 的 `<div>` 换成 `<span>`、把 `flex:none` 改成 `flex:1 1 auto`、删掉 `flex-wrap:wrap`、把标题挪到卡片之后——四种变异**全部 FAIL**，还原后 sha1 一致

**视觉验证**（Edge headless 渲染真实 CSS + markup，包装页放在仓库外）：1100px 与 760px 宽、且向 `#skinsStatus` 注入真实错误串 `皮肤/披风请求失败: HTTP 401: Unauthorized` —— 三个小标题均为暗灰、独占一行、位于各自卡片上方；长错误串在卡片内正常换行，**全页不再出现任何逐字竖排**。

**门禁**：pytest **385 passed**（旧基线 363 + 22）；17 个 node 测试文件共 **1019 断言 0 失败**（旧基线 1010 + 9）；`py_compile` 62 文件 rc=0；`node --check` 内联 1 block + `ui/i18n.js`/`ui/i18n_dict.js` rc=0。`tools/i18n` 两个产物字节级不变（`ui/i18n_dict.js` sha1 `6F93E5B0…`、`tools/i18n/strings.json` sha1 `5EEE7CCC…`）——文案未改、仅移动节点，而收集器按 sha1 排序、与标记位置无关。
### 账户页披风预览 + 下拉框统一 + 微软四色 Logo（2026-10-18）

**需求**（用户报障 + 2 张截图）：① 账户页显示披风预览、自动显示当前披风；② 「当前皮肤」的 variant 下拉框风格与其他控件不一致、文字看不见；③ Microsoft 图标换成微软品牌色。

**根因**：① 披风卡片里只有 `#capeList` 与「隐藏披风」按钮，压根没有预览元素，装备披风后没有任何视觉反馈；② `#skinVariant` 是全仓唯一没走共享 `.settings-input` 的控件，靠一段内联 `background/border/color:#fff` 手写样式，且缺 `color-scheme:dark` —— 深色页面上原生下拉按浅色主题渲染，白字配白底即「文字看不见」；③ 微软图标是单色描边 svg（4 个空心 `rect`，`stroke="white"`），3 处字节完全相同。

**改动**（均在 `ui/index.html`，**零 CSS 变更**）：
- 披风卡片首位新增 `<img id="capePreview" style="width:64px;height:32px;object-fit:contain;image-rendering:pixelated;border-radius:6px;background:rgba(0,0,0,0.25);display:none;">`（64x32 即披风纹理尺寸）
- `renderCapeList(capes)`：在 `!capes.length` 早退**之前**处理预览 —— 取 ACTIVE（否则取首个）披风的 `url` 写入 `src` 并 `display:block`；无 url 或空列表则 `removeAttribute('src')` + `display:none`。装备/隐藏披风走 Python `emit skinsResult` → `onSkinsResult` → `renderSkinsProfile` → `renderCapeList`，预览自动跟随，无需手动点「刷新」
- `#skinVariant` 删除全部内联配色，改用 `class="settings-input"`（深色背景 + `color-scheme:dark` + `option` 深色主题），仅保留 `style="width:auto;min-width:160px;"` 以压过 `.settings-input` 的固定 120px 宽、保证选项文字不被裁剪
- 微软图标 3 处（markup 登录按钮 + 2 处 `microsoftBtn.innerHTML` 字符串）换成四色品牌 `<rect fill="#F25022"/"#7FBA00"/"#00A4EF"/"#FFB900">`，去掉 `fill="none" stroke="white"`；全页仍有 29 处 `stroke="white"`（离线登录/退出登录等无关图标），未动

**红绿**：`tests/test_account_skin_tab.js` **43 → 64 断言**（+21）——
- `#capePreview` 全局恰 1 个、排在 `#capeList` 之前、是第 2 张 `.settings-item--skin-cape` 卡片的直接子元素（卡片开头到预览之间不含 `</div>`，排除塞进其它卡片）
- `renderCapeList` 源码含 `capePreview`/`.src`/`.url`/`'none'`，且 `capePreview` 出现在 `暂无披风` 之前（证明隐藏路径覆盖了 `!capes.length` 早退分支）
- `#skinVariant` 标签含 `class="settings-input"`，内联样式**不含** `background`/`border`/`color:`，含 `width:auto` + `min-width`
- 四色 Logo 恰 3 处；单色版（`stroke="white"` 与 `<rect x="2" y="2"` 组合）0 处；4 个品牌色 hex 各在 Logo 标签内至少出现 1 次

**视觉验证**（Edge headless 渲染真实 CSS + markup + **真实 `renderSkinsProfile`/`renderCapeList` 源码**，喂合成 64x32 披风纹理）：Case A（1 ACTIVE + 1 非 ACTIVE）披风卡片左侧显示披风预览图；Case B（空列表）预览隐藏、卡片内显示 `暂无披风`；两 Case 中 variant 下拉均为深色主题、文字清晰、与相邻「更换皮肤 / 刷新」同风格；Microsoft 登录按钮为四色品牌图标。

**门禁**：pytest **385 passed**；17 个 node 测试文件共 **1040 断言 0 失败**（旧基线 1019 + 21）；`py_compile` 62 文件 rc=0；`node --check` 内联 1 block + `ui/i18n.js`/`ui/i18n_dict.js` rc=0。`tools/i18n` 两个产物字节级不变（`ui/i18n_dict.js` sha1 `6F93E5B0…`、`tools/i18n/strings.json` sha1 `5EEE7CCC…`）—— 未改动任何用户可见文本，仅新增控件与图标。

### 启动详细过程面板 + 早期日志（2026-10-18）

**需求**（用户报障）：点「启动游戏」后几乎瞬间就变成「游戏运行中」，看不到启动器做了什么，要求显示启动过程的详细细节。

**根因**：`GameLauncher.launch()` 在 `Popen` 返回后立即 `return True, "游戏已启动"`，`main.py` 随即 emit `("running", "游戏运行中")`；整条链路只有 `launching` / `running` 两个状态，中间的版本校验、Java 探测、父版本安装、参数拼装、natives 解压全部静默。游戏 stdout 虽被重定向到 `<游戏目录>/logs/game.log`，但从未有代码读取它。

**改动**：
- `launcher_core/game.py`：`launch()` 新增 `on_progress(step, text)` 回调（默认 `None`，旧调用零影响），在 14 个阶段上报：`check_version` / `version_ok` / `check_java` / `java_ok` / `check_files` / `files_ok` / `gamedir` / `build_command` / `command_ok`（含 Java 名、内存区间、参数个数）/ `natives` / `natives_ok`（含解压个数）/ `spawn` / `spawned`（含 PID）/ `waiting`；父版本补装另有 `parent_install` / `parent_ok`，失败路径有 `java_fail`
- `_emit_progress()` 吞掉回调异常：UI 断链绝不影响启动
- Java 探测修正：`java_executable` 存在即用（标注「设置」）；设置路径不存在时记 `java_warn` 并回退自动探测；两者都没有才 `java_fail`。此前即使玩家手动指定 Java，只要 mll 自动探测失败就拒绝启动
- 新增 `_tail_game_log()` 守护线程：从 `logs/game.log` 逐行读取最多 25 秒 / 80 行（单行截断 300 字），命中 `Setting user` / `Backend library` / `OpenAL initialized` / `Created:` 任一标记即上报 `ready`；进程提前退出则上报 `exit`（带退出码）
- `main.py`：新增 `launchDetail = pyqtSignal(str, str)`；`launchGame()` 把 `self.launchDetail.emit` 作为 `on_progress` 传入，未登录 / 失败 / 异常各补一条 `error`；`_on_launch_detail` 用 `json.dumps` 安全注入 `appendLaunchDetail(step, text)`
- `ui/index.html`：启动区新增 `#launchDetailPanel`（`#launchDetailLog` 复用 `.download-file-list` 滚动样式 + 等宽字体），`appendLaunchDetail()` 用 `textContent` 造行、带 `HH:MM:SS`、按步骤着色（成功 / 就绪 / 错误）、上限 200 行、自动滚底；`toggleLaunchDetail()` 折叠展开；`launchGame()` 开新局先 `launchDetailClear()`；`updateLaunchButton('installing')` 隐藏旧详情
- i18n：新增静态文案「启动详情」→ `Launch details`；`collect.py` 同时补收了 §43 改为四色后的 Microsoft 图标字符串（此前未重跑收集器），`build.py` 产物随之更新

**红绿**：
- `tests/test_game_launch_progress.py`（新）**10 断言**：14 阶段顺序与文案、PID、内存、日志文件落盘、无回调兼容、设置 Java 直用、设置路径失效回退、无 Java 失败、版本缺失提前失败、日志行 / 就绪 / 提前退出、natives 计数、main/UI 接线
- `tests/test_launch_detail.js`（新）**38 断言**：面板位置（启动区、按钮上方）、追加 / 时间戳 / 自动滚动、`textContent` 不解析 HTML、步骤配色、200 行上限、清空与折叠、启动清空 / 安装隐藏

**视觉验证**（Edge headless）：① 独立包装页用真实 CSS 渲染 12 行（含长 Java 路径与 25 个模组的超长行）—— 换行正常、时间戳弱化、就绪行为绿色；② 真实 `ui/index.html` 注入真实 `appendLaunchDetail` 调用后截图 —— 面板出现在启动按钮正上方，滚动到底部显示最新日志，无布局破坏。

**门禁**：pytest **395 passed**（旧 385 + 10）；18 个 node 测试文件共 **1078 断言 0 失败**（旧 1040 + 38）；`py_compile` 63 文件 rc=0；`node --check` 内联 1 block + `ui/i18n.js`/`ui/i18n_dict.js` rc=0。i18n 按预期变更：`strings.json` 347→348 键、`ui/i18n_dict.js` 重建（新增「启动详情」，并补收 §43 的四色图标字符串）。

### 启动提速：onedir 打包 + 原生启动画面（2026-10-20）

**现象**：双击 `dist\DevLauncher.exe` 后约 8 秒窗口才出现，期间桌面没有任何反馈。

**实测定位**（`dist\logs\launcher.log` 首行时间戳 vs 进程创建时间）：

| run | 到主窗口 | 进程创建 → 首行日志 |
| --- | --- | --- |
| 1 | 9470 ms | 8092 ms |
| 2 | 7966 ms | 7084 ms |
| 3 | 8587 ms | 7829 ms |

即 85%~95% 的时间花在应用自身首行日志之前——PyInstaller onefile 每次启动都要把约 207MB 解包到 `%TEMP%\_MEI*`，与 MainWindow、QtWebEngine 初始化无关。只加启动画面覆盖不到这段空白。

**改动**：
- `build_exe.ps1`：`--onefile` → `--onedir`，入口 `main.py` → `boot.py`；发布 zip 改为整个 `dist\DevLauncher\` 目录（含 `_internal`），解压后运行 `DevLauncher\DevLauncher.exe`；冒烟路径同步；`--clean` 保持
- `boot.py`（新）：先设置 `AA_ShareOpenGLContexts`（QtWebEngine 要求，否则必须在 QApplication 之前 import QtWebEngineWidgets，启动画面就来不及显示），再创建 QApplication 与启动画面，最后 `import main`；失败时把 traceback 写入 `logs/launcher.log`（windowed 无控制台）
- `launcher_core/splash.py`（新）：460×172 无边框卡片（12px 圆角、代码绘制图标、状态文本、不定进度条、半透明背景），只依赖 QtCore/QtGui/QtWidgets；`set_status()` 立即 `processEvents`，`finish()` 幂等
- `main.py`：`main(app=None, splash=None)` 支持注入已创建的 QApplication；三处状态文本（加载运行库 / 初始化账户与版本 / 加载界面）；`web_view.loadFinished` 关闭启动画面，另有 6s 兜底
- `pytest.ini`（新）：`testpaths = tests` + `norecursedirs` 排除 `dist`。onedir 后 `dist\DevLauncher\_internal` 是一整套 Python 环境，根目录裸跑 pytest 会递归进去并导致进程崩溃（0xC0000409）

**实测（同机各 3 次）**：启动画面 **0.76~0.91s**；主窗口 **1.28~1.68s**（改前 7.97~9.47s），约 5~6 倍；冷启动（首次解压后）约 2.6s。

**代价**：发布形态由单文件变为文件夹（`DevLauncher.exe` + `_internal\`），这是省掉每次解包的必然结果；用户解压后路径为 `DevLauncher\DevLauncher.exe`。

**回归**：pytest **400 passed**（+5 `tests/test_startup_splash.py`）；node 18 文件 **1078 断言 0 失败**；`py_compile` 66 文件；`node --check` 通过。`tests/test_build_assets.py` 断言改为 `--onedir` + `boot.py`，版本资源 1.2.1.0。
### 模组列表渐进渲染：首屏 15 条 + 文件名骨架（2026-10-20）

**问题**：模组页一次性构建并插入全部卡片。300+ 模组时，用户点开模组页要先等 jar 扫描（冷缓存顺序读取 300 个 jar 约 4s，8 线程约 180ms）再等整表插入，期间界面无任何反馈。

**改动**：
- `main.py`：`LauncherBridge` 新增 `modsIndex` 信号。`loadMods` 在收集完 jar 列表后、读取任何元数据之前先 emit 一份 `[{filename, enabled}]` 轻量索引；完整列表仍走 `modsLoaded`，前端无需改协议。`_on_mods_index` 注入 `updateModIndex(...)`。
- `ui/index.html`：`renderModList` 改为三段式——
  1. 同步只构建并插入前 `MOD_FIRST_BATCH = 15` 条完整卡片（真实名称、图标、版本号）；
  2. 后续每帧用 `insertAdjacentHTML` 追加一批骨架行（文件名当名称、灰色占位图标、`mod-pending`），单帧预算 `MOD_UPGRADE_BUDGET_MS = 8`；
  3. 追加完毕后再按同一预算逐帧把骨架行 `innerHTML` 换成完整内容，代次计数 `modRenderGen` 保证重渲染时旧帧立即失效。
- 抽出 `modDisplayName` / `modPlaceholderIconHtml` / `modIconHtml(mod, pending)` / `modInnerHtml` / `modItemHtml`，骨架与完整卡片共用同一套 markup，避免两份模板漂移；`.mod-pending` 仅降低名称与图标的不透明度。

**实测**（Playwright + msedge，真实布局与 rAF，300 个模组 @8KB 图标，3 次取中位）：
- 首屏 15 条：**6.3ms**（旧实现 6.7ms，且旧实现必须先构建完 300 条才有第一条进 DOM）
- 全量替换完成：**111ms**（旧 118ms）；600 个模组：299ms（旧 313ms）
- 纯骨架渲染 `updateModIndex`：300 行 **4.4ms**、600 行 9.2ms
- 后端：300 个 jar 元数据（含 4KB 图标）8 线程 **177ms**，顺序 3969ms；索引载荷 **15,490 B**，完整载荷 **1,740,650 B**

**收益**：模组页首次可见时间从「等整轮扫描 + 整表构建」降到「等索引（约 10ms 级）」，冷缓存时差距最大；图标与版本号随后补位，不再阻塞首屏。

**回归**：pytest **403 passed**（+3 `tests/test_mods_index.py`，含真实 bridge 线程链路的信号顺序断言）；node **19** 个文件 **1118 断言 0 失败**（+40 `tests/test_mod_list_phased.js`）；`py_compile` 67 文件；`node --check` 通过。

### 启动/模组页卡顿：插件预加载移出主线程 + 图标压缩（2026-10-21）

**现象**：主窗口出现后整段无响应，点模组页也要顿一下。

**定位**（按 `logs/launcher.log` 相邻日志时间差找主线程空档，日志由调用线程同步写入，间隔即阻塞）：

| 空档 | 位置 | 性质 |
| --- | --- | --- |
| 2753 ms | `plugin.mods-doctor 扫描完成` 之前 | `load_all()` 在 QTimer(0) 回调里同步跑，144 个模组 |
| 201 ms | `modsLoaded` 之前 | 1.18MB 载荷 marshal |
| 1154 ms | `WebChannel 设置完成` | 窗口出现前，启动画面已覆盖 |

**改动**：
- `main.py`：`_startup_load_plugins` 改为 `threading.Thread(name="plugin-preload", daemon=True)` 里跑 `load_all()`，并把调度从 `QTimer.singleShot(0, ...)` 推到 `singleShot(1500, ...)`——先让首帧和版本列表拿到干净的事件循环。跨线程的 `pluginsLoaded` 走 Qt 队列连接回到主线程，页面渲染不变。
- `launcher_core/mod_manager.py`：新增 `_downscale_icon()`，用 QImage 把大于 72px 的图标按比例缩到 72px 再 base64（列表按 36 CSS px 显示，2x 屏也够清晰）；jar 内图标、Modrinth 图标缓存、网络下载三处都过这个函数，MIME 由实际字节头判定。
- `main.py`：`_mod_cache_key` 前缀改 `v2|`，旧缓存里的未压缩大图标自动失效并重建一次（本次 45 个模组 401ms，后台线程完成）。

**实测**（同一套真实模组目录，45 个 jar）：
- 启动后主线程最长空档：**2753 ms → 无**（插件扫描改在 `plugin-preload` 线程，结束后日志 `plugin preload finished`）
- 模组列表载荷：**1,182,839 B → 289,239 B**（其中图标 1,161,732 B → 268,132 B，4.1 倍）
- 冷缓存重建：8 线程扫描 + 缩放 **401 ms**，期间索引已先到、列表照常显示骨架

**回归**：pytest **411 passed**（+3 `tests/test_plugin_preload.py`、+5 `tests/test_mod_icon_downscale.py`）；node 19 文件 **1119 断言**；`py_compile` 69 文件；`node --check` 通过；`tests/test_plugins_ui.js` 的 M7 断言由「singleShot(0) 延后」改为「不得同步 + 至少延后 100ms」。

### 模组页：骨架升级后配色一致 + 再次进入零重建（2026-10-22）

**现象**：模组页里先渲染的前 15 条是白色名称，后补齐的卡片一直偏灰；每次点进模组页仍要卡几下。

**定位**：
- `upgradeModRow` 只用 `node.innerHTML` 换成完整内容，外层 `div` 上的 `mod-pending` class 从未移除，于是已升级的行继续命中 `.mod-item.mod-pending .mod-name { color: var(--text-muted); font-weight: 500 }`。索引骨架走的是「先建、后升级」，所以只有它们灰；前 15 条在构建时就是完整卡片，所以白。
- `switchPage` 每次进入模组页都会用 `lastMods` 调 `renderModList`。旧实现一律整表重建：插入 45 行 → 再逐帧升级，外加图标解码，所以每切一次都连续掉帧。

**改动**：
- `upgradeModRow` 写入内容后同步 `node.className = cls.replace(/\s*mod-pending\b/g, '')`，颜色与字重在升级当帧恢复默认。
- 新增 `modSameList(list, mods)`：children 数量与首末 `data-filename` 一致即认为顺序未变，复用现有节点、只逐帧升级，不再重写 `innerHTML`；若首行已无 `mod-pending`（上次已升级完），直接 return，重复进入页面 DOM 工作量为 0。
- CSS：`.mod-item` 加 `content-visibility: auto; contain-intrinsic-size: auto 62px;`，屏外行不参与布局/绘制；`transition: all 0.2s` 收窄为 `background 0.2s, border-color 0.2s`，升级时不再连颜色和字重一起做过渡。

**实测**（Playwright + msedge，真实 rAF/布局/图片解码；图标 6KB base64）：
- 45 个模组（与真实实例一致）：索引骨架 2.2ms，完整列表调用 5.3ms，全程单帧 **33.5ms**，0 个 longtask
- 300 个模组压测：最大帧 **58.9ms**（原 110.7ms），longtask **0**（原 1 次 53ms）
- 升级完成后首行/末行 computed style 均为 `rgb(238, 238, 238) / 600`，`mod-pending` 残留 0 行
- 再次进入模组页 `renderModList` 耗时 **0ms**，节点与内容完全不重写

**回归**：pytest **411 passed**；node **19 文件 1133 断言 0 失败**（`tests/test_mod_list_phased.js` 40 → 54，新增「升级后无 pending」「复用节点不重建」「滚动保持」「重复进入零 DOM 工作」断言）；`py_compile` 69 文件；`node --check` 通过。

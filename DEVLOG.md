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

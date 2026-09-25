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

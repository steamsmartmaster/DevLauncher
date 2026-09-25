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

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

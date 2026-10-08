# 客户端下载升级为完整实例安装 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILLS: Use mod-agent-developer or 计划执行师 to implement.
> **Testing:** Each task MUST use mod-test-developer for TDD.
> **Review:** After completion, use mod-review-requester for code review.
> **Verification:** Before claiming complete, use mod-completion-verifier.
> **Commits:** 提交动作统一在全部完成、回归门绿后征得用户确认执行（沿用本仓库会话惯例）。

**Goal:** 客户端下载从「只下 jar 到 mods」升级为「自动下载 MC 版本 + 加载器 + jar，装进以客户端名默认命名的隔离实例」，按钮完成后不锁死可重复下载。

**Architecture:** `ModpackImporter.install_client_instance()` 复用整合包导入四件套（原版/版本json/Forge系loader/隔离）；`main.py downloadClientVersion` 编排元数据解析→回退链定 MC→推荐 loader 版本→装实例→下 jar→双信号回执（`modpackImportComplete` 白拿弹窗+刷新+自动选中，`clientDownloadFinished` 清卡片态）；前端选择器 clients 分支带名称输入、导入弹窗进度模式复用、卡片去永久「已下载」。

**Execution Path:** mod-agent-developer（TDD 红→绿）

设计文档：`docs/plans/2026-10-04-client-instance-install-design.md`

---

### Task 1: `resolve_client_mc_version` 回退链纯函数

**Files:**
- Modify: `launcher_core/clients_catalog.py`（`parse_mc_version` 之后追加）
- Test: `tests/test_clients_catalog.py`（追加 2 个用例）

**Step 1 — 写失败测试**（追加到文件末尾）：
```python
def test_strict_and_resolve_client_mc_version():
    # 严格校验：完整 id 形状才算 MC 版本（实例名带数字不误判）
    assert cc.strict_mc_version("1.21.11") == "1.21.11"
    assert cc.strict_mc_version("26.3") == "26.3"
    assert cc.strict_mc_version("26.4-snapshot-2") == "26.4-snapshot-2"
    assert cc.strict_mc_version("Meteor Client 26") == ""
    assert cc.strict_mc_version("My-1.21-Pack") == ""
    assert cc.strict_mc_version("") == ""

def test_resolve_client_mc_version_chain():
    # 条目标注 → 当前选中（严格）→ 最新正式版；全部不可用返回 ""
    assert cc.resolve_client_mc_version(["1.21.11", "26.3"], "26.1", "26.4") == "1.21.11"
    assert cc.resolve_client_mc_version([], "26.3", "26.4") == "26.3"
    assert cc.resolve_client_mc_version([], "Meteor Client", "26.4") == "26.4"
    assert cc.resolve_client_mc_version(["Fabric", "OptiFine"], "", "") == ""
    assert cc.resolve_client_mc_version(["24w14a", "1.21.9"], "", "") == "1.21.9"  # 快照 id 跳过
    assert cc.resolve_client_mc_version([], "", "") == ""
```

**Step 2 — 跑测确认失败**：`python -m pytest tests\test_clients_catalog.py -q` → 2 failed（AttributeError: strict_mc_version）

**Step 3 — 最小实现**（`launcher_core/clients_catalog.py`，`parse_mc_version` 后）：
```python
_STRICT_MC_RE = re.compile(r"^(?:\d+\.\d+(?:\.\d+)?|\d+\.\d+-snapshot(?:-\d+)?)$")


def strict_mc_version(candidate: str) -> str:
    """完整匹配才视为 MC 版本 id；实例名/含杂质字符串返回 ""。"""
    c = (candidate or "").strip()
    return c if _STRICT_MC_RE.match(c) else ""


def resolve_client_mc_version(game_versions, current_version, latest_release="") -> str:
    """客户端实例安装的 MC 版本回退链：条目标注 → 当前选中 → 最新正式版。"""
    for gv in game_versions or []:
        hit = strict_mc_version(gv)
        if hit:
            return hit
    hit = strict_mc_version(current_version or "")
    if hit:
        return hit
    return strict_mc_version(latest_release or "")
```

**Step 4 — 跑测通过**：`python -m pytest tests\test_clients_catalog.py -q` → 14 passed

---

### Task 2: `ModpackImporter.install_client_instance`（四件套复用）

**Files:**
- Modify: `launcher_core/modpack_importer.py`（`_install_loader_for_import` 之后、Singleton 之前）
- Test: `tests/test_client_instance_install.py`（新建）

**Step 1 — 写失败测试**：
```python
"""客户端实例化安装：ModpackImporter.install_client_instance + main.py 编排静态断言"""
import re
from pathlib import Path
import pytest
from launcher_core.modpack_importer import ModpackImporter

ROOT = Path(__file__).resolve().parents[1]


def test_install_client_instance_recipe(tmp_path, monkeypatch):
    imp = ModpackImporter(tmp_path)
    calls = []
    def fake_vanilla(mc, report):
        calls.append(("vanilla", mc)); report(91, 100, "x")
    def fake_json(version_dir, version_name, mc, loader, loader_version):
        calls.append(("json", version_name, mc, loader, loader_version))
        (version_dir / f"{version_name}.json").write_text("{}", encoding="utf-8")
    def fake_loader(version_name, loader, loader_version, report):
        calls.append(("loader", version_name, loader, loader_version)); return "warn-x"
    monkeypatch.setattr(imp, "_ensure_vanilla_version", fake_vanilla)
    monkeypatch.setattr(imp, "_create_version_json", fake_json)
    monkeypatch.setattr(imp, "_install_loader_for_import", fake_loader)

    reports = []
    out = imp.install_client_instance("Meteor Client", "26.3", "fabric", "0.17.2",
                                      lambda c, t, m: reports.append((c, m)))
    # 目录与隔离
    vdir = tmp_path / "versions" / "Meteor Client"
    assert (vdir / "mods").is_dir() and (vdir / "config").is_dir()
    assert (vdir / "Meteor Client.json").is_file()
    # 四件套调用顺序
    assert [c[0] for c in calls] == ["vanilla", "json", "loader"]
    assert calls[0][1] == "26.3"
    assert calls[1] == ("json", "Meteor Client", "26.3", "fabric", "0.17.2")
    assert out == {"version_name": "Meteor Client", "warning": "warn-x"}
    assert reports and reports[0][0] == 91


def test_install_client_instance_idempotent(tmp_path, monkeypatch):
    imp = ModpackImporter(tmp_path)
    monkeypatch.setattr(imp, "_ensure_vanilla_version", lambda mc, r: None)
    monkeypatch.setattr(imp, "_create_version_json", lambda *a: None)
    monkeypatch.setattr(imp, "_install_loader_for_import", lambda *a: "")
    a = imp.install_client_instance("X", "26.3", "fabric", "0.17.2", lambda *a: None)
    b = imp.install_client_instance("X", "26.3", "fabric", "0.17.2", lambda *a: None)
    assert a == b  # 同名重装幂等


def test_install_client_instance_propagates_vanilla_failure(tmp_path, monkeypatch):
    imp = ModpackImporter(tmp_path)
    def boom(mc, report): raise RuntimeError("无法下载原版 Minecraft 9.9.9")
    monkeypatch.setattr(imp, "_ensure_vanilla_version", boom)
    with pytest.raises(RuntimeError, match="9.9.9"):
        imp.install_client_instance("Y", "9.9.9", "fabric", "0.17.2", lambda *a: None)


def test_download_client_version_orchestration_static():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    m = re.search(r"def downloadClientVersion\(self[\s\S]{0,14000}", src)
    assert m, "downloadClientVersion 应存在"
    body = m.group(0)
    for needle in ("install_client_instance(", "resolve_client_mc_version(",
                   "get_recommended_loaders(", "modpackImportComplete.emit",
                   "clientDownloadFinished.emit", "meteor_api.get_jar",
                   "downloadModpackVersion(", "install_client_instance"):
        assert needle in body, f"编排体内应含 {needle}"
    assert "from launcher_core.modpack_importer import" in src or "ModpackImporter(" in src


def test_latest_release_helper_available():
    import minecraft_launcher_lib.utils as mllu
    assert callable(mllu.get_latest_version)
```

**Step 2 — 跑测确认失败**：`python -m pytest tests\test_client_instance_install.py -q` → 4 failed（AttributeError: install_client_instance 等）

**Step 3 — 最小实现**（`launcher_core/modpack_importer.py`，`_install_loader_for_import` 方法之后）：
```python
    def install_client_instance(self, instance_name: str, mc_version: str,
                                loader: str, loader_version: str, report) -> dict:
        """为客户端条目创建隔离实例（复用整合包导入四件套）。

        目录与隔离先建（幂等复用），随后：原版确保 → 版本 JSON → Forge 系合并。
        返回 {"version_name", "warning"}；任一步失败向上抛出。
        """
        version_dir = self.minecraft_dir / "versions" / instance_name
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / "mods").mkdir(exist_ok=True)

        from launcher_core.versions import VersionManager
        VersionManager(str(self.minecraft_dir)).enable_version_isolation(instance_name)

        report(90, 100, f"准备实例 {instance_name}（{mc_version} + {loader}）...")
        self._ensure_vanilla_version(mc_version, report)
        self._create_version_json(version_dir, instance_name, mc_version, loader, loader_version)
        warning = self._install_loader_for_import(instance_name, loader, loader_version, report)
        logger.info(f"客户端实例就绪: {instance_name} (MC {mc_version}, {loader} {loader_version})")
        return {"version_name": instance_name, "warning": warning}
```

**Step 4 — 跑测通过**（静态断言项此时仍失败属预期，本 Task 只看前 3 个 fs 用例绿 + 静态 1 个红转到 Task 3）：先只跑 `test_install_client_instance*` 三个 → passed；全套本文件将在 Task 3 后全绿。

---

### Task 3: main.py `downloadClientVersion` 编排改造

**Files:**
- Modify: `main.py:1386-1483`（downloadClientVersion 全函数体；`downloadClient` 委托签名不动）
- Test: `tests/test_client_instance_install.py`（Task 2 静态断言）

**Step 1 — 确认静态断言为 RED**：`python -m pytest tests\test_client_instance_install.py -q` → `test_download_client_version_orchestration_static` failed

**Step 2 — 实现**，要点（保持六 strategy 直链解析逻辑不动，逐分支补元数据，解析后再走长安装）：
1. 各解析分支同步填 `picked_meta = {"game_versions": [...], "loaders": [...]}`：
   - meteor：`[version_id] if version_id else []` / `["fabric"]`
   - github 直链：`format_github_release_items(get_releases(...))` 按 id 匹配条目的 game_versions；latest：`parse_mc_version(asset["filename"])`
   - modrinth：version 字典的 `game_versions`/`loaders`
   - curseforge：`file_info.get("gameVersions")` + `parse_mc_version(fileName)`
2. 解析后（进实例管线前）：
```python
        candidates = list(picked_meta.get("game_versions") or [])
        mv = clients_catalog.parse_mc_version(filename)
        if mv:
            candidates.append(mv)
        try:
            import minecraft_launcher_lib.utils as mllu
            latest_release = mllu.get_latest_version().get("release", "")
        except Exception:
            latest_release = ""
        mc_version = clients_catalog.resolve_client_mc_version(
            candidates, self._current_mod_version, latest_release)
        if not mc_version:
            raise RuntimeError("无法确定 Minecraft 版本（条目未标注，且当前版本/最新版不可用）")
        loader = next((l for l in picked_meta.get("loaders") or []
                       if l in ("fabric", "forge", "neoforge", "quilt")), "fabric")
        from launcher_core.api_modloaders import get_recommended_loaders
        rec = get_recommended_loaders(mc_version)
        if loader not in rec:
            raise RuntimeError(f"无法获取 {loader} 推荐版本（MC {mc_version}）")
        loader_version = rec[loader].loader_version
        instance_name = (custom_name or "").strip() or entry["name"]
```
3. 进度与安装（替换旧 `client_dest_dir` 落盘段）：
```python
        def report(current, total, message, file_downloaded=0, file_total=0, files=None):
            self.modpackImportProgress.emit(json.dumps({
                "current": current, "total": total, "message": message,
                "file_downloaded": file_downloaded, "file_total": file_total,
                "files": files or []}, ensure_ascii=False))

        report(0, 100, f"正在创建实例 {instance_name}（{mc_version} + {loader}）...")
        minecraft_dir = Path(self.settings.get("minecraft_dir"))
        importer = ModpackImporter(minecraft_dir)
        installed = importer.install_client_instance(
            instance_name, mc_version, loader, loader_version, report)

        report(88, 100, f"正在下载 {filename}...")
        dest = minecraft_dir / "versions" / instance_name / "mods" / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        def dl_cb(p):
            report(int(p * 100), 100, f"正在下载 {filename}...")
        if not modrinth_api.download_file(url, str(dest), callback=dl_cb):
            raise RuntimeError(f"文件下载失败: {url}")

        result = {"success": True, "version_name": instance_name,
                  "downloaded": 1, "total": 1, "errors": []}
        if installed.get("warning"):
            result["warning"] = installed["warning"]
        self.modpackImportComplete.emit(json.dumps(result, ensure_ascii=False))
        self.clientDownloadFinished.emit(json.dumps(
            {"id": client_id, "ok": True,
             "message": f"已安装到实例 {instance_name}（{filename}）"}, ensure_ascii=False))
        self.getVersions()
```
4. except 分支必须**同时**解锁导入弹窗：
```python
    except Exception as e:
        logger.error(f"客户端实例安装失败: {e}", exc_info=True)
        self.modpackImportComplete.emit(json.dumps(
            {"success": False, "error": str(e)}, ensure_ascii=False))
        self.clientDownloadFinished.emit(json.dumps(
            {"id": client_id, "ok": False, "message": str(e)}, ensure_ascii=False))
```
（旧 `_finish` 辅助删除或保留均可，但双信号必须齐；`import minecraft_launcher_lib.utils` 置于函数顶层 try 而非线程内重复）

**Step 3 — 跑测**：`python -m pytest tests\test_client_instance_install.py tests\test_clients_catalog.py -q` → 全 passed；`python -m py_compile main.py` OK

---

### Task 4: 前端 — 导入弹窗进度模式 + 选择器名称输入 + 卡片按钮去锁

**Files:**
- Modify: `ui/index.html`
  - 模态标题 h3（≈2810 行）加 `id="modpackImportTitle"`
  - `closeModpackImportModal()`（≈5378）重置标题为「导入整合包」
  - 新增 `openClientImportDialog(name)`（放 `triggerModpackImport` 旁）
  - `openVersionPicker` clients 分支（5022 附近）：显示名称输入框并默认客户端名
  - `downloadClientWithPicker` clients 回调：并发锁 + 开弹窗 + 传 customName
  - `clientCardHtml`：移除 `downloaded` 永久禁用分支
  - `onClientDownloadFinished`：移除 `clientsDownloaded[res.id] = true`
- Test: `tests/test_clients_ui.js`

**Step 1 — 改测试到期望行为（RED）**：
- `REQUIRED` 数组补 `'openClientImportDialog'`
- `cch` 段加：`check(!/已下载/.test(cch), '卡片不应有永久已下载禁用态')`
- 行为段「选版本流程（客户端）」改断言：
  - 打开后 `elements['versionPickerName'].value === 'Meteor Client'`（默认名）
  - 先设 `elements['versionPickerName'].value = 'MyMeteor'` 再 `pickModVersion` → `downloadClientVersion[0] === ['meteor', '1.21.11', 'MyMeteor']`
  - 确认后 `elements['modpackImportModal'].style.display === 'flex'`、`modpackImportProgress.style.display === 'block'`、`modpackImportCancelBtn.disabled === true`
- 新增行为段「并发锁」：env preamble 补 `var modpackImporting = false;`、`fnNames` 补 `openClientImportDialog`；`env` 暴露 `setImporting: function(v){ modpackImporting = v; }`；`modpackImporting=true` 时 pick → `downloadClientVersion` 仍 0 次且 toast 有「等待」字样
- 「下载完成态」段改：完成后卡片应显示 **「下载」可再点**（`indexOf('已下载') < 0`），downloading 清空，toast 保留
- main.py 静态：`def downloadClientVersion\(self[\s\S]{0,3500}` 窗口扩为 `{0,14000}` 并补 `install_client_instance(` 断言（与 py 测试同步）

**Step 2 — 跑测确认 RED**：`node tests\test_clients_ui.js` → 若干 FAIL（缺 openClientImportDialog / 仍含已下载 / customName 未传）

**Step 3 — 实现前端**：
```js
        function openClientImportDialog(name) {
            document.getElementById('modpackImportModal').style.display = 'flex';
            document.getElementById('modpackImportTitle').textContent = '安装客户端 - ' + name;
            document.getElementById('modpackImportInfo').style.display = 'none';
            document.getElementById('modpackImportResult').style.display = 'none';
            document.getElementById('modpackImportProgress').style.display = 'block';
            document.getElementById('modpackImportConfirmBtn').style.display = 'none';
            var cancelBtn = document.getElementById('modpackImportCancelBtn');
            if (cancelBtn) { cancelBtn.setAttribute('disabled', 'disabled'); cancelBtn.textContent = '导入中...'; }
            modpackImporting = true;
            modpackImportLastFileCount = { downloaded: 0, total: 0 };
            modpackImportLastPct = 0;
        }
```
- `openVersionPicker` 名称输入判定改为：
```js
            if (contentType === 'modpacks') { nameInput.style.display='block'; value=''; placeholder=contentId; }
            else if (contentType === 'clients') {
                nameInput.style.display = 'block';
                var centry = null;
                for (var ci = 0; ci < clientsData.length; ci++) if (clientsData[ci].id === contentId) { centry = clientsData[ci]; break; }
                document.getElementById('versionPickerName').value = centry ? (centry.name || '') : contentId;
                document.getElementById('versionPickerName').placeholder = centry ? (centry.name || contentId) : contentId;
            }
            else { nameInput.style.display = 'none'; }
```
- `downloadClientWithPicker` clients 回调改：
```js
            openVersionPicker(id, 'clients', function(versionId, versionName, customName) {
                if (modpackImporting) { showToast('已有安装任务进行中，请等待完成', 'info'); return; }
                clientsDownloading[id] = true;
                filterClients();
                var cname = (customName || '').trim();
                openClientImportDialog(cname || (entry ? entry.name : id));
                if (pythonInterface && pythonInterface.downloadClientVersion) {
                    pythonInterface.downloadClientVersion(id, versionId || '', cname);
                }
            });
```
- `clientCardHtml` 删除 `downloaded` 分支（只余 打开页面/下载中…/下载）
- `onClientDownloadFinished` 删除 `clientsDownloaded[res.id] = true;`（变量与 getClientsState 保留）

**Step 4 — 跑测通过**：`node tests\test_clients_ui.js` → PASS 0 FAIL

---

### Task 5: 全套回归门 + 集成冒烟

**Step 1**：`python -m pytest tests -q` → 期望 ≥149 passed（144 + 4 py 新用例 + 2 catalog 新用例 −…以实际收集为准，0 failed）
**Step 2**：8 套 JS 全跑 → 0 FAIL（`tests\test_*.js` 循环，PASS 总数以实际为准）
**Step 3**：`python -m py_compile main.py launcher_core\modpack_importer.py launcher_core\clients_catalog.py` + 提取 `<script>` `node --check`
**Step 4 — 集成冒烟（代理，tmp 目录，跳过原版大包下载）**：临时脚本
- monkeypatch `_ensure_vanilla_version`（跳过数 GB 资产），真实执行 `_create_version_json`（Fabric meta + 库下载）、`enable_version_isolation`、单 jar 直链下载进 `versions/<名>/mods`
- 断言：版本 json 存在且 `libraries` 非空、`mainClass` 为 Fabric、mods 下 jar >0 字节、隔离目录齐
- 代理：`$env:HTTP_PROXY/HTTPS_PROXY='http://127.0.0.1:10808'`

**Step 5 — 文档**：`DEVLOG.md` 追加条目；`TESTCHECKLIST.md` §23 追加验收项（默认实例名/回退链/不锁死/弹窗进度/并发锁）

---

### Task 6: 提交（需用户确认后执行）

- `git add` 设计文档 + 计划 + 全部改动；单条信息风格与历史一致
- 提交前跑 `git status`/`git diff` 复核

---

## 验收标准（对照 4 问）

1. 选版本条目（如 BleachHack 1.19.4）→ 装 MC 1.19.4 + Fabric + jar → `versions/BleachHack/` 实例出现且可选中启动
2. 当前选中「Meteor Client」实例（非 MC id）+ 条目未标版本 → 回退 Mojang 最新（26.3），不把实例名当 MC 版本
3. 选择器名称输入框默认 = 客户端名，改名后实例用改后名
4. 完成后卡片按钮回到「下载」，可再次点击重复下载；全程「下载中…」仅临时

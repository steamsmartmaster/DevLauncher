"""LiquidBounce 内置网页下载：catalog 条目 / main.py 槽+窗口+拦截 / 代理 flags"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_liquidbounce_entry_web_download():
    from launcher_core import clients_catalog as cc
    e = cc.get_entry("liquidbounce")
    assert e is not None, "目录应含 liquidbounce 条目"
    assert e["strategy"] == "web_download"
    # #manual 锚点直达 jar 构建列表（页顶是 LiquidLauncher 推广区，见 liquidbounce.net/download HTML）
    assert e["endpoint"] == "https://liquidbounce.net/download#manual"
    assert e["kind"] == "jar" and e["type"] == "client"
    assert e["icon"] and not e["icon"].startswith("http")


def test_tauri_probe_hides_site_chrome():
    """ClientWebWindow 注入 __TAURI__ 探针 → 官网按官方 LiquidLauncher 逻辑隐藏导航/页脚。
    官网仅用该全局做展示切换（root.js），无任何 Tauri API 调用（已核验全部前端包）。
    """
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    m = re.search(r"class ClientWebWindow[\s\S]{0,3000}?(?=\nclass )", src)
    assert m, "ClientWebWindow 类应存在"
    body = m.group(0)
    assert "__TAURI__" in body, "窗口应注入 window.__TAURI__ 探针"
    assert "QWebEngineScript" in body, "应使用 QWebEngineScript 注入"
    assert "DocumentCreation" in body, "应在 DocumentCreation 注入（页面脚本前；Qt 枚举无 DocumentStart）"
    assert "scripts().insert(" in body, "脚本应挂到 profile.scripts()"
    # QWebEngineScript 仅存在这些 setter；setRunOnEveryDocument 属 Qt WebKit(QWebScript)
    # 命名空间，PyQt6 上调用即 AttributeError 崩线程（曾致点下载即崩）
    allowed = {"setName", "setSourceCode", "setInjectionPoint",
               "setWorldId", "setRunsOnSubFrames", "setBaseUrl"}
    called = set(re.findall(r"self\._probe\.(\w+)\(", body))
    assert called <= allowed, f"探针调用了 QWebEngineScript 不存在的 API: {called - allowed}"


def test_main_py_web_download_flow_static():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert re.search(r"@pyqtSlot\(str\)\s+def openClientWebPage\(self, client_id: str\)", src), \
        "应有 openClientWebPage(client_id) 槽"
    assert "class ClientWebWindow" in src, "应有内置网页下载窗口类"
    assert "class ClientWebPage" in src, "应有拦截 .jar 导航的 Page 子类"
    assert "downloadRequested.connect" in src, "应接 profile.downloadRequested 拦截下载"


def test_open_client_web_page_resolves_latest_build():
    """打开 LiquidBounce 网页时后台解析官方构建 API → 切到最新 release 的 queue 页。

    静态 #manual 入口保留为回退（API 失败/超时时窗口仍可用）。
    """
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from launcher_core import api_liquidbounce" in src, "应导入官方构建 API 模块"
    m = re.search(
        r"def openClientWebPage\(self[\s\S]*?(?=\n    def startWebClientDownload)", src)
    assert m, "openClientWebPage 槽应存在"
    body = m.group(0)
    assert "fetch_latest_build" in body, "应拉取最新构建下载页 URL"
    assert "threading.Thread" in body, "网络解析必须在后台线程（阻塞操作不进 UI 线程）"
    assert 'entry["endpoint"]' in body, "静态 endpoint 仍是窗口初始/回退入口"
    w = re.search(r"class ClientWebWindow[\s\S]{0,3500}?(?=\nclass )", src)
    assert w, "ClientWebWindow 类应存在"
    wb = w.group(0)
    assert "navigateTo" in wb, "ClientWebWindow 应有跨线程导航信号"
    assert "pyqtSignal(str)" in wb, "导航信号应为 pyqtSignal(str)"
    assert "navigateTo.connect" in wb, "信号应接到切页槽"
    assert "acceptNavigationRequest" in src, "应覆写 acceptNavigationRequest 拦截直链"
    assert "startWebClientDownload" in src, "应有接管下载入口 startWebClientDownload"
    m = re.search(r"def downloadClientVersion\(self[\s\S]{0,14000}", src)
    assert m, "downloadClientVersion 应存在"
    body = m.group(0)
    assert 'strategy == "web_download"' in body, "下载编排应含 web_download 分支"
    assert "remove_stale_client_mods(" in body, "接管下载同样走 jar 去重"
    idx = src.find("class ClientWebWindow")
    bridge_idx = src.find("class LauncherBridge")
    win_idx = src.find("class MainWindow(QMainWindow)")
    assert bridge_idx < idx < win_idx, "窗口类应位于 LauncherBridge 与 MainWindow 之间"
    assert re.search(r"self\._client_web_win\s*=\s*ClientWebWindow\(", src), \
        "槽内应持有窗口引用防 GC"


def test_js_routes_web_download_to_embedded_window():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"function downloadClientWithPicker\(id\)\s*\{[\s\S]*?\n        \}", html)
    assert m, "downloadClientWithPicker 应存在"
    body = m.group(0)
    assert "entry.strategy === 'web_download'" in body, "应有 web_download 分支"
    assert "openClientWebPage(" in body, "web_download 应开内置网页窗口（非外部浏览器）"
    assert "pythonInterface.openClientWebPage" in html or "openClientWebPage(id)" in body
    open_idx = body.find("entry.strategy === 'open_page'")
    web_idx = body.find("entry.strategy === 'web_download'")
    pack_idx = body.find("entry.type === 'pack'")
    assert 0 < open_idx < web_idx < pack_idx, "分支顺序: open_page → web_download → pack"


def test_webengine_proxy_from_env(monkeypatch):
    from launcher_core import webengine_flags
    from launcher_core.webengine_flags import WEBENGINE_CHROMIUM_FLAGS, merge_chromium_flags
    # 隔离本机 WinINET 系统代理（否则注册表真代理混入 env 断言）
    monkeypatch.setattr(webengine_flags, "_read_system_proxy", lambda: "")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(k, raising=False)
    assert merge_chromium_flags("") == WEBENGINE_CHROMIUM_FLAGS
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10808")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    out = merge_chromium_flags("")
    assert "--proxy-server=http://127.0.0.1:10808" in out, out
    assert "--disable-gpu" in out, out
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:10809")
    out2 = merge_chromium_flags("")
    assert out2.count("--proxy-server") == 1, out2
    assert "--proxy-server=http://127.0.0.1:10808" in out2, "HTTPS_PROXY 优先于 HTTP_PROXY"
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    out3 = merge_chromium_flags("")
    assert "--proxy-server=http://127.0.0.1:10809" in out3, out3
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10808")
    user = "--proxy-server=http://user-proxy:3128"
    out4 = merge_chromium_flags(user)
    assert out4.count("--proxy-server") == 1 and out4.startswith(user), out4


def test_no_external_browser_for_web_download():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    m = re.search(r"def openClientWebPage\(self[\s\S]{0,800}", src)
    assert m, "openClientWebPage 应存在"
    body = m.group(0)
    assert "webbrowser.open" not in body, "内置网页窗口不应走外部浏览器"
    assert "ClientWebWindow" in body

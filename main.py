import sys
import os
import json
import logging
import threading
import shutil
import webbrowser
import queue
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from PyQt6.QtWidgets import QApplication, QMainWindow, QFileDialog
from PyQt6.QtGui import QIcon
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, pyqtSlot, QObject, pyqtSignal, QTimer
from PyQt6.QtWebChannel import QWebChannel

try:
    import minecraft_launcher_lib
except ImportError:
    minecraft_launcher_lib = None
    logger = logging.getLogger("DevLauncher")
    logger.warning("未安装 minecraft-launcher-lib，原版下载功能将不可用")

from launcher_core import AuthManager, VersionManager, GameLauncher, Settings, ModManager, modrinth_api, curseforge_api
from launcher_core.api_modloaders import (
    MOD_LOADER_APIS, LOADER_DISPLAY_NAMES,
    get_available_loaders, get_recommended_loaders, install_mod_loader,
    get_installed_loaders, ModLoaderVersion
)
from launcher_core.modpack_importer import ModpackImporter, ModpackInfo


# === 日志配置 ===
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

class _SafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            super().emit(record)
        except UnicodeEncodeError:
            msg = self.format(record)
            self.stream.write(msg.encode('utf-8', errors='replace').decode('utf-8') + self.terminator)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "launcher.log", encoding='utf-8'),
        _SafeStreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("DevLauncher")


# Azure Application Configuration
CLIENT_ID = "a17ae87e-6f86-44f7-bdfa-6750dfe3acfc"
REDIRECT_URL = "http://localhost:8080"

logger.info(f"启动器启动 | Azure Client ID: {CLIENT_ID[:8]}...")


class ModLoadScheduler:
    """Coalesce rapid mod-list reload requests: one scan at a time, the
    newest pending version chained after the current run finishes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._pending = None

    def submit(self, version_id):
        """Register a load request. True = caller should start the worker."""
        with self._lock:
            self._pending = version_id
            if self._running:
                return False
            self._running = True
            return True

    def complete(self, version_id):
        """Finished loading version_id; return next version or None (idle)."""
        with self._lock:
            pending = self._pending
            if pending is None:
                self._running = False
                return None
            self._pending = None
            if pending != version_id:
                return pending
            self._running = False
            return None


class LauncherBridge(QObject):
    """Bridge between Python and JavaScript"""
    
    # Signals
    versionsLoaded = pyqtSignal(str)
    modsLoaded = pyqtSignal(str)
    worldsLoaded = pyqtSignal(str)
    resourcepacksLoaded = pyqtSignal(str)
    versionIsolationStatus = pyqtSignal(str)
    loginComplete = pyqtSignal(str)
    progressUpdate = pyqtSignal(float, str)
    gameLaunched = pyqtSignal()
    installComplete = pyqtSignal(str)
    settingsLoaded = pyqtSignal(str)
    errorOccurred = pyqtSignal(str)
    backgroundSelected = pyqtSignal(str)
    applyBackground = pyqtSignal(str)
    searchResults = pyqtSignal(str)
    gameStateChanged = pyqtSignal(str, str)  # (state, extra_text)
    gameStarted = pyqtSignal()  # emitted after game process starts, to start monitor on main thread
    modLoaderVersions = pyqtSignal(str)  # JSON list of mod loader versions
    installedLoaders = pyqtSignal(str)  # JSON list of installed loaders for a version
    availableGameVersions = pyqtSignal(str)  # JSON list of game versions for mod filtering
    availableLoaders = pyqtSignal(str)  # JSON list of available loaders
    modVersions = pyqtSignal(str)  # JSON list of mod versions for version picker
    loginStarted = pyqtSignal()  # emitted when login begins (show loading state)
    modpackImportProgress = pyqtSignal(str)  # JSON: {current, total, message, file_downloaded, file_total, files}
    modpackImportComplete = pyqtSignal(str)  # JSON result
    modpackInfoLoaded = pyqtSignal(str)  # JSON modpack info

    def __init__(self, auth: AuthManager, versions: VersionManager, game: GameLauncher, settings: Settings, mods: ModManager):
        super().__init__()
        self.auth = auth
        self.versions = versions
        self.game = game
        self.settings = settings
        self.mods = mods
        self._game_monitor_timer = QTimer()
        self._game_monitor_timer.timeout.connect(self._check_game_process)
        self._current_mod_version = ""
        self._mod_sched = ModLoadScheduler()
        # Thread-safe queue for auth callback from HTTP server
        self._auth_callback_queue = queue.Queue()
        self._auth_callback_timer = QTimer()
        self._auth_callback_timer.timeout.connect(self._poll_auth_callback)
        self._auth_callback_timer.start(100)  # Poll every 100ms
        logger.info("LauncherBridge 初始化完成")

    @pyqtSlot(str)
    def setCurrentVersion(self, version_id: str):
        """Set the current version context for downloads"""
        self._current_mod_version = version_id or ""
        logger.info(f"设置当前版本上下文: {version_id}")

    def _path_to_data_uri(self, path: str) -> str:
        """Convert an image file path to a base64 data URI"""
        import base64
        import mimetypes
        try:
            logger.info(f"开始转换背景: {path}")
            if not os.path.exists(path):
                logger.error(f"背景文件不存在: {path}")
                return ''
            mime, _ = mimetypes.guess_type(path)
            if not mime:
                mime = 'image/png'
            with open(path, 'rb') as f:
                raw = f.read()
            logger.info(f"读取背景文件: {len(raw)} bytes")
            data = base64.b64encode(raw).decode('utf-8')
            uri = f'data:{mime};base64,{data}'
            logger.info(f"背景图片转换完成: URI 长度={len(uri)}")
            return uri
        except Exception as e:
            logger.error(f"转换背景图片失败: {e}", exc_info=True)
            return ''

    def _apply_background(self):
        """Read background setting, convert to data URI, emit signal"""
        bg_path = self.settings.get('background', '')
        logger.info(f"[BG] path='{bg_path}'")
        if not bg_path:
            return
        p = Path(bg_path)
        if not p.exists():
            logger.error(f"[BG] file not found: {bg_path}")
            return
        data_uri = self._path_to_data_uri(bg_path)
        if data_uri:
            logger.info(f"[BG] data URI 长度: {len(data_uri)}")
            self.applyBackground.emit(data_uri)
        else:
            logger.error("[BG] data URI 生成失败")

    @pyqtSlot()
    def getVersions(self):
        """Get list of versions (threaded)"""
        logger.info("获取版本列表...")
        def _do_load():
            try:
                version_list = self.versions.get_version_list()
                installed = self.versions.get_installed_versions()
                logger.info(f"获取到 {len(version_list)} 个版本, 已安装 {len(installed)} 个")
                
                installed_ids = {v["id"] for v in installed}
                
                official_ids = {v['id'] for v in version_list}
                for v in version_list:
                    v['installed'] = v['id'] in installed_ids
                    if 'releaseTime' in v and hasattr(v['releaseTime'], 'isoformat'):
                        v['releaseTime'] = v['releaseTime'].isoformat()
                    elif 'releaseTime' in v:
                        v['releaseTime'] = str(v['releaseTime'])
                
                for v in installed:
                    if v['id'] not in official_ids:
                        v['installed'] = True
                        v['type'] = v.get('type', 'unknown')
                        v['releaseTime'] = v.get('releaseTime', '')
                        version_list.append(v)
                
                json_data = json.dumps(version_list)
                self.versionsLoaded.emit(json_data)
            except Exception as e:
                logger.error(f"获取版本列表失败: {e}", exc_info=True)
                self.errorOccurred.emit(str(e))
        threading.Thread(target=_do_load, daemon=True).start()

    @pyqtSlot(result=str)
    def getInstalledVersions(self):
        """Get list of installed versions"""
        installed = self.versions.get_installed_versions()
        logger.info(f"已安装版本: {installed}")
        return json.dumps(installed)

    @pyqtSlot(result=str)
    def getSettings(self):
        """Get current settings"""
        logger.info("获取设置")
        settings_data = {
            'max_memory': self.settings.get('max_memory'),
            'min_memory': self.settings.get('min_memory'),
            'minecraft_dir': self.settings.get('minecraft_dir'),
            'java_path': self.settings.get('java_path', ''),
            'show_snapshots': self.settings.get('show_snapshots', True),
            'show_old': self.settings.get('show_old', False),
            'theme_primary': self.settings.get('theme_primary', '#ffffff'),
            'theme_gradient_start': self.settings.get('theme_gradient_start', '#ffffff'),
            'theme_gradient_end': self.settings.get('theme_gradient_end', '#888888')
        }
        logger.debug(f"设置: max_memory={settings_data['max_memory']}")
        result = json.dumps(settings_data)
        self.settingsLoaded.emit(result)
        return result

    @pyqtSlot()
    def _poll_auth_callback(self):
        """Poll for auth callback from HTTP server thread"""
        try:
            callback_url = self._auth_callback_queue.get_nowait()
            logger.info(f"收到登录回调: {callback_url[:50]}...")
            self.handleAuthCallback(callback_url)
        except queue.Empty:
            pass

    @pyqtSlot()
    def startLogin(self):
        """Start Microsoft login flow"""
        logger.info("开始 Microsoft 登录流程")
        try:
            if not CLIENT_ID:
                logger.warning("Client ID 未配置")
                self.errorOccurred.emit("请先配置 Azure Client ID")
                return

            url, state, code_verifier = self.auth.get_login_url()
            logger.info(f"登录 URL 已生成: {url[:50]}...")

            # Start local HTTP server to receive OAuth callback
            auth_queue = self._auth_callback_queue
            class CallbackHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    query = parse_qs(urlparse(self.path).query)
                    if 'code' in query:
                        callback_url = f"http://localhost:8080{self.path}"
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/html; charset=utf-8')
                        self.end_headers()
                        self.wfile.write('登录成功！请返回启动器。'.encode('utf-8'))
                        # Put callback URL into thread-safe queue
                        auth_queue.put(callback_url)
                    else:
                        self.send_response(400)
                        self.send_header('Content-Type', 'text/html; charset=utf-8')
                        self.end_headers()
                        self.wfile.write('登录失败：未收到授权码。'.encode('utf-8'))
                def log_message(self, format, *args):
                    pass

            server = HTTPServer(('localhost', 8080), CallbackHandler)
            logger.info("回调服务器已启动，监听 localhost:8080")

            def run_server():
                try:
                    server.handle_request()
                except Exception as e:
                    logger.error(f"回调服务器错误: {e}")
                finally:
                    try:
                        server.server_close()
                    except Exception:
                        pass

            threading.Thread(target=run_server, daemon=True).start()
            webbrowser.open(url)
            logger.info("已打开浏览器进行登录")
        except OSError as e:
            if 'address already in use' in str(e).lower() or e.errno == 10048:
                logger.error(f"端口 8080 被占用: {e}")
                self.errorOccurred.emit("端口 8080 被占用，请关闭占用该端口的程序后重试")
            else:
                logger.error(f"启动登录失败: {e}", exc_info=True)
                self.errorOccurred.emit(str(e))
        except Exception as e:
            logger.error(f"启动登录失败: {e}", exc_info=True)
            self.errorOccurred.emit(str(e))
        except Exception as e:
            logger.error(f"启动登录失败: {e}", exc_info=True)
            self.errorOccurred.emit(str(e))

    @pyqtSlot(str)
    def handleAuthCallback(self, callback_url: str):
        """Handle auth callback URL"""
        logger.info(f"处理登录回调: {callback_url[:50]}...")
        try:
            auth_code = self.auth.parse_auth_code(callback_url)
            logger.info("Auth code 解析成功")
        except Exception as e:
            logger.error(f"解析 auth code 失败: {e}", exc_info=True)
            self.errorOccurred.emit(str(e))
            return

        # Emit loginStarted to show loading state, then run complete_login in background thread
        self.loginStarted.emit()

        def do_login():
            try:
                login_data = self.auth.complete_login(auth_code)
                logger.info(f"登录成功: {login_data['name']}")
                self.loginComplete.emit(json.dumps({
                    'name': login_data['name'],
                    'id': login_data['id'],
                    'isOffline': False
                }))
            except Exception as e:
                logger.error(f"登录失败: {e}", exc_info=True)
                self.errorOccurred.emit(str(e))

        threading.Thread(target=do_login, daemon=True).start()

    @pyqtSlot(str)
    def offlineLogin(self, username: str):
        """Login with offline mode"""
        logger.info(f"离线登录: {username}")
        try:
            login_data = self.auth.offline_login(username)
            logger.info(f"离线登录成功: {login_data['name']}")
            self.loginComplete.emit(json.dumps({
                'name': login_data['name'],
                'id': login_data['id'],
                'isOffline': True
            }))
        except Exception as e:
            logger.error(f"离线登录失败: {e}", exc_info=True)
            self.errorOccurred.emit(str(e))

    @pyqtSlot()
    def logout(self):
        """Logout user"""
        logger.info("用户登出")
        self.auth.logout()

    @pyqtSlot(str)
    def launchGame(self, version_id: str):
        """Launch Minecraft game"""
        logger.info(f"启动游戏: {version_id}")
        def _launch():
            try:
                login_data = self.auth.get_login_data()
                if not login_data:
                    logger.warning("用户未登录")
                    self.gameStateChanged.emit("error", "请先登录")
                    self.errorOccurred.emit("请先登录")
                    return
                
                self.gameStateChanged.emit("launching", f"正在启动 {version_id}...")
                
                logger.info(f"准备启动 - 用户: {login_data['name']}, 版本: {version_id}")
                success, message = self.game.launch(
                    version_id,
                    login_data['name'],
                    login_data['id'],
                    login_data['access_token'],
                    max_memory=self.settings.get('max_memory'),
                    min_memory=self.settings.get('min_memory')
                )
                
                if success:
                    logger.info("游戏启动成功")
                    self.gameStateChanged.emit("running", "游戏运行中")
                    self.gameLaunched.emit()
                    self.gameStarted.emit()  # start monitor on main thread
                else:
                    logger.error(f"游戏启动失败: {message}")
                    self.gameStateChanged.emit("error", message)
                    self.errorOccurred.emit(message)
            except Exception as e:
                logger.error(f"启动游戏异常: {e}", exc_info=True)
                self.gameStateChanged.emit("error", str(e))
                self.errorOccurred.emit(str(e))
        
        threading.Thread(target=_launch, daemon=True).start()

    @pyqtSlot()
    def killGame(self):
        """Kill the running game process"""
        logger.info("终止游戏进程")
        if self.game.kill():
            self._game_monitor_timer.stop()
            self.gameStateChanged.emit("idle", "")
        else:
            self.errorOccurred.emit("没有正在运行的游戏")

    def _start_game_monitor(self):
        """Start monitoring game process (poll every 1 second). Must be called from main thread."""
        logger.info("启动游戏进程监控")
        if self._game_monitor_timer.isActive():
            self._game_monitor_timer.stop()
        self._game_monitor_timer.start(1000)

    def _check_game_process(self):
        """Check if game process has exited"""
        running = self.game.is_running()
        logger.debug(f"游戏进程检查: running={running}")
        if not running:
            self._game_monitor_timer.stop()
            exit_code = self.game.get_exit_code()
            logger.info(f"游戏进程已退出, 退出码: {exit_code}")
            self.gameStateChanged.emit("idle", "")

    @pyqtSlot(str)
    def installVersion(self, version_id: str):
        """Install a Minecraft version"""
        logger.info(f"安装版本: {version_id}")
        def _install():
            file_count = [0]
            current_file = [""]

            def on_status(status):
                file_count[0] += 1
                current_file[0] = status
                logger.info(f"安装状态 [{file_count[0]}]: {status}")
                # Show file count as progress indicator
                self.progressUpdate.emit(-1, f"[{file_count[0]}] {status}")

            try:
                self.gameStateChanged.emit("installing", f"正在安装 {version_id}...")
                self.versions.install_version(version_id, callback={
                    "setStatus": on_status,
                })
                logger.info(f"版本安装完成: {version_id} (共下载 {file_count[0]} 个文件)")
                # Mark user-initiated installs as user-managed (devlauncher.cfg)
                # so they stay visible in the version list; auto-downloaded
                # modpack parent versions have no cfg and stay hidden.
                v_path = self.versions.get_version_path(version_id)
                if v_path and not (v_path / "devlauncher.cfg").exists():
                    self.versions.get_version_setting(version_id).set("isolation", False)
                self.gameStateChanged.emit("idle", "")
                self.installComplete.emit(version_id)
            except Exception as e:
                logger.error(f"安装版本失败: {e}", exc_info=True)
                self.gameStateChanged.emit("error", str(e))
                self.errorOccurred.emit(str(e))
        
        threading.Thread(target=_install, daemon=True).start()

    @pyqtSlot(str)
    def saveSettings(self, settings_json: str):
        """Save settings"""
        logger.info(f"保存设置: {settings_json[:100]}...")
        try:
            settings = json.loads(settings_json)
            for key, value in settings.items():
                self.settings.set(key, value)
            logger.info("设置保存成功")
        except Exception as e:
            logger.error(f"保存设置失败: {e}", exc_info=True)
            self.errorOccurred.emit(str(e))

    @pyqtSlot()
    def selectBackground(self):
        """Open file dialog to select background image"""
        logger.info("选择背景图片")
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "选择背景图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if file_path:
            logger.info(f"背景图片已选择: {file_path}")
            self.settings.set('background', file_path)
            QTimer.singleShot(100, lambda: self.bridge._apply_background())
            self.backgroundSelected.emit(file_path)

    @pyqtSlot()
    def selectJavaPath(self):
        """Open file dialog to select Java executable"""
        logger.info("选择 Java 路径")
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "选择 Java 可执行文件",
            "",
            "Java 可执行文件 (java.exe;java;javaw.exe)"
        )
        if file_path:
            logger.info(f"Java 路径已选择: {file_path}")
            self.settings.set('java_path', file_path)
            # Send updated settings to JS
            settings_data = self.settings._settings.copy()
            settings_data["background"] = settings_data.get("background", "")
            QTimer.singleShot(100, lambda: self.settingsLoaded.emit(json.dumps(settings_data)))

    @pyqtSlot()
    def selectMinecraftDir(self):
        """Open directory dialog to select .minecraft directory"""
        logger.info("选择 .minecraft 目录")
        dir_path = QFileDialog.getExistingDirectory(
            None,
            "选择 .minecraft 目录",
            self.settings.get('minecraft_dir', '')
        )
        if dir_path:
            logger.info(f".minecraft 目录已选择: {dir_path}")
            old_dir = self.settings.get('minecraft_dir', '')
            self.settings.set('minecraft_dir', dir_path)
            
            # Reinitialize components with new directory
            self.versions = VersionManager(dir_path)
            self.game = GameLauncher(dir_path)
            self.mods = ModManager(dir_path)
            
            self.settingsLoaded.emit(json.dumps(self.settings._settings))

    @pyqtSlot()
    def migrateMinecraftDir(self):
        """Migrate .minecraft data from current to new directory"""
        import shutil
        old_dir = Path.home() / ".minecraft"
        new_dir = Path(self.settings.get('minecraft_dir', ''))
        
        if not new_dir.exists():
            logger.error(f"目标目录不存在: {new_dir}")
            self.errorOccurred.emit(f"目标目录不存在: {new_dir}")
            return
        
        if old_dir.resolve() == new_dir.resolve():
            logger.info("源目录和目标目录相同，无需迁移")
            self.errorOccurred.emit("源目录和目标目录相同，无需迁移")
            return
        
        if not old_dir.exists():
            logger.error(f"源目录不存在: {old_dir}")
            self.errorOccurred.emit(f"源目录不存在: {old_dir}")
            return
        
        logger.info(f"开始迁移: {old_dir} -> {new_dir}")
        
        # Items to migrate
        migrate_items = ['versions', 'libraries', 'assets', 'logs', 'saves', 'resourcepacks', 'mods', 'config', 'shaderpacks']
        
        migrated = []
        for item in migrate_items:
            src = old_dir / item
            dst = new_dir / item
            if src.exists() and not dst.exists():
                try:
                    shutil.copytree(src, dst)
                    migrated.append(item)
                    logger.info(f"已迁移: {item}")
                except Exception as e:
                    logger.error(f"迁移 {item} 失败: {e}")
            elif dst.exists():
                logger.info(f"跳过已存在: {item}")
        
        # Migrate root files (options.txt, etc.)
        for f in old_dir.glob('*.txt'):
            dst = new_dir / f.name
            if not dst.exists():
                try:
                    shutil.copy2(f, dst)
                    migrated.append(f.name)
                except Exception as e:
                    logger.error(f"迁移 {f.name} 失败: {e}")
        
        if migrated:
            self.errorOccurred.emit(f"迁移完成: {', '.join(migrated)}")
        else:
            self.errorOccurred.emit("无需迁移或所有文件已存在")
        
        logger.info("迁移完成")

    @pyqtSlot(str)
    def log(self, message: str):
        """接收 JS 日志"""
        logger.info(f"[JS] {message}")

    @pyqtSlot(str, str)
    def loadTrendingContent(self, content_type: str, source: str = "modrinth"):
        """Load trending/popular content from Modrinth or CurseForge"""
        logger.info(f"加载热门内容: {content_type}, 来源: {source}")
        def _do_load():
            try:
                formatted = []
                if source == "curseforge":
                    # CurseForge search
                    if content_type == "mods":
                        results = curseforge_api.search_mods(query="")
                    elif content_type == "modpacks":
                        results = curseforge_api.search_modpacks(query="")
                    elif content_type == "worlds":
                        results = curseforge_api.search_worlds(query="")
                    elif content_type == "datapacks":
                        results = curseforge_api.search_datapacks(query="")
                    else:
                        results = {"hits": [], "total_hits": 0}
                    
                    for hit in results.get("hits", []):
                        # Get icon URL from CurseForge
                        icon_url = ""
                        if hit.get("logo"):
                            icon_url = hit["logo"].get("thumbnailUrl", "")
                        
                        formatted.append({
                            "id": str(hit.get("id", "")),
                            "title": hit.get("name", ""),
                            "description": hit.get("summary", ""),
                            "downloads": hit.get("downloadCount", 0),
                            "icon_url": icon_url,
                            "author": hit.get("authors", [{}])[0].get("name", "") if hit.get("authors") else "",
                            "date_modified": hit.get("dateModified", ""),
                            "versions": [],
                            "loaders": [],
                            "project_type": content_type,
                            "source": "curseforge"
                        })
                else:
                    # Modrinth search
                    results = modrinth_api.search(
                        query="",
                        project_type=content_type,
                        index="downloads",
                        limit=20
                    )
                    for hit in results.get("hits", []):
                        # Get icon URL, fallback to constructed URL if empty
                        icon_url = hit.get("icon_url", "")
                        project_id = hit.get("project_id", "")
                        if not icon_url and project_id:
                            icon_url = f"https://cdn.modrinth.com/data/{project_id}/icon.png"
                        elif not icon_url:
                            slug = hit.get("slug", "")
                            if slug:
                                icon_url = f"https://cdn.modrinth.com/data/{slug}/icon.png"
                        
                        formatted.append({
                            "id": hit.get("slug") or project_id,
                            "title": hit.get("title", ""),
                            "description": hit.get("description", ""),
                            "downloads": hit.get("downloads", 0),
                            "icon_url": icon_url,
                            "author": hit.get("author", ""),
                            "date_modified": hit.get("date_modified", ""),
                            "versions": hit.get("versions", []),
                            "loaders": hit.get("loaders", []),
                            "project_type": hit.get("project_type", ""),
                            "source": "modrinth"
                        })
                
                result_json = json.dumps({
                    "hits": formatted,
                    "total_hits": results.get("total_hits", 0),
                    "isTrending": True,
                    "source": source
                })
                logger.info(f"热门{content_type} ({source}): {len(formatted)} 个")
                self.searchResults.emit(result_json)
            except Exception as e:
                logger.error(f"加载热门{content_type}失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"加载热门内容失败: {e}")
        threading.Thread(target=_do_load, daemon=True).start()

    @pyqtSlot()
    def loadTrendingMods(self):
        """Load trending/popular mods from Modrinth"""
        self.loadTrendingContent("mods", "modrinth")

    @pyqtSlot()
    def selectModpackFile(self):
        """Open file dialog to select a modpack file"""
        from PyQt6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            None, "选择整合包文件", "",
            "整合包文件 (*.zip *.mrpack);;所有文件 (*)"
        )
        if file_path:
            logger.info(f"选择整合包文件: {file_path}")
            if hasattr(self, 'main_window') and self.main_window:
                self.main_window.web_view.page().runJavaScript(
                    f"onModpackFileSelectedFromPython('{file_path.replace(chr(92), '/')}')"
                )

    @pyqtSlot(str)
    def getModpackInfo(self, zip_path: str):
        """Get modpack info from ZIP file (threaded)"""
        logger.info(f"获取整合包信息: {zip_path}")
        def _do_load():
            try:
                importer = ModpackImporter(self.versions.minecraft_dir)
                info = importer.read_manifest(zip_path)
                if info:
                    info_json = json.dumps({
                        'name': info.name,
                        'version': info.version,
                        'author': info.author,
                        'description': info.description,
                        'minecraft_version': info.minecraft_version,
                        'mod_loader': info.mod_loader,
                        'mod_loader_version': info.mod_loader_version,
                        'mod_count': info.mod_count,
                        'format': info.format
                    })
                    self.modpackInfoLoaded.emit(info_json)
                else:
                    self.errorOccurred.emit("无法读取整合包信息")
            except Exception as e:
                logger.error(f"获取整合包信息失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"获取整合包信息失败: {e}")
        threading.Thread(target=_do_load, daemon=True).start()

    @pyqtSlot(str, str)
    def importModpack(self, zip_path: str, version_name: str):
        """Import modpack from ZIP file (threaded)"""
        logger.info(f"导入整合包: {zip_path}, 版本名: {version_name}")
        def _do_import():
            try:
                importer = ModpackImporter(self.versions.minecraft_dir)
                
                def progress_callback(current, total, message, file_downloaded=0, file_total=0, file_states=None):
                    detail = json.dumps({
                        "current": current, "total": total, "message": message,
                        "file_downloaded": file_downloaded, "file_total": file_total,
                        "files": file_states or []
                    })
                    self.modpackImportProgress.emit(detail)
                
                result = importer.import_modpack(zip_path, version_name, progress_callback)
                self.modpackImportComplete.emit(json.dumps(result))
                
                # Refresh versions list if successful
                if result.get('success'):
                    self.getVersions()
                    imported_version = result.get('version_name', version_name)
                    if imported_version:
                        self.loadMods(imported_version)
                self.gameStateChanged.emit("idle", "")
            except Exception as e:
                logger.error(f"导入整合包失败: {e}", exc_info=True)
                # Always complete so the modal never gets stuck in "importing" state
                self.modpackImportComplete.emit(json.dumps({
                    'success': False, 'error': str(e)
                }))
                self.gameStateChanged.emit("idle", "")
                self.errorOccurred.emit(f"导入整合包失败: {e}")
        threading.Thread(target=_do_import, daemon=True).start()

    @pyqtSlot(str)
    def redownloadModpackMods(self, version_id: str):
        """Re-download mods for an existing modpack version (threaded)"""
        logger.info(f"重新下载整合包模组: {version_id}")
        def _do_redownload():
            try:
                importer = ModpackImporter(self.versions.minecraft_dir)

                def progress_callback(current, total, message, file_downloaded=0, file_total=0, file_states=None):
                    detail = json.dumps({
                        "current": current, "total": total, "message": message,
                        "file_downloaded": file_downloaded, "file_total": file_total,
                        "files": file_states or []
                    })
                    self.modpackImportProgress.emit(detail)
                    # Also drive the sidebar download panel (modal may be closed)
                    button_detail = json.dumps({
                        "message": message,
                        "button_text": "正在下载整合包模组",
                        "file_downloaded": file_downloaded,
                        "file_total": file_total,
                        "files": file_states or []
                    })
                    self.gameStateChanged.emit("installing", button_detail)

                result = importer.redownload_modpack_mods(version_id, progress_callback)
                self.gameStateChanged.emit("idle", "")
                if result.get('success'):
                    logger.info(f"整合包模组下载完成: {result.get('downloaded', 0)}/{result.get('total', 0)}")
                    # Reload mods list
                    self.loadMods(version_id)
                else:
                    err = result.get('error') or '; '.join(result.get('errors', [])[:3]) or '未知错误'
                    self.errorOccurred.emit(f"下载整合包模组失败: {err}")
            except Exception as e:
                logger.error(f"重新下载整合包模组失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"重新下载整合包模组失败: {e}")
        threading.Thread(target=_do_redownload, daemon=True).start()

    @pyqtSlot(str, str, str, str)
    def downloadModpackVersion(self, project_id: str, version_id: str, source: str, custom_name: str = ""):
        """Download a modpack version from Modrinth/CurseForge, auto-install, then delete zip"""
        logger.info(f"下载整合包: project_id='{project_id}', version_id='{version_id}', source='{source}'")
        def _do_download():
            try:
                minecraft_dir = Path(self.settings.get("minecraft_dir"))
                modpacks_dir = minecraft_dir / "modpacks"
                modpacks_dir.mkdir(parents=True, exist_ok=True)

                if source == "modrinth":
                    # Get project info for name
                    project_info = modrinth_api.get_project(project_id)
                    project_name = project_info.get("title", project_id) if project_info else project_id
                    
                    versions = modrinth_api.get_project_versions(project_id)
                    target = next((v for v in versions if v.get("id") == version_id), versions[0] if versions else None)
                    if not target:
                        self.errorOccurred.emit("找不到指定版本")
                        return
                    files = target.get("files", [])
                    if not files:
                        self.errorOccurred.emit("没有找到可下载文件")
                        return
                    file_info = files[0]
                    download_url = file_info.get("url")
                    filename = file_info.get("filename", "modpack.zip")
                    # Default name: project name + version name
                    version_name_hint = f"{project_name} {target.get('name', '')}".strip()
                elif source == "curseforge":
                    cf_id = int(project_id)
                    cf_file_id = int(version_id)
                    file_data = curseforge_api.get_mod_file(cf_id, cf_file_id)
                    if not file_data:
                        self.errorOccurred.emit("找不到指定文件")
                        return
                    download_url = file_data.get("downloadUrl")
                    filename = file_data.get("fileName", "modpack.zip")
                    # Get project name for CurseForge
                    cf_project = curseforge_api.get_mod(cf_id)
                    cf_name = cf_project.get("name", project_id) if cf_project else project_id
                    version_name_hint = f"{cf_name} {file_data.get('displayName', '')}".strip()
                else:
                    self.errorOccurred.emit("不支持的来源")
                    return

                # Use custom name if provided, otherwise use the hint
                if custom_name:
                    version_name_hint = custom_name

                if not download_url:
                    self.errorOccurred.emit("下载链接无效")
                    return

                dest_path = modpacks_dir / filename

                def progress_callback(progress):
                    self.progressUpdate.emit(progress * 100, f"正在下载整合包 {filename}...")

                self.gameStateChanged.emit("installing", f"正在下载整合包 {filename}...")
                success = (modrinth_api if source == "modrinth" else curseforge_api).download_file(
                    download_url, str(dest_path), callback=progress_callback
                )
                if not success:
                    self.gameStateChanged.emit("idle", "")
                    self.errorOccurred.emit("下载失败")
                    return

                # Auto-install the modpack
                self.gameStateChanged.emit("installing", "正在安装整合包...")
                importer = ModpackImporter(minecraft_dir)

                def import_progress(current, total, message, file_downloaded=0, file_total=0, file_states=None):
                    detail = json.dumps({
                        "current": current, "total": total, "message": message,
                        "file_downloaded": file_downloaded, "file_total": file_total,
                        "files": file_states or []
                    })
                    self.modpackImportProgress.emit(detail)
                    # Also send for HMCL-style launch button UI
                    button_detail = json.dumps({
                        "message": message,
                        "button_text": f"正在下载 {version_name_hint}",
                        "file_downloaded": file_downloaded,
                        "file_total": file_total,
                        "files": file_states or []
                    })
                    self.gameStateChanged.emit("installing", button_detail)

                result = importer.import_modpack(str(dest_path), version_name_hint, import_progress)
                self.modpackImportComplete.emit(json.dumps(result))

                # Delete the downloaded zip after successful install
                if result.get("success"):
                    try:
                        dest_path.unlink()
                        logger.info(f"已删除整合包安装包: {dest_path}")
                    except Exception as e:
                        logger.warning(f"删除整合包安装包失败: {e}")

                self.getVersions()
                # Auto-load mods for the imported version
                imported_version = result.get('version_name', version_name_hint)
                if imported_version:
                    self.loadMods(imported_version)
                self.gameStateChanged.emit("idle", "")

            except Exception as e:
                logger.error(f"下载整合包失败: {e}", exc_info=True)
                self.gameStateChanged.emit("idle", "")
                self.errorOccurred.emit(f"下载整合包失败: {e}")
        threading.Thread(target=_do_download, daemon=True).start()

    @pyqtSlot(str, str)
    def searchContent(self, query: str, content_type: str):
        """Search for content on Modrinth/CurseForge"""
        self.searchContentFiltered(query, content_type, "", "", "modrinth")

    @pyqtSlot(str, str, str, str, str)
    def searchContentFiltered(self, query: str, content_type: str, game_version: str, loader: str, source: str = "modrinth"):
        """Search for content (threaded)"""
        logger.info(f"搜索内容: query='{query}', type='{content_type}', source='{source}'")
        def _do_search():
            try:
                formatted = []
                if source == "curseforge":
                    # CurseForge search
                    if content_type == "mods":
                        results = curseforge_api.search_mods(query=query, game_version=game_version if game_version else None)
                    elif content_type == "modpacks":
                        results = curseforge_api.search_modpacks(query=query, game_version=game_version if game_version else None)
                    elif content_type == "worlds":
                        results = curseforge_api.search_worlds(query=query, game_version=game_version if game_version else None)
                    elif content_type == "datapacks":
                        results = curseforge_api.search_datapacks(query=query, game_version=game_version if game_version else None)
                    else:
                        results = {"hits": [], "total_hits": 0}
                    
                    for hit in results.get("hits", []):
                        icon_url = ""
                        if hit.get("logo"):
                            icon_url = hit["logo"].get("thumbnailUrl", "")
                        
                        formatted.append({
                            "id": str(hit.get("id", "")),
                            "title": hit.get("name", ""),
                            "description": hit.get("summary", ""),
                            "downloads": hit.get("downloadCount", 0),
                            "icon_url": icon_url,
                            "author": hit.get("authors", [{}])[0].get("name", "") if hit.get("authors") else "",
                            "date_modified": hit.get("dateModified", ""),
                            "versions": [],
                            "loaders": [],
                            "project_type": content_type,
                            "source": "curseforge"
                        })
                else:
                    # Modrinth search
                    results = modrinth_api.search(
                        query=query,
                        project_type=content_type,
                        limit=20
                    )
                    for hit in results.get("hits", []):
                        # Get icon URL, fallback to constructed URL if empty
                        icon_url = hit.get("icon_url", "")
                        project_id = hit.get("project_id", "")
                        if not icon_url and project_id:
                            icon_url = f"https://cdn.modrinth.com/data/{project_id}/icon.png"
                        elif not icon_url:
                            slug = hit.get("slug", "")
                            if slug:
                                icon_url = f"https://cdn.modrinth.com/data/{slug}/icon.png"
                        
                        formatted.append({
                            "id": hit.get("slug") or project_id,
                            "title": hit.get("title", ""),
                            "description": hit.get("description", ""),
                            "downloads": hit.get("downloads", 0),
                            "icon_url": icon_url,
                            "author": hit.get("author", ""),
                            "date_modified": hit.get("date_modified", ""),
                            "versions": hit.get("versions", []),
                            "loaders": hit.get("loaders", []),
                            "project_type": hit.get("project_type", ""),
                            "source": "modrinth"
                        })
                
                result_json = json.dumps({
                    "hits": formatted,
                    "total_hits": results.get("total_hits", 0),
                    "source": source
                })
                logger.info(f"搜索结果 ({source}): {len(formatted)} 个")
                self.searchResults.emit(result_json)
            except Exception as e:
                logger.error(f"搜索失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"搜索失败: {e}")
        threading.Thread(target=_do_search, daemon=True).start()

    @pyqtSlot(str, str)
    def downloadContent(self, content_id: str, content_type: str):
        """Download content from Modrinth"""
        logger.info(f"下载内容: id='{content_id}', type='{content_type}'")
        def _do_download():
            try:
                versions = modrinth_api.get_project_versions(content_id)
                if not versions:
                    self.errorOccurred.emit("没有找到可用版本")
                    return
                
                version = versions[0]
                files = version.get("files", [])
                if not files:
                    self.errorOccurred.emit("没有找到可下载文件")
                    return
                
                file_info = files[0]
                download_url = file_info.get("url")
                filename = file_info.get("filename", "download.jar")
                
                if not download_url:
                    self.errorOccurred.emit("下载链接无效")
                    return
                
                minecraft_dir = Path(self.settings.get("minecraft_dir"))
                if content_type == "modpacks":
                    dest_dir = minecraft_dir / "modpacks"
                elif content_type == "mods":
                    dest_dir = minecraft_dir / "mods"
                elif content_type == "datapacks":
                    dest_dir = minecraft_dir / "datapacks"
                else:
                    dest_dir = minecraft_dir / "downloads"
                
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / filename
                
                def progress_callback(progress):
                    self.progressUpdate.emit(progress * 100, f"正在下载 {filename}...")
                
                self.gameStateChanged.emit("installing", f"正在下载 {filename}...")
                success = modrinth_api.download_file(
                    download_url,
                    str(dest_path),
                    callback=progress_callback
                )
            
                if success:
                    self.gameStateChanged.emit("idle", "")
                    self.installComplete.emit(filename)
                else:
                    self.gameStateChanged.emit("idle", "")
                    self.errorOccurred.emit("下载失败")
                    
            except Exception as e:
                logger.error(f"下载失败: {e}", exc_info=True)
                self.gameStateChanged.emit("idle", "")
                self.errorOccurred.emit(f"下载失败: {e}")
        threading.Thread(target=_do_download, daemon=True).start()

    @pyqtSlot(str)
    def getModLoaderVersions(self, game_version: str):
        """Get available mod loader versions for a game version (background thread)"""
        logger.info(f"获取模组加载器版本: input={game_version}")
        def _fetch():
            try:
                resolved_version = game_version
                if not self.versions.is_valid_game_version(game_version):
                    json_path = self.versions.get_version_json_path(game_version)
                    logger.info(f"解析版本: {game_version} -> JSON路径: {json_path}, 存在: {os.path.exists(json_path)}")
                    if os.path.exists(json_path):
                        with open(json_path, "r", encoding="utf-8") as f:
                            vd = json.load(f)
                        resolved_version = vd.get("id", game_version)
                        logger.info(f"JSON id: {resolved_version}, 有效: {self.versions.is_valid_game_version(resolved_version)}")
                        if not self.versions.is_valid_game_version(resolved_version):
                            resolved_version = vd.get("inheritsFrom", vd.get("clientVersion", game_version))
                            logger.info(f"回退到 inheritsFrom/clientVersion: {resolved_version}")
                    else:
                        logger.warning(f"版本JSON不存在: {json_path}")
                logger.info(f"最终解析版本: {game_version} -> {resolved_version}")
                result = get_available_loaders(resolved_version)
                output = {}
                for loader_type, versions in result.items():
                    output[loader_type] = [v.to_dict() for v in versions]
                self.modLoaderVersions.emit(json.dumps(output))
            except Exception as e:
                logger.error(f"获取模组加载器版本失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"获取模组加载器版本失败: {e}")
        threading.Thread(target=_fetch, daemon=True).start()

    @pyqtSlot(str)
    def getRecommendedLoaders(self, game_version: str):
        """Get recommended (latest) mod loader versions (background thread)"""
        logger.info(f"获取推荐模组加载器: MC {game_version}")
        def _fetch():
            try:
                resolved_version = game_version
                if not self.versions.is_valid_game_version(game_version):
                    json_path = self.versions.get_version_json_path(game_version)
                    if os.path.exists(json_path):
                        with open(json_path, "r", encoding="utf-8") as f:
                            vd = json.load(f)
                        resolved_version = vd.get("id", game_version)
                        if not self.versions.is_valid_game_version(resolved_version):
                            resolved_version = vd.get("inheritsFrom", vd.get("clientVersion", game_version))
                logger.info(f"推荐加载器解析: {game_version} -> {resolved_version}")
                result = get_recommended_loaders(resolved_version)
                output = {k: v.to_dict() for k, v in result.items()}
                self.modLoaderVersions.emit(json.dumps({"recommended": output}))
            except Exception as e:
                logger.error(f"获取推荐模组加载器失败: {e}", exc_info=True)
        threading.Thread(target=_fetch, daemon=True).start()

    @pyqtSlot(str, str, str, str, str)
    def installModLoader(self, game_version: str, loader_type: str, loader_version: str,
                         installer_url: str = "", custom_name: str = ""):
        """Install a mod loader onto a version.
        game_version is installed directly (modpack JSONs merge in place; the
        APIs resolve the real MC version via inheritsFrom when they need it).
        If custom_name is provided, rename the version after install."""
        logger.info(f"安装模组加载器: {loader_type} {loader_version} -> {game_version}, url={installer_url[:60] if installer_url else 'N/A'}, custom_name={custom_name}")
        def _install():
            def on_status(status):
                self.progressUpdate.emit(-1, status)

            try:
                self.gameStateChanged.emit("installing", f"正在安装 {LOADER_DISPLAY_NAMES.get(loader_type, loader_type)}...")
                success = install_mod_loader(
                    loader_type, game_version, loader_version,
                    self.settings.get("minecraft_dir"),
                    callback={"setStatus": on_status},
                    installer_url=installer_url
                )
                if success:
                    # Rename version if custom name was provided
                    if custom_name and custom_name != game_version:
                        logger.info(f"重命名版本: {game_version} -> {custom_name}")
                        rename_ok = self.versions.rename_version(game_version, custom_name)
                        if rename_ok:
                            logger.info(f"版本已重命名为: {custom_name}")
                            self.installComplete.emit(custom_name)
                        else:
                            logger.warning(f"重命名失败，使用原名称: {game_version}")
                            self.installComplete.emit(game_version)
                    else:
                        self.installComplete.emit(game_version)
                    self.gameStateChanged.emit("idle", "")
                else:
                    self.gameStateChanged.emit("error", "安装失败")
                    self.errorOccurred.emit(f"{LOADER_DISPLAY_NAMES.get(loader_type, loader_type)} 安装失败")
            except Exception as e:
                logger.error(f"安装模组加载器失败: {e}", exc_info=True)
                self.gameStateChanged.emit("error", str(e))
                self.errorOccurred.emit(f"安装失败: {e}")

        threading.Thread(target=_install, daemon=True).start()

    @pyqtSlot(str, str)
    def removeModLoader(self, version_id: str, loader_type: str):
        """Remove a mod loader from a version"""
        logger.info(f"移除模组加载器: {loader_type} <- {version_id}")
        try:
            success = self.versions.remove_mod_loader(version_id, loader_type)
            if success:
                self.installComplete.emit(f"已移除 {loader_type}")
            else:
                self.errorOccurred.emit(f"移除 {loader_type} 失败")
        except Exception as e:
            logger.error(f"移除模组加载器失败: {e}", exc_info=True)
            self.errorOccurred.emit(f"移除失败: {e}")

    @pyqtSlot(str)
    def getInstalledLoaders(self, version_id: str):
        """Get installed mod loaders for a version"""
        logger.info(f"检测已安装模组加载器: {version_id}")
        try:
            loaders = self.versions.get_installed_loaders(version_id)
            self.installedLoaders.emit(json.dumps({"version_id": version_id, "loaders": loaders}))
        except Exception as e:
            logger.error(f"检测模组加载器失败: {e}", exc_info=True)
            self.installedLoaders.emit(json.dumps({"version_id": version_id, "loaders": []}))

    @pyqtSlot(str, str)
    def getModVersions(self, content_id: str, game_version: str):
        """Get all versions for a mod/modpack (no server-side filter, show all)"""
        logger.info(f"获取模组版本: {content_id}, MC {game_version}")
        def _do_fetch():
            try:
                versions = modrinth_api.get_project_versions(content_id)
                formatted = []
                for v in versions:
                    files = v.get("files", [])
                    primary_file = files[0] if files else {}
                    formatted.append({
                        "id": v.get("id", ""),
                        "name": v.get("name", ""),
                        "version_number": v.get("version_number", ""),
                        "game_versions": v.get("game_versions", []),
                        "loaders": v.get("loaders", []),
                        "date_published": v.get("date_published", ""),
                        "downloads": v.get("downloads", 0),
                        "filename": primary_file.get("filename", ""),
                        "url": primary_file.get("url", ""),
                        "featured": v.get("featured", False),
                    })
                self.modVersions.emit(json.dumps({"content_id": content_id, "versions": formatted}))
            except Exception as e:
                logger.error(f"获取模组版本失败: {e}", exc_info=True)
                self.modVersions.emit(json.dumps({"content_id": content_id, "versions": []}))
        threading.Thread(target=_do_fetch, daemon=True).start()

    @pyqtSlot(str, str)
    def getModpackVersions(self, content_id: str, source: str):
        """Get all versions for a modpack from Modrinth or CurseForge"""
        logger.info(f"获取整合包版本: {content_id}, source={source}")
        def _do_fetch():
            try:
                formatted = []
                if source == "curseforge":
                    cf_id = int(content_id)
                    files = curseforge_api.get_mod_files(cf_id)
                    for f in files:
                        formatted.append({
                            "id": str(f.get("id", "")),
                            "name": f.get("displayName", f.get("fileName", "")),
                            "version_number": f.get("displayName", ""),
                            "game_versions": f.get("gameVersions", []),
                            "loaders": [],
                            "date_published": f.get("fileDate", ""),
                            "downloads": f.get("downloadCount", 0),
                            "filename": f.get("fileName", ""),
                            "url": f.get("downloadUrl", ""),
                            "featured": f.get("isFeatured", False),
                        })
                else:
                    versions = modrinth_api.get_project_versions(content_id)
                    for v in versions:
                        files = v.get("files", [])
                        primary_file = files[0] if files else {}
                        formatted.append({
                            "id": v.get("id", ""),
                            "name": v.get("name", ""),
                            "version_number": v.get("version_number", ""),
                            "game_versions": v.get("game_versions", []),
                            "loaders": v.get("loaders", []),
                            "date_published": v.get("date_published", ""),
                            "downloads": v.get("downloads", 0),
                            "filename": primary_file.get("filename", ""),
                            "url": primary_file.get("url", ""),
                            "featured": v.get("featured", False),
                        })
                self.modVersions.emit(json.dumps({"content_id": content_id, "versions": formatted}))
            except Exception as e:
                logger.error(f"获取整合包版本失败: {e}", exc_info=True)
                self.modVersions.emit(json.dumps({"content_id": content_id, "versions": []}))
        threading.Thread(target=_do_fetch, daemon=True).start()

    @pyqtSlot(str, str)
    def downloadModVersion(self, content_id: str, version_id: str):
        """Download a specific version of a mod"""
        logger.info(f"下载指定版本: {content_id}, version {version_id}")
        def _do_download():
            try:
                version = modrinth_api.get_version(version_id)
                if not version:
                    self.errorOccurred.emit("版本不存在")
                    return

                files = version.get("files", [])
                if not files:
                    self.errorOccurred.emit("没有可下载文件")
                    return

                file_info = files[0]
                download_url = file_info.get("url")
                filename = file_info.get("filename", "download.jar")

                if not download_url:
                    self.errorOccurred.emit("下载链接无效")
                    return

                minecraft_dir = Path(self.settings.get("minecraft_dir"))
                if self._current_mod_version and self.versions.is_version_isolated(self._current_mod_version):
                    dest_dir = self.versions.get_mods_path(self._current_mod_version)
                    logger.info(f"版本隔离已启用，模组保存到版本目录: {dest_dir}")
                else:
                    dest_dir = minecraft_dir / "mods"
                    logger.info(f"模组保存到全局mods目录: {dest_dir} (current_mod_version='{self._current_mod_version}')")
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / filename

                def progress_callback(progress):
                    self.progressUpdate.emit(progress * 100, f"正在下载 {filename}...")

                self.gameStateChanged.emit("installing", f"正在下载 {filename}...")
                success = modrinth_api.download_file(download_url, str(dest_path), callback=progress_callback)

                if success:
                    self.gameStateChanged.emit("idle", "")
                    self.installComplete.emit(filename)
                else:
                    self.gameStateChanged.emit("idle", "")
                    self.errorOccurred.emit("下载失败")
            except Exception as e:
                logger.error(f"下载失败: {e}", exc_info=True)
                self.gameStateChanged.emit("idle", "")
                self.errorOccurred.emit(f"下载失败: {e}")
        threading.Thread(target=_do_download, daemon=True).start()

    @pyqtSlot(str)
    def downloadVanillaVersion(self, version_id: str):
        """Download vanilla Minecraft version"""
        logger.info(f"下载原版: {version_id}")
        def _do_download():
            try:
                self.gameStateChanged.emit("installing", f"正在下载 Minecraft {version_id}...")
                
                minecraft_dir = self.settings.get("minecraft_dir")
                
                def status_callback(status):
                    if hasattr(status, 'get'):
                        msg = status.get("status", "")
                        if msg == "Downloading":
                            filename = status.get("file", {}).get("filename", "")
                            if filename:
                                self.gameStateChanged.emit("installing", f"正在下载 {filename}")
                        elif msg == "Extracting":
                            self.gameStateChanged.emit("installing", "正在解压文件...")
                
                minecraft_launcher_lib.install.install_minecraft_version(
                    version_id,
                    minecraft_dir,
                    callback={"setStatus": status_callback}
                )
                
                self.gameStateChanged.emit("idle", "")
                self.getVersions()
                logger.info(f"Minecraft {version_id} 下载完成")
            except Exception as e:
                logger.error(f"下载原版失败: {e}", exc_info=True)
                self.gameStateChanged.emit("idle", "")
                self.errorOccurred.emit(f"下载失败: {e}")
        threading.Thread(target=_do_download, daemon=True).start()

    @pyqtSlot(str, str, str, str)
    def downloadContentFiltered(self, content_id: str, content_type: str,
                                 game_version: str = "", loader: str = ""):
        """Download content with version/loader filtering"""
        logger.info(f"下载内容(过滤): id='{content_id}', type='{content_type}', ver='{game_version}', loader='{loader}'")
        def _do_download():
            try:
                versions_list = [game_version] if game_version else None
                loaders_list = [loader] if loader else None

                versions = modrinth_api.get_project_versions(
                    content_id,
                    loaders=loaders_list,
                    game_versions=versions_list
                )
                if not versions:
                    versions = modrinth_api.get_project_versions(content_id)

                if not versions:
                    self.errorOccurred.emit("没有找到可用版本")
                    return

                featured = [v for v in versions if v.get("featured", False)]
                version = featured[0] if featured else versions[0]

                files = version.get("files", [])
                if not files:
                    self.errorOccurred.emit("没有找到可下载文件")
                    return

                file_info = files[0]
                download_url = file_info.get("url")
                filename = file_info.get("filename", "download.jar")

                if not download_url:
                    self.errorOccurred.emit("下载链接无效")
                    return

                minecraft_dir = Path(self.settings.get("minecraft_dir"))
                if content_type == "modpacks":
                    dest_dir = minecraft_dir / "modpacks"
                elif content_type == "mods":
                    if self._current_mod_version and self.versions.is_version_isolated(self._current_mod_version):
                        dest_dir = self.versions.get_mods_path(self._current_mod_version)
                    else:
                        dest_dir = minecraft_dir / "mods"
                elif content_type == "datapacks":
                    dest_dir = minecraft_dir / "datapacks"
                else:
                    dest_dir = minecraft_dir / "downloads"

                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / filename

                def progress_callback(progress):
                    self.progressUpdate.emit(progress * 100, f"正在下载 {filename}...")

                self.gameStateChanged.emit("installing", f"正在下载 {filename}...")
                success = modrinth_api.download_file(download_url, str(dest_path), callback=progress_callback)

                if success:
                    self.gameStateChanged.emit("idle", "")
                    self.installComplete.emit(filename)
                else:
                    self.gameStateChanged.emit("idle", "")
                    self.errorOccurred.emit("下载失败")
            except Exception as e:
                logger.error(f"下载失败: {e}", exc_info=True)
                self.gameStateChanged.emit("idle", "")
                self.errorOccurred.emit(f"下载失败: {e}")
        threading.Thread(target=_do_download, daemon=True).start()

    @pyqtSlot(str, result=bool)
    def isVersionInstalled(self, version_id: str) -> bool:
        """Check if a version directory exists"""
        return self.versions.is_version_installed(version_id)

    @pyqtSlot(str, str)
    def renameVersion(self, old_id: str, new_id: str):
        """Rename a Minecraft version"""
        logger.info(f"重命名版本: {old_id} -> {new_id}")
        try:
            success = self.versions.rename_version(old_id, new_id)
            if success:
                self.errorOccurred.emit(f"版本已重命名: {old_id} -> {new_id}")
                self.refresh_versions()
            else:
                self.errorOccurred.emit("重命名失败")
        except Exception as e:
            logger.error(f"重命名版本失败: {e}", exc_info=True)
            self.errorOccurred.emit(f"重命名失败: {e}")

    @pyqtSlot(str)
    def deleteVersion(self, version_id: str):
        """Delete a Minecraft version"""
        logger.info(f"删除版本: {version_id}")
        try:
            success = self.versions.delete_version(version_id)
            if success:
                self.errorOccurred.emit(f"版本已删除: {version_id}")
                self.refresh_versions()
            else:
                self.errorOccurred.emit("删除失败")
        except Exception as e:
            logger.error(f"删除版本失败: {e}", exc_info=True)
            self.errorOccurred.emit(f"删除失败: {e}")

    @pyqtSlot(str, str)
    def duplicateVersion(self, src_id: str, dst_id: str):
        """Duplicate a Minecraft version"""
        logger.info(f"复制版本: {src_id} -> {dst_id}")
        try:
            success = self.versions.duplicate_version(src_id, dst_id)
            if success:
                self.errorOccurred.emit(f"版本已复制: {src_id} -> {dst_id}")
                self.refresh_versions()
            else:
                self.errorOccurred.emit("复制失败")
        except Exception as e:
            logger.error(f"复制版本失败: {e}", exc_info=True)
            self.errorOccurred.emit(f"复制失败: {e}")

    @pyqtSlot(str)
    def getVersionSettings(self, version_id: str):
        """Get settings for a version"""
        logger.info(f"获取版本设置: {version_id}")
        try:
            setting = self.versions.get_version_setting(version_id)
            result = json.dumps(setting.to_dict())
            self.settingsLoaded.emit(result)
        except Exception as e:
            logger.error(f"获取版本设置失败: {e}", exc_info=True)

    @pyqtSlot(str, str)
    def setVersionSetting(self, version_id: str, key: str, value: str):
        """Set a version setting"""
        logger.info(f"设置版本设置: {version_id}, {key}={value}")
        try:
            setting = self.versions.get_version_setting(version_id)
            # Parse value based on type
            if value.lower() in ('true', 'false'):
                parsed = value.lower() == 'true'
            elif value.isdigit():
                parsed = int(value)
            else:
                try:
                    parsed = float(value)
                except ValueError:
                    parsed = value
            setting.set(key, parsed)
        except Exception as e:
            logger.error(f"设置版本设置失败: {e}", exc_info=True)

    @pyqtSlot(str)
    def enableVersionIsolation(self, version_id: str):
        """Enable version isolation"""
        logger.info(f"启用版本隔离: {version_id}")
        try:
            success = self.versions.enable_version_isolation(version_id)
            if success:
                self.errorOccurred.emit(f"版本隔离已启用: {version_id}")
            else:
                self.errorOccurred.emit("启用版本隔离失败")
        except Exception as e:
            logger.error(f"启用版本隔离失败: {e}", exc_info=True)
            self.errorOccurred.emit(f"启用版本隔离失败: {e}")

    @pyqtSlot(str)
    def disableVersionIsolation(self, version_id: str):
        """Disable version isolation"""
        logger.info(f"禁用版本隔离: {version_id}")
        try:
            success = self.versions.disable_version_isolation(version_id)
            if success:
                self.errorOccurred.emit(f"版本隔离已禁用: {version_id}")
            else:
                self.errorOccurred.emit("禁用版本隔离失败")
        except Exception as e:
            logger.error(f"禁用版本隔离失败: {e}", exc_info=True)
            self.errorOccurred.emit(f"禁用版本隔离失败: {e}")

    @pyqtSlot(str)
    def getVersionIsolationStatus(self, version_id: str):
        """Get version isolation status"""
        try:
            is_isolated = self.versions.is_version_isolated(version_id)
            result = json.dumps({"version_id": version_id, "isolation": is_isolated})
            self.versionIsolationStatus.emit(result)
        except Exception as e:
            logger.error(f"获取版本隔离状态失败: {e}", exc_info=True)

    def refresh_versions(self):
        """Refresh and send version list to JS"""
        installed = self.versions.get_installed_versions()
        version_list = self.versions.get_version_list()
        
        # Mark installed versions and convert releaseTime to string
        installed_ids = {v["id"] for v in installed}
        official_ids = {v['id'] for v in version_list}
        for v in version_list:
            v["installed"] = v["id"] in installed_ids
            # Convert releaseTime to string if it's a datetime object
            if hasattr(v.get("releaseTime"), "isoformat"):
                v["releaseTime"] = v["releaseTime"].isoformat()
        
        # Add installed versions that might not be in remote list
        for v in installed:
            if v["id"] not in official_ids:
                version_list.insert(0, {
                    "id": v["id"],
                    "type": v.get("type", "unknown"),
                    "releaseTime": str(v.get("releaseTime", "")),
                    "installed": True
                })
        
        result = json.dumps(version_list)
        self.versionsLoaded.emit(result)

    @staticmethod
    def _mod_cache_key(jar: Path):
        """Cache key strips `.disabled` so enable/disable keeps the hit
        (a rename would otherwise force jar re-extract + Modrinth icon fetch)."""
        try:
            name = jar.name
            if name.endswith(".disabled"):
                name = name[:-len(".disabled")]
            st = jar.stat()
            return f"{name}|{st.st_size}|{int(st.st_mtime)}"
        except OSError:
            return None

    @staticmethod
    def _cached_mod_entry(jar: Path, cache: dict):
        """Cache entry for jar, with `enabled` refreshed from current filename
        (cached dicts store a stale `enabled` from build time)."""
        key = LauncherBridge._mod_cache_key(jar)
        if not key:
            return None
        entry = cache.get(key)
        if not isinstance(entry, dict):
            return None
        entry = dict(entry)
        entry["enabled"] = not jar.name.endswith(".disabled")
        return entry

    @pyqtSlot(str)
    def loadMods(self, version_id: str):
        """Load and send mod list to JS (threaded, coalesced)"""
        logger.info(f"加载模组列表: {version_id}")
        self._current_mod_version = version_id or ""
        if not self._mod_sched.submit(version_id):
            return  # a scan is already running; it will chain this request
        def _do_load(current_id: str):
            try:
                mods_path = self.versions.get_mods_path(current_id) if current_id else Path(self.settings.get("minecraft_dir")) / "mods"
                mods = []
                jar_files = []
                if mods_path.exists():
                    # Collect all jar files (including in subdirectories)
                    for item in mods_path.iterdir():
                        if item.is_file() and (item.suffix == ".jar" or item.suffix == ".disabled"):
                            jar_files.append(item)
                        elif item.is_dir():
                            for sub_item in item.iterdir():
                                if sub_item.is_file() and sub_item.suffix == ".jar":
                                    jar_files.append(sub_item)
                
                # Also scan .fabric/processedMods for Fabric modpacks
                if not jar_files and current_id:
                    fabric_mods = Path(self.settings.get("minecraft_dir")) / "versions" / current_id / ".fabric" / "processedMods"
                    if fabric_mods.exists():
                        for item in fabric_mods.iterdir():
                            if item.is_file() and item.suffix == ".jar":
                                jar_files.append(item)
                
                # Use ModInfo to extract metadata (parallel + persistent cache,
                # because each jar is unzipped twice: metadata + icon)
                from launcher_core.mod_manager import ModInfo
                from concurrent.futures import ThreadPoolExecutor, as_completed

                cache_path = mods_path / "modcache.json"
                cache = {}
                try:
                    if cache_path.exists():
                        with open(cache_path, "r", encoding="utf-8") as f:
                            cache = json.load(f)
                except Exception:
                    cache = {}

                def _build(jar: Path):
                    return jar, ModInfo(str(jar)).to_dict()

                keys = [self._mod_cache_key(j) for j in jar_files]
                mods = [None] * len(jar_files)
                missing = []
                for i in range(len(jar_files)):
                    entry = self._cached_mod_entry(jar_files[i], cache)
                    if entry is not None:
                        mods[i] = entry
                    else:
                        missing.append(i)

                if missing:
                    with ThreadPoolExecutor(max_workers=8) as ex:
                        futs = {ex.submit(_build, jar_files[i]): i for i in missing}
                        for fut in as_completed(futs):
                            i = futs[fut]
                            try:
                                _jar, data = fut.result()
                                mods[i] = data
                            except Exception as e:
                                logger.warning(f"读取模组失败 {jar_files[i].name}: {e}")

                # Persist cache (only current files, so it never grows stale)
                if missing:
                    try:
                        rebuilt = {}
                        for i, m in enumerate(mods):
                            if m and keys[i]:
                                rebuilt[keys[i]] = m
                        if rebuilt:
                            with open(cache_path, "w", encoding="utf-8") as f:
                                json.dump(rebuilt, f, ensure_ascii=False)
                    except Exception as e:
                        logger.debug(f"写入模组缓存失败: {e}")

                mods = [m for m in mods if m]
                result = json.dumps(mods)
                self.modsLoaded.emit(result)
            except Exception as e:
                logger.error(f"加载模组列表失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"加载模组列表失败: {e}")
        def _worker():
            current = version_id
            while current is not None:
                _do_load(current)
                current = self._mod_sched.complete(current)
        threading.Thread(target=_worker, daemon=True).start()

    @pyqtSlot(str)
    def enableMod(self, filename: str):
        """Enable a mod (threaded: file ops must not block the GUI thread)"""
        logger.info(f"启用模组: {filename}")
        def _do():
            try:
                mods_dir = self.versions.get_mods_path(self._current_mod_version) if self._current_mod_version else None
                success = self.mods.enable_mod(filename, mods_dir=mods_dir)
                if success:
                    self.loadMods(self._current_mod_version)
                else:
                    self.errorOccurred.emit("启用模组失败")
            except Exception as e:
                logger.error(f"启用模组失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"启用模组失败: {e}")
        threading.Thread(target=_do, daemon=True).start()

    @pyqtSlot(str)
    def disableMod(self, filename: str):
        """Disable a mod (threaded: file ops must not block the GUI thread)"""
        logger.info(f"禁用模组: {filename}")
        def _do():
            try:
                mods_dir = self.versions.get_mods_path(self._current_mod_version) if self._current_mod_version else None
                success = self.mods.disable_mod(filename, mods_dir=mods_dir)
                if success:
                    self.loadMods(self._current_mod_version)
                else:
                    self.errorOccurred.emit("禁用模组失败")
            except Exception as e:
                logger.error(f"禁用模组失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"禁用模组失败: {e}")
        threading.Thread(target=_do, daemon=True).start()

    @pyqtSlot(str)
    def deleteMod(self, filename: str):
        """Delete a mod (threaded: file ops must not block the GUI thread)"""
        logger.info(f"删除模组: {filename}")
        def _do():
            try:
                mods_dir = self.versions.get_mods_path(self._current_mod_version) if self._current_mod_version else None
                success = self.mods.delete_mod(filename, mods_dir=mods_dir)
                if success:
                    self.loadMods(self._current_mod_version)
                else:
                    self.errorOccurred.emit("删除模组失败")
            except Exception as e:
                logger.error(f"删除模组失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"删除模组失败: {e}")
        threading.Thread(target=_do, daemon=True).start()

    @pyqtSlot(str)
    def loadWorlds(self, version_id: str):
        """Load and send world list to JS (threaded)"""
        logger.info(f"加载世界列表: {version_id}")
        def _do_load():
            try:
                worlds = []
                if version_id:
                    saves_path = self.versions.get_saves_path(version_id)
                    if saves_path.exists():
                        for item in saves_path.iterdir():
                            if item.is_dir():
                                level_dat = item / "level.dat"
                                if level_dat.exists():
                                    worlds.append({
                                        "name": item.name,
                                        "folder": item.name
                                    })
                result = json.dumps(worlds)
                self.worldsLoaded.emit(result)
            except Exception as e:
                logger.error(f"加载世界列表失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"加载世界列表失败: {e}")
        threading.Thread(target=_do_load, daemon=True).start()

    @pyqtSlot(str, str)
    def deleteWorld(self, version_id: str, folder: str):
        """Delete a world (threaded: rmtree can be slow)"""
        logger.info(f"删除世界: {folder} (版本: {version_id})")
        def _do():
            try:
                if version_id:
                    saves_path = self.versions.get_saves_path(version_id)
                    world_path = saves_path / folder
                    if world_path.exists():
                        import shutil
                        shutil.rmtree(world_path)
                        self.loadWorlds(version_id)
                    else:
                        self.errorOccurred.emit("世界不存在")
                else:
                    self.errorOccurred.emit("请先选择版本")
            except Exception as e:
                logger.error(f"删除世界失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"删除世界失败: {e}")
        threading.Thread(target=_do, daemon=True).start()

    @pyqtSlot(str)
    def loadResourcepacks(self, version_id: str):
        """Load and send resourcepacks list to JS (threaded)"""
        logger.info(f"加载资源包列表: {version_id}")
        def _do_load():
            try:
                resourcepacks = []
                if version_id:
                    rp_path = self.versions.get_resourcepacks_path(version_id)
                    if rp_path.exists():
                        for item in rp_path.iterdir():
                            if item.is_file() and (item.suffix == ".zip" or item.suffix == ".jar"):
                                resourcepacks.append({
                                    "name": item.stem,
                                    "filename": item.name
                                })
                result = json.dumps(resourcepacks)
                self.resourcepacksLoaded.emit(result)
            except Exception as e:
                logger.error(f"加载资源包列表失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"加载资源包列表失败: {e}")
        threading.Thread(target=_do_load, daemon=True).start()

    @pyqtSlot(str, str)
    def deleteResourcepack(self, version_id: str, filename: str):
        """Delete a resourcepack (threaded: file ops must not block the GUI)"""
        logger.info(f"删除资源包: {filename} (版本: {version_id})")
        def _do():
            try:
                if version_id:
                    rp_path = self.versions.get_resourcepacks_path(version_id)
                    rp_file = rp_path / filename
                    if rp_file.exists():
                        rp_file.unlink()
                        self.loadResourcepacks(version_id)
                    else:
                        self.errorOccurred.emit("资源包不存在")
                else:
                    self.errorOccurred.emit("请先选择版本")
            except Exception as e:
                logger.error(f"删除资源包失败: {e}", exc_info=True)
                self.errorOccurred.emit(f"删除资源包失败: {e}")
        threading.Thread(target=_do, daemon=True).start()

    @pyqtSlot()
    def checkLoginStatus(self):
        """Check and send login status to JS"""
        login_data = self.auth.get_login_data()
        if login_data:
            is_offline = login_data.get('access_token') == 'offline_token'
            logger.info(f"检查登录状态: {login_data['name']} (离线: {is_offline})")
            self.loginComplete.emit(json.dumps({
                'name': login_data['name'],
                'id': login_data['id'],
                'isOffline': is_offline
            }))
        else:
            logger.info("无登录数据")


class MainWindow(QMainWindow):
    """Main launcher window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DevLauncher")
        self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), "ui", "icon.svg")))
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)
        logger.info("MainWindow 初始化")
        
        # Initialize core components
        self.settings = Settings()
        logger.info(f"Minecraft 目录: {self.settings.get('minecraft_dir')}")
        
        auth = AuthManager(CLIENT_ID, REDIRECT_URL)
        versions = VersionManager(self.settings.get('minecraft_dir'))
        game = GameLauncher(self.settings.get('minecraft_dir'))
        mods = ModManager(self.settings.get('minecraft_dir'))
        
        # Create bridge
        self.bridge = LauncherBridge(auth, versions, game, self.settings, mods)
        
        # Setup web view
        self.web_view = QWebEngineView()
        self.setCentralWidget(self.web_view)
        self.bridge.main_window = self
        
        # Enable loading external images from file:// origin
        settings = self.web_view.settings()
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        
        # Setup web channel
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        logger.info("WebChannel 设置完成")
        
        # Load UI
        ui_path = Path(__file__).parent / "ui" / "index.html"
        logger.info(f"加载 UI: {ui_path}")
        self.web_view.setUrl(QUrl.fromLocalFile(str(ui_path.absolute())))
        
        # Connect signals (bridge is initialized by HTML via QWebChannel)
        self.bridge.versionsLoaded.connect(self._on_versions_loaded)
        self.bridge.modsLoaded.connect(self._on_mods_loaded)
        self.bridge.worldsLoaded.connect(self._on_worlds_loaded)
        self.bridge.resourcepacksLoaded.connect(self._on_resourcepacks_loaded)
        self.bridge.versionIsolationStatus.connect(self._on_version_isolation_status)
        self.bridge.loginComplete.connect(self._on_login_complete)
        self.bridge.loginStarted.connect(self._on_login_started)
        self.bridge.progressUpdate.connect(self._on_progress_update)
        self.bridge.gameLaunched.connect(self._on_game_launched)
        self.bridge.installComplete.connect(self._on_install_complete)
        self.bridge.settingsLoaded.connect(self._on_settings_loaded)
        self.bridge.errorOccurred.connect(self._on_error)
        self.bridge.backgroundSelected.connect(self._on_background_selected)
        self.bridge.applyBackground.connect(self._on_apply_background)
        self.bridge.searchResults.connect(self._on_search_results)
        self.bridge.gameStateChanged.connect(self._on_game_state_changed)
        self.bridge.gameStarted.connect(self.bridge._start_game_monitor)
        self.bridge.modLoaderVersions.connect(self._on_mod_loader_versions)
        self.bridge.installedLoaders.connect(self._on_installed_loaders)
        self.bridge.modVersions.connect(self._on_mod_versions)
        self.bridge.modpackImportProgress.connect(self._on_modpack_import_progress)
        self.bridge.modpackImportComplete.connect(self._on_modpack_import_complete)
        self.bridge.modpackInfoLoaded.connect(self._on_modpack_info_loaded)
        
        # Login status will be checked after JS bridge is ready (via HTML callback)
        logger.info("MainWindow 初始化完成")

    def _on_versions_loaded(self, versions_json: str):
        logger.info(f"信号: versionsLoaded (长度: {len(versions_json)})")
        self.web_view.page().runJavaScript(
            f"updateVersionList({versions_json})"
        )

    def _on_mods_loaded(self, mods_json: str):
        logger.info(f"信号: modsLoaded (长度: {len(mods_json)})")
        self.web_view.page().runJavaScript(
            f"updateModList({mods_json})"
        )

    def _on_worlds_loaded(self, worlds_json: str):
        logger.info(f"信号: worldsLoaded (长度: {len(worlds_json)})")
        self.web_view.page().runJavaScript(
            f"updateWorldsList({worlds_json})"
        )

    def _on_resourcepacks_loaded(self, resourcepacks_json: str):
        logger.info(f"信号: resourcepacksLoaded (长度: {len(resourcepacks_json)})")
        self.web_view.page().runJavaScript(
            f"updateResourcepacksList({resourcepacks_json})"
        )

    def _on_version_isolation_status(self, status_json: str):
        logger.info(f"信号: versionIsolationStatus - {status_json[:100]}")
        self.web_view.page().runJavaScript(
            f"updateVersionIsolationStatus({status_json})"
        )

    def _on_login_complete(self, login_json: str):
        logger.info(f"信号: loginComplete - {login_json[:100]}")
        self.web_view.page().runJavaScript(
            f"updateLoginStatus({login_json})"
        )

    def _on_login_started(self):
        logger.info("信号: loginStarted")
        self.web_view.page().runJavaScript("onLoginStarted()")

    def _on_progress_update(self, progress: float, text: str):
        logger.debug(f"信号: progressUpdate - {progress:.1f}% {text}")
        self.web_view.page().runJavaScript(
            f"updateProgress({progress}, '{text}')"
        )

    def _on_game_launched(self):
        logger.info("信号: gameLaunched")
        self.web_view.page().runJavaScript("onGameLaunched()")

    def _on_install_complete(self, version_id: str):
        logger.info(f"信号: installComplete - {version_id}")
        self.web_view.page().runJavaScript(
            f"onInstallComplete('{version_id}')"
        )

    def _on_settings_loaded(self, settings_json: str):
        logger.info(f"信号: settingsLoaded, JSON 长度: {len(settings_json)}")
        self.web_view.page().runJavaScript(
            f"updateSettingsUI({settings_json})"
        )
        # Delay background setting to ensure JS bridge is ready
        QTimer.singleShot(500, lambda: self.bridge._apply_background())

    def _on_apply_background(self, data_uri: str):
        """Receive data URI from bridge and apply to JS"""
        logger.info(f"[BG] 收到 data URI, 长度: {len(data_uri)}")
        safe_uri = data_uri.replace("\\", "\\\\").replace("'", "\\'")
        self.web_view.page().runJavaScript(
            f"setBackground('{safe_uri}')",
            lambda r: logger.info("[BG] setBackground OK")
        )

    def _on_search_results(self, results_json: str):
        """Handle search results from API"""
        logger.info(f"搜索结果信号，长度: {len(results_json)}")
        self.web_view.page().runJavaScript(
            f"displaySearchResults({results_json})"
        )

    def _on_modpack_import_progress(self, detail_json: str):
        """Handle modpack import progress"""
        try:
            detail = json.loads(detail_json)
            files_json = json.dumps(detail.get("files", []))
            self.web_view.page().runJavaScript(
                f"updateModpackImportProgress({detail.get('current', 0)}, {detail.get('total', 0)}, "
                f"'{detail.get('message', '').replace(chr(39), chr(92)+chr(39)).replace(chr(10), ' ')}', "
                f"{detail.get('file_downloaded', 0)}, {detail.get('file_total', 0)}, {files_json})"
            )
        except Exception as e:
            logger.warning(f"处理导入进度失败: {e}")

    def _on_modpack_import_complete(self, result_json: str):
        """Handle modpack import completion"""
        logger.info(f"整合包导入完成: {result_json[:200]}")
        self.web_view.page().runJavaScript(
            f"onModpackImportComplete({result_json})"
        )

    def _on_modpack_info_loaded(self, info_json: str):
        """Handle modpack info loaded"""
        logger.info(f"整合包信息加载: {info_json[:200]}")
        self.web_view.page().runJavaScript(
            f"showModpackImportDialog({info_json})"
        )

    def _on_game_state_changed(self, state: str, extra: str):
        """Handle game state changes"""
        logger.info(f"游戏状态变更: {state} - {extra}")
        safe_extra = extra.replace("'", "\\'")
        self.web_view.page().runJavaScript(
            f"updateLaunchButton('{state}', '{safe_extra}')"
        )

    def _on_mod_loader_versions(self, data: str):
        """Handle mod loader versions response"""
        logger.info(f"模组加载器版本响应, 长度: {len(data)}")
        self.web_view.page().runJavaScript(
            f"updateModLoaderVersions({data})"
        )

    def _on_installed_loaders(self, data: str):
        """Handle installed loaders response"""
        logger.info(f"已安装加载器响应: {data[:100]}")
        self.web_view.page().runJavaScript(
            f"updateInstalledLoaders({data})"
        )

    def _on_mod_versions(self, data: str):
        """Handle mod versions response"""
        logger.info(f"模组版本响应, 长度: {len(data)}")
        self.web_view.page().runJavaScript(
            f"updateModVersions({data})"
        )

    def _on_error(self, error: str):
        logger.error(f"错误: {error}")
        # Escape single quotes and newlines for JS
        safe_error = error.replace("'", "\\'").replace("\n", " ")
        self.web_view.page().runJavaScript(
            f"showToast('{safe_error}', 'error'); onLoginError();"
        )

    def _on_background_selected(self, path: str):
        logger.info(f"信号: backgroundSelected - {path}")
        self.web_view.page().runJavaScript(
            f"setBackground('{path}')"
        )

def main():
    for key in list(os.environ.keys()):
        if key.lower() in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy', 'http_proxy_upper', 'https_proxy_upper'):
            logger.info(f"清除代理环境变量: {key}={os.environ[key]}")
            del os.environ[key]
    os.environ['no_proxy'] = '*'
    logger.info("已设置 no_proxy=* 以禁用系统代理")

    logger.info("=" * 50)
    logger.info("DevLauncher 启动")
    logger.info(f"Python: {sys.version}")
    logger.info(f"工作目录: {os.getcwd()}")
    logger.info("=" * 50)
    
    app = QApplication(sys.argv)
    app.setApplicationName("DevLauncher")
    
    window = MainWindow()
    window.show()
    
    logger.info("主窗口已显示")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

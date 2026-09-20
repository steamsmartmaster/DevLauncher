"""Modpack importer for CurseForge, Modrinth, and MultiMC formats"""
import json
import logging
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Optional, Callable
import requests
import minecraft_launcher_lib

logger = logging.getLogger("DevLauncher")


@dataclass
class ModpackInfo:
    """Modpack metadata"""
    name: str = ""
    version: str = ""
    author: str = ""
    description: str = ""
    minecraft_version: str = ""
    mod_loader: str = ""  # "forge", "fabric", "neoforge", "quilt"
    mod_loader_version: str = ""
    mod_count: int = 0
    format: str = ""  # "curseforge", "modrinth", "multimc"
    icon_path: str = ""


@dataclass
class CurseForgeModRef:
    """CurseForge mod reference"""
    project_id: int
    file_id: int
    required: bool = True


@dataclass
class ModrinthModRef:
    """Modrinth mod reference"""
    path: str
    downloads: list = field(default_factory=list)
    file_size: int = 0
    hashes: dict = field(default_factory=dict)


class ModpackImporter:
    """Handles modpack import from various formats"""

    def __init__(self, minecraft_dir, curseforge_api_key: str = "$2a$10$bL4bIL5pUWqfcO7KQtnMReakwtfHbNKh6v1uTpKlzhwoueEJQnPnm"):
        self.minecraft_dir = Path(minecraft_dir)
        self.curseforge_api_key = curseforge_api_key
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": curseforge_api_key,
            "Accept": "application/json"
        })

    def detect_format(self, zip_path: str) -> str:
        """Detect modpack format from ZIP contents.
        Checks for modrinth.index.json at root AND in overrides/ directory,
        since some .mrpack files bundle MultiMC metadata at root.
        """
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                names = zf.namelist()
                
                # Modrinth: modrinth.index.json (check root AND overrides/)
                if 'modrinth.index.json' in names:
                    return 'modrinth'
                if 'overrides/modrinth.index.json' in names:
                    return 'modrinth'
                if 'client-overrides/modrinth.index.json' in names:
                    return 'modrinth'
                
                # CurseForge: manifest.json
                if 'manifest.json' in names:
                    return 'curseforge'
                
                # MultiMC: instance.cfg + mmc-pack.json
                if 'instance.cfg' in names and 'mmc-pack.json' in names:
                    return 'multimc'
                
                # HMCL: hmclmodpack.json
                if 'hmclmodpack.json' in names:
                    return 'hmcl'
                    
        except Exception as e:
            logger.error(f"检测整合包格式失败: {e}")
        
        return 'unknown'

    def read_manifest(self, zip_path: str) -> Optional[ModpackInfo]:
        """Read modpack manifest and return info"""
        fmt = self.detect_format(zip_path)
        
        try:
            if fmt == 'curseforge':
                return self._read_curseforge_manifest(zip_path)
            elif fmt == 'modrinth':
                return self._read_modrinth_manifest(zip_path)
            elif fmt == 'multimc':
                return self._read_multimc_manifest(zip_path)
        except Exception as e:
            logger.error(f"读取整合包清单失败: {e}")
        
        return None

    def _read_curseforge_manifest(self, zip_path: str) -> ModpackInfo:
        """Read CurseForge manifest.json"""
        with zipfile.ZipFile(zip_path, 'r') as zf:
            with zf.open('manifest.json') as f:
                manifest = json.load(f)
        
        mc_info = manifest.get('minecraft', {})
        mod_loaders = mc_info.get('modLoaders', [])
        
        loader = ""
        loader_version = ""
        if mod_loaders:
            loader_id = mod_loaders[0].get('id', '')
            # Format: "forge-47.2.0" or "fabric-0.16.5"
            parts = loader_id.split('-', 1)
            if len(parts) == 2:
                loader = parts[0]
                loader_version = parts[1]
        
        # Count mods (excluding libraries)
        files = manifest.get('files', [])
        mod_count = len([f for f in files if f.get('required', True)])
        
        # Try to find icon
        icon_path = ""
        overrides = manifest.get('overrides', 'overrides')
        for ext in ['png', 'jpg', 'jpeg']:
            for name in [f'icon.{ext}', f'logo.{ext}', f'pack.png']:
                candidate = f'{overrides}/{name}'
                if candidate in [zi.filename for zi in zipfile.ZipFile(zip_path, 'r').filelist]:
                    icon_path = candidate
                    break
        
        return ModpackInfo(
            name=manifest.get('name', ''),
            version=manifest.get('version', ''),
            author=manifest.get('author', ''),
            description=manifest.get('description', ''),
            minecraft_version=mc_info.get('version', ''),
            mod_loader=loader,
            mod_loader_version=loader_version,
            mod_count=mod_count,
            format='curseforge',
            icon_path=icon_path
        )

    def _read_modrinth_manifest(self, zip_path: str) -> ModpackInfo:
        """Read Modrinth modrinth.index.json"""
        with zipfile.ZipFile(zip_path, 'r') as zf:
            with zf.open('modrinth.index.json') as f:
                manifest = json.load(f)
        
        deps = manifest.get('dependencies', {})
        
        # Determine loader from dependencies
        loader = ""
        loader_version = ""
        for key, ver in deps.items():
            if 'forge' in key and key != 'minecraft':
                loader = 'forge'
                loader_version = ver
            elif 'fabric' in key:
                loader = 'fabric'
                loader_version = ver
            elif 'neoforge' in key:
                loader = 'neoforge'
                loader_version = ver
            elif 'quilt' in key:
                loader = 'quilt'
                loader_version = ver
        
        # Count mods
        files = manifest.get('files', [])
        mod_count = len([f for f in files if f.get('env', {}).get('client', 'required') != 'unsupported'])
        
        return ModpackInfo(
            name=manifest.get('name', ''),
            version=manifest.get('versionId', ''),
            author='',
            description='',
            minecraft_version=deps.get('minecraft', ''),
            mod_loader=loader,
            mod_loader_version=loader_version,
            mod_count=mod_count,
            format='modrinth'
        )

    def _read_multimc_manifest(self, zip_path: str) -> ModpackInfo:
        """Read MultiMC instance.cfg + mmc-pack.json"""
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Read instance.cfg
            config = {}
            if 'instance.cfg' in zf.namelist():
                with zf.open('instance.cfg') as f:
                    for line in f.read().decode('utf-8').splitlines():
                        if '=' in line:
                            key, val = line.split('=', 1)
                            config[key.strip()] = val.strip()
            
            # Read mmc-pack.json
            pack = {}
            if 'mmc-pack.json' in zf.namelist():
                with zf.open('mmc-pack.json') as f:
                    pack = json.load(f)
        
        # Get loader info from mmc-pack.json
        loader = ""
        loader_version = ""
        components = pack.get('components', [])
        for comp in components:
            cid = comp.get('uid', '')
            if cid == 'net.minecraftforge':
                loader = 'forge'
                loader_version = comp.get('version', '')
            elif cid == 'net.fabricmc.fabric-loader':
                loader = 'fabric'
                loader_version = comp.get('version', '')
            elif cid == 'net.neoforged':
                loader = 'neoforge'
                loader_version = comp.get('version', '')
        
        return ModpackInfo(
            name=config.get('name', ''),
            version='',
            author='',
            description='',
            minecraft_version=config.get('MinecraftVersion', ''),
            mod_loader=loader,
            mod_loader_version=loader_version,
            mod_count=0,
            format='multimc'
        )

    def import_modpack(
        self,
        zip_path: str,
        version_name: str,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """
        Import a modpack from ZIP file.
        
        Args:
            zip_path: Path to the modpack ZIP file
            version_name: Name for the new version
            progress_callback: Optional callback(current, total, message)
        
        Returns:
            dict with 'success' and optional 'error'/'version_name'
        """
        fmt = self.detect_format(zip_path)
        logger.info(f"导入整合包: {zip_path}, 格式: {fmt}")
        
        def report(current, total, msg="", file_downloaded=0, file_total=0, file_states=None):
            if progress_callback:
                progress_callback(current, total, msg, file_downloaded, file_total, file_states)
        
        try:
            if fmt == 'curseforge':
                return self._import_curseforge(zip_path, version_name, report)
            elif fmt == 'modrinth':
                return self._import_modrinth(zip_path, version_name, report)
            elif fmt == 'multimc':
                return self._import_multimc(zip_path, version_name, report)
            else:
                return {'success': False, 'error': f'不支持的整合包格式: {fmt}'}
        except Exception as e:
            logger.error(f"导入整合包失败: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def _import_curseforge(self, zip_path: str, version_name: str, report) -> dict:
        """Import CurseForge modpack"""
        report(0, 100, "读取整合包清单...")
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            with zf.open('manifest.json') as f:
                manifest = json.load(f)
            
            mc_info = manifest.get('minecraft', {})
            mc_version = mc_info.get('version', '1.20.1')
            mod_loaders = mc_info.get('modLoaders', [])
            files = manifest.get('files', [])
            overrides = manifest.get('overrides', 'overrides')
            
            # Determine loader
            loader = ""
            loader_version = ""
            if mod_loaders:
                loader_id = mod_loaders[0].get('id', '')
                parts = loader_id.split('-', 1)
                if len(parts) == 2:
                    loader = parts[0]
                    loader_version = parts[1]
            
            # Create version directory
            version_dir = self.minecraft_dir / "versions" / version_name
            version_dir.mkdir(parents=True, exist_ok=True)
            mods_dir = version_dir / "mods"
            mods_dir.mkdir(exist_ok=True)
            
            # Enable version isolation so mods are version-specific
            from launcher_core.versions import VersionManager
            vm = VersionManager(str(self.minecraft_dir))
            vm.enable_version_isolation(version_name)
            
            # Download mods (multi-threaded)
            required_files = [f for f in files if f.get('required', True)]
            total = len(required_files)
            downloaded = 0
            errors = []
            lock = Lock()
            
            def download_one(idx_fref):
                idx, file_ref = idx_fref
                project_id = file_ref.get('projectID')
                file_id = file_ref.get('fileID')
                
                try:
                    file_info = self._get_curseforge_file(project_id, file_id)
                    if not file_info:
                        return (False, f"{project_id}/{file_id}", "Could not get file info")
                    
                    download_url = file_info.get('downloadUrl')
                    filename = file_info.get('fileName', f'{project_id}_{file_id}.jar')
                    
                    if not download_url:
                        return (False, filename, "No download URL")
                    
                    mod_path = mods_dir / filename
                    for attempt in range(3):
                        try:
                            self._download_file(download_url, mod_path)
                            with lock:
                                nonlocal downloaded
                                downloaded += 1
                            report(0, 0, f"下载模组 {downloaded}/{total}: {filename}", downloaded, total)
                            return (True, filename, None)
                        except Exception as e:
                            logger.warning(f"下载模组失败 {project_id}/{file_id} (尝试 {attempt+1}/3): {e}")
                            if attempt < 2:
                                import time
                                time.sleep(2 * (attempt + 1))
                    return (False, filename, f"Failed after 3 attempts")
                except Exception as e:
                    logger.warning(f"下载模组失败 {project_id}/{file_id}: {e}")
                    return (False, f"{project_id}/{file_id}", str(e))
            
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(download_one, (i, fref))
                    for i, fref in enumerate(required_files)
                ]
                for future in as_completed(futures):
                    try:
                        success, filename, error = future.result(timeout=120)
                        if not success and error:
                            errors.append(error)
                    except TimeoutError:
                        errors.append("下载超时")
                        future.cancel()
                    except Exception as e:
                        errors.append(f"Thread error: {e}")
            
            report(85, 100, "提取 overrides...")
            
            # Extract overrides
            for item in zf.infolist():
                if item.filename.startswith(overrides + '/'):
                    # Get relative path
                    rel_path = item.filename[len(overrides)+1:]
                    if rel_path:
                        target = version_dir / rel_path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if not item.is_dir():
                            with zf.open(item) as src, open(target, 'wb') as dst:
                                dst.write(src.read())
            
            # Copy icon if found
            info = self._read_curseforge_manifest(zip_path)
            if info and info.icon_path:
                try:
                    with zf.open(info.icon_path) as icon_file:
                        icon_ext = Path(info.icon_path).suffix
                        icon_dest = version_dir / f"pack{icon_ext}"
                        with open(icon_dest, 'wb') as dst:
                            dst.write(icon_file.read())
                except Exception as e:
                    logger.warning(f"复制图标失败: {e}")
            
            report(90, 100, "创建版本配置...")
            
            # Download vanilla Minecraft version if not installed
            self._ensure_vanilla_version(mc_version, report)
            
            # Create version JSON
            self._create_version_json(
                version_dir, version_name, mc_version, loader, loader_version
            )
            
            report(100, 100, f"导入完成! 已下载 {downloaded}/{len(files)} 个模组")
            
            result = {
                'success': True,
                'version_name': version_name,
                'downloaded': downloaded,
                'total': len(files),
                'errors': errors
            }
            
            if errors:
                result['warning'] = f'{len(errors)} 个模组下载失败'
            
            return result

    def _import_modrinth(self, zip_path: str, version_name: str, report) -> dict:
        """Import Modrinth modpack (.mrpack)"""
        report(0, 100, "读取整合包清单...")
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            with zf.open('modrinth.index.json') as f:
                manifest = json.load(f)
            
            deps = manifest.get('dependencies', {})
            mc_version = deps.get('minecraft', '1.20.1')
            files = manifest.get('files', [])
            
            # Determine loader
            loader = ""
            loader_version = ""
            for key, ver in deps.items():
                if 'forge' in key and key != 'minecraft':
                    loader = 'forge'
                    loader_version = ver
                elif 'fabric' in key:
                    loader = 'fabric'
                    loader_version = ver
                elif 'neoforge' in key:
                    loader = 'neoforge'
                    loader_version = ver
            
            # Create version directory
            version_dir = self.minecraft_dir / "versions" / version_name
            version_dir.mkdir(parents=True, exist_ok=True)
            mods_dir = version_dir / "mods"
            mods_dir.mkdir(exist_ok=True)
            
            # Enable version isolation so mods are version-specific
            from launcher_core.versions import VersionManager
            vm = VersionManager(str(self.minecraft_dir))
            vm.enable_version_isolation(version_name)
            
            # Download mods (multi-threaded)
            total = len(files)
            downloaded = 0
            errors = []
            lock = Lock()
            file_states = []  # Track all file states
            
            def download_one(idx_file):
                nonlocal downloaded
                idx, file_entry = idx_file
                downloads = file_entry.get('downloads', [])
                path = file_entry.get('path', '')
                filename = Path(path).name if path else f"file_{idx}"
                mod_path = mods_dir / filename
                
                # Mark as downloading
                with lock:
                    file_states.append({"name": filename, "status": "downloading"})
                    report(0, 0, f"下载模组 {downloaded}/{total}", downloaded, total, list(file_states))
                
                if not downloads:
                    with lock:
                        # Find and update this file's status
                        for fs in file_states:
                            if fs["name"] == filename and fs["status"] == "downloading":
                                fs["status"] = "error"
                                break
                        errors.append(f"No download URL for {path}")
                        report(0, 0, f"下载模组 {downloaded}/{total}", downloaded, total, list(file_states))
                    return (False, filename, f"No download URL for {path}")
                
                for url in downloads:
                    for attempt in range(3):
                        try:
                            self._download_file(url, mod_path)
                            with lock:
                                downloaded += 1
                                # Update file status
                                for fs in file_states:
                                    if fs["name"] == filename and fs["status"] == "downloading":
                                        fs["status"] = "done"
                                        break
                                report(0, 0, f"下载模组 {downloaded}/{total}", downloaded, total, list(file_states))
                            return (True, filename, None)
                        except Exception as e:
                            logger.warning(f"下载失败 {url} (尝试 {attempt+1}/3): {e}")
                            if attempt < 2:
                                import time
                                time.sleep(2 * (attempt + 1))
                
                with lock:
                    for fs in file_states:
                        if fs["name"] == filename and fs["status"] == "downloading":
                            fs["status"] = "error"
                            break
                    report(0, 0, f"下载模组 {downloaded}/{total}", downloaded, total, list(file_states))
                return (False, filename, f"Failed to download {path}")
            
            # Use 8 parallel threads
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(download_one, (i, fe))
                    for i, fe in enumerate(files)
                ]
                for future in as_completed(futures):
                    try:
                        success, filename, error = future.result(timeout=120)
                        if not success and error:
                            errors.append(error)
                    except TimeoutError:
                        errors.append("下载超时")
                        future.cancel()
                    except Exception as e:
                        errors.append(f"Thread error: {e}")
            
            report(85, 100, "提取文件...")
            
            # Extract overrides (supports both "overrides/" and "client-overrides/")
            for item in zf.infolist():
                rel_path = None
                if item.filename.startswith('client-overrides/'):
                    rel_path = item.filename[len('client-overrides/'):]
                elif item.filename.startswith('overrides/'):
                    rel_path = item.filename[len('overrides/'):]
                if rel_path:
                    target = version_dir / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not item.is_dir():
                        with zf.open(item) as src, open(target, 'wb') as dst:
                            dst.write(src.read())
            
            report(90, 100, "创建版本配置...")
            
            # Create version JSON
            self._create_version_json(
                version_dir, version_name, mc_version, loader, loader_version
            )
            
            report(100, 100, f"导入完成! 已下载 {downloaded}/{len(files)} 个模组")
            
            return {
                'success': True,
                'version_name': version_name,
                'downloaded': downloaded,
                'total': len(files),
                'errors': errors
            }

    def _import_multimc(self, zip_path: str, version_name: str, report) -> dict:
        """Import MultiMC modpack"""
        report(0, 100, "读取整合包清单...")
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Read instance.cfg
            config = {}
            if 'instance.cfg' in zf.namelist():
                with zf.open('instance.cfg') as f:
                    for line in f.read().decode('utf-8').splitlines():
                        if '=' in line:
                            key, val = line.split('=', 1)
                            config[key.strip()] = val.strip()
            
            # Read mmc-pack.json
            pack = {}
            if 'mmc-pack.json' in zf.namelist():
                with zf.open('mmc-pack.json') as f:
                    pack = json.load(f)
            
            mc_version = config.get('MinecraftVersion', '1.20.1')
            
            # Determine loader
            loader = ""
            loader_version = ""
            components = pack.get('components', [])
            for comp in components:
                cid = comp.get('uid', '')
                if cid == 'net.minecraftforge':
                    loader = 'forge'
                    loader_version = comp.get('version', '')
                elif cid == 'net.fabricmc.fabric-loader':
                    loader = 'fabric'
                    loader_version = comp.get('version', '')
            
            # Create version directory
            version_dir = self.minecraft_dir / "versions" / version_name
            version_dir.mkdir(parents=True, exist_ok=True)
            
            # Enable version isolation so mods are version-specific
            from launcher_core.versions import VersionManager
            vm = VersionManager(str(self.minecraft_dir))
            vm.enable_version_isolation(version_name)
            
            # Extract all files
            total = len(zf.infolist())
            for i, item in enumerate(zf.infolist()):
                report(int(i / total * 90), 100, f"解压文件 {i+1}/{total}...")
                
                if item.is_dir():
                    continue
                
                # Skip instance.cfg and mmc-pack.json
                if item.filename in ['instance.cfg', 'mmc-pack.json']:
                    continue
                
                target = version_dir / item.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(item) as src, open(target, 'wb') as dst:
                    dst.write(src.read())
            
            report(90, 100, "创建版本配置...")
            
            # Check if modrinth.index.json exists in ZIP (may be inside overrides/)
            modrinth_index = None
            for name in zf.namelist():
                if name.endswith('modrinth.index.json'):
                    with zf.open(name) as f:
                        modrinth_index = json.load(f)
                    break
            
            # Download mods from modrinth.index.json if available and mods/ is empty
            mods_dir = version_dir / "mods"
            downloaded_count = 0
            if modrinth_index and (not mods_dir.exists() or not any(mods_dir.iterdir())):
                files = modrinth_index.get('files', [])
                if files:
                    report(90, 100, f"下载模组 (0/{len(files)})...")
                    mods_dir.mkdir(exist_ok=True)
                    
                    def download_mod(idx_file):
                        idx, file_entry = idx_file
                        downloads = file_entry.get('downloads', [])
                        path = file_entry.get('path', '')
                        filename = Path(path).name if path else f"file_{idx}"
                        mod_path = mods_dir / filename
                        for url in downloads:
                            try:
                                self._download_file(url, mod_path)
                                return True
                            except Exception as e:
                                logger.warning(f"下载模组失败 {url}: {e}")
                        return False
                    
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    with ThreadPoolExecutor(max_workers=8) as executor:
                        futures = [executor.submit(download_mod, (i, fe)) for i, fe in enumerate(files)]
                        for f in as_completed(futures):
                            if f.result():
                                downloaded_count += 1
                            report(90 + int(downloaded_count / len(files) * 9), 100,
                                   f"下载模组 ({downloaded_count}/{len(files)})...")
            
            # Download vanilla Minecraft version if not installed
            self._ensure_vanilla_version(mc_version, report)
            
            # Create version JSON
            self._create_version_json(
                version_dir, version_name, mc_version, loader, loader_version
            )
            
            report(100, 100, "导入完成!")
            
            return {
                'success': True,
                'version_name': version_name,
                'downloaded': 0,
                'total': 0,
                'errors': []
            }

    def _download_missing_libraries(self, libraries: list):
        """Download any libraries that are not yet on disk"""
        for lib in libraries:
            name = lib.get("name", "")
            if not name:
                continue
            # Convert name to path: org.ow2.asm:asm:9.10.1 -> org/ow2/asm/asm/9.10.1/asm-9.10.1.jar
            parts = name.split(":")
            if len(parts) < 3:
                continue
            group, artifact, version = parts[0], parts[1], parts[2]
            classifier = parts[3] if len(parts) > 3 else ""
            
            group_path = group.replace(".", "/")
            jar_name = f"{artifact}-{version}"
            if classifier:
                jar_name += f"-{classifier}"
            jar_name += ".jar"
            
            lib_path = Path(self.minecraft_dir) / "libraries" / group_path / artifact / version / jar_name
            
            if lib_path.exists():
                continue
            
            # Use the URL from the library metadata (Fabric libs are on maven.fabricmc.net)
            download_url = lib.get("url", "")
            if not download_url:
                download_url = f"https://repo1.maven.org/maven2/{group_path}/{artifact}/{version}/{jar_name}"
            else:
                # Append the relative path to the base URL
                if not download_url.endswith("/"):
                    download_url += "/"
                download_url += f"{group_path}/{artifact}/{version}/{jar_name}"
            
            try:
                logger.info(f"下载库文件: {name}")
                lib_path.parent.mkdir(parents=True, exist_ok=True)
                self._download_file(download_url, lib_path)
            except Exception as e:
                logger.warning(f"下载库文件失败 {name}: {e}")

    def _get_curseforge_file(self, project_id: int, file_id: int) -> Optional[dict]:
        """Get CurseForge file info"""
        try:
            resp = self.session.get(
                f"https://api.curseforge.com/v1/mods/{project_id}/files/{file_id}",
                timeout=15
            )
            resp.raise_for_status()
            return resp.json().get('data')
        except Exception as e:
            logger.warning(f"获取 CurseForge 文件信息失败 {project_id}/{file_id}: {e}")
            return None

    def _download_file(self, url: str, dest: Path, total_timeout: int = 120):
        """Download a file with content validation and total timeout"""
        import time
        start_time = time.time()
        
        try:
            resp = requests.get(url, stream=True, timeout=(10, 30))
            resp.raise_for_status()
            
            # Validate content type for JAR files
            content_type = resp.headers.get("content-type", "")
            if dest.suffix == ".jar" and "html" in content_type.lower():
                raise ValueError(f"Downloaded HTML instead of JAR from {url}")
            
            with open(dest, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    if time.time() - start_time > total_timeout:
                        raise TimeoutError(f"Download timed out after {total_timeout}s: {url}")
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        
        # Validate file size (JARs should be > 1KB)
        if dest.suffix == ".jar" and dest.stat().st_size < 1024:
            file_size = dest.stat().st_size
            content = dest.read_text(errors="replace")[:200]
            dest.unlink()
            raise ValueError(f"Downloaded file too small ({file_size} bytes), likely HTML: {content[:100]}")

    def _ensure_vanilla_version(self, mc_version: str, report):
        """Download vanilla Minecraft version if not installed. Raises on failure."""
        try:
            installed = minecraft_launcher_lib.utils.get_installed_versions(str(self.minecraft_dir))
            installed_ids = [v.get("id") for v in installed if isinstance(v, dict)]
            if mc_version in installed_ids:
                logger.info(f"原版 {mc_version} 已安装")
                return
            
            logger.info(f"下载原版 Minecraft {mc_version}...")
            report(91, 100, f"正在下载 Minecraft {mc_version}...")
            
            def status_callback(status):
                if isinstance(status, dict):
                    msg = status.get("status", "")
                    if msg == "Downloading":
                        report(92, 100, f"正在下载 Minecraft {mc_version}...")
                    elif msg == "Extracting":
                        report(95, 100, "正在解压 Minecraft...")
            
            minecraft_launcher_lib.install.install_minecraft_version(
                mc_version,
                str(self.minecraft_dir),
                callback={"setStatus": status_callback}
            )
            logger.info(f"原版 Minecraft {mc_version} 下载完成")
        except Exception as e:
            logger.error(f"下载原版 Minecraft {mc_version} 失败: {e}")
            raise RuntimeError(f"无法下载原版 Minecraft {mc_version}: {e}")

    def _fetch_modrinth_index_from_api(self, version_name: str, report) -> Optional[dict]:
        """Fetch modrinth.index.json from Modrinth API by searching for the modpack."""
        try:
            report(0, 100, "从 Modrinth 获取整合包信息...")
            # Search for the modpack on Modrinth
            import urllib.parse
            query = urllib.parse.quote(version_name)
            search_url = f"https://api.modrinth.com/v2/search?query={query}&limit=5&facets=[[\"project_type:modpack\"]]"
            resp = requests.get(search_url, timeout=15)
            resp.raise_for_status()
            results = resp.json().get("hits", [])
            
            if not results:
                logger.warning(f"Modrinth 搜索无结果: {version_name}")
                return None
            
            # Find best match
            project_id = None
            for hit in results:
                title = hit.get("title", "").lower()
                slug = hit.get("slug", "").lower()
                vn = version_name.lower()
                if vn in title or vn in slug or title in vn:
                    project_id = hit.get("project_id")
                    break
            if not project_id and results:
                project_id = results[0].get("project_id")
            
            if not project_id:
                return None
            
            # Get version list for this project
            ver_resp = requests.get(
                f"https://api.modrinth.com/v2/project/{project_id}/version",
                timeout=15
            )
            ver_resp.raise_for_status()
            versions = ver_resp.json()
            
            if not versions:
                return None
            
            # Find the matching version or use latest
            target_version = None
            for v in versions:
                vname = v.get("name", "")
                if version_name.lower() in vname.lower() or vname.lower() in version_name.lower():
                    target_version = v
                    break
            if not target_version:
                target_version = versions[0]
            
            # Download the .mrpack to extract modrinth.index.json
            files = target_version.get("files", [])
            for vf in files:
                if vf.get("filename", "").endswith(".mrpack"):
                    mrpack_url = vf.get("url")
                    if mrpack_url:
                        report(0, 100, "下载整合包清单...")
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix=".mrpack", delete=False) as tmp:
                            tmp_path = tmp.name
                        try:
                            self._download_file(mrpack_url, Path(tmp_path))
                            with zipfile.ZipFile(tmp_path, 'r') as zf2:
                                for name in zf2.namelist():
                                    if name.endswith("modrinth.index.json"):
                                        with zf2.open(name) as f:
                                            index = json.load(f)
                                        # Save to version directory for future use
                                        save_path = self.minecraft_dir / "versions" / version_name / "modrinth.index.json"
                                        with open(save_path, 'w', encoding='utf-8') as sf:
                                            json.dump(index, sf, indent=2, ensure_ascii=False)
                                        logger.info(f"已从 Modrinth 获取整合包清单 ({len(index.get('files', []))} 个模组)")
                                        return index
                        finally:
                            try:
                                os.unlink(tmp_path)
                            except Exception:
                                pass
        except Exception as e:
            logger.warning(f"从 Modrinth 获取整合包清单失败: {e}")
        return None

    def redownload_modpack_mods(self, version_name: str, report=None) -> dict:
        """Re-download mods for an existing modpack version.
        Looks for modrinth.index.json in the version directory and downloads missing mods.
        """
        if report is None:
            report = lambda cur, total, msg: None
        
        version_dir = self.minecraft_dir / "versions" / version_name
        if not version_dir.exists():
            return {'success': False, 'error': f'版本目录不存在: {version_name}'}
        
        # Find modrinth.index.json in version directory or overrides
        modrinth_index = None
        index_candidates = [
            version_dir / "modrinth.index.json",
            version_dir / "overrides" / "modrinth.index.json",
        ]
        # Also check the original ZIP if it exists
        modpacks_dir = self.minecraft_dir / "modpacks"
        if modpacks_dir.exists():
            for zf_file in modpacks_dir.glob("*.mrpack"):
                try:
                    with zipfile.ZipFile(str(zf_file), 'r') as zf:
                        for name in zf.namelist():
                            if name.endswith('modrinth.index.json'):
                                with zf.open(name) as f:
                                    modrinth_index = json.load(f)
                                break
                except Exception:
                    pass
                if modrinth_index:
                    break
        
        if not modrinth_index:
            for p in index_candidates:
                if p.exists():
                    with open(p, 'r', encoding='utf-8') as f:
                        modrinth_index = json.load(f)
                    break
        
        # Fallback: fetch from Modrinth API
        if not modrinth_index:
            modrinth_index = self._fetch_modrinth_index_from_api(version_name, report)
        
        if not modrinth_index:
            return {'success': False, 'error': '未找到 modrinth.index.json，请在 Modrinth 上重新下载整合包'}
        
        files = modrinth_index.get('files', [])
        if not files:
            return {'success': True, 'downloaded': 0, 'total': 0, 'errors': []}
        
        mods_dir = version_dir / "mods"
        mods_dir.mkdir(exist_ok=True)
        
        # Check which mods are already present
        existing_mods = {f.name for f in mods_dir.iterdir() if f.suffix == '.jar'}
        to_download = []
        for i, file_entry in enumerate(files):
            path = file_entry.get('path', '')
            filename = Path(path).name if path else f"file_{i}"
            if filename not in existing_mods:
                to_download.append((i, file_entry))
        
        if not to_download:
            return {'success': True, 'downloaded': 0, 'total': len(files),
                    'message': '所有模组已存在'}
        
        report(0, 100, f"下载模组 (0/{len(to_download)})...")
        
        downloaded = 0
        errors = []
        
        def download_one(idx_file):
            nonlocal downloaded
            idx, file_entry = idx_file
            downloads = file_entry.get('downloads', [])
            path = file_entry.get('path', '')
            filename = Path(path).name if path else f"file_{idx}"
            mod_path = mods_dir / filename
            for url in downloads:
                for attempt in range(3):
                    try:
                        self._download_file(url, mod_path)
                        with lock:
                            downloaded += 1
                        return True
                    except Exception as e:
                        logger.warning(f"下载模组失败 {url} (尝试 {attempt+1}/3): {e}")
                        if attempt < 2:
                            import time
                            time.sleep(2 * (attempt + 1))
            return False
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from threading import Lock
        lock = Lock()
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(download_one, item) for item in to_download]
            for f in as_completed(futures):
                try:
                    success = f.result(timeout=120)
                except TimeoutError:
                    success = False
                    f.cancel()
                    errors.append("下载超时")
                if not success:
                    idx = futures.index(f)
                    errors.append(f"模组 {to_download[idx][1].get('path', 'unknown')} 下载失败")
                report(int(downloaded / len(to_download) * 100), 100,
                       f"下载模组 ({downloaded}/{len(to_download)})...")
        
        return {
            'success': len(errors) == 0,
            'downloaded': downloaded,
            'total': len(files),
            'errors': errors
        }

    def _create_version_json(
        self,
        version_dir: Path,
        version_name: str,
        mc_version: str,
        loader: str,
        loader_version: str
    ):
        """Create Minecraft version JSON"""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        
        # Base version JSON structure
        version_json = {
            "id": version_name,
            "inheritsFrom": mc_version,
            "type": "release",
            "mainClass": "net.minecraft.client.main.Main",
            "libraries": [],
            "releaseTime": now,
            "time": now
        }
        
        # Add loader libraries
        if loader == "fabric" and loader_version:
            try:
                meta_url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{loader_version}/profile/json"
                resp = requests.get(meta_url, timeout=15)
                resp.raise_for_status()
                fabric_meta = resp.json()
                
                version_json["libraries"] = fabric_meta.get("libraries", [])
                if "mainClass" in fabric_meta:
                    version_json["mainClass"] = fabric_meta["mainClass"]
                
                # Download any missing Fabric libraries
                self._download_missing_libraries(version_json["libraries"])
                    
                logger.info(f"已获取 Fabric {loader_version} 元数据")
            except Exception as e:
                logger.warning(f"获取 Fabric 元数据失败: {e}")
                version_json["mainClass"] = "net.fabricmc.loader.impl.launch.knot.KnotClient"
        
        elif loader == "forge" and loader_version:
            version_json["mainClass"] = "net.minecraftforge.fml.loading.FMLClientTweaker"
        
        elif loader == "neoforge" and loader_version:
            version_json["mainClass"] = "cpw.mods.fml.relauncher.FMLTweaker"
        
        elif loader == "quilt" and loader_version:
            try:
                meta_url = f"https://meta.quiltmc.org/v3/versions/loader/{mc_version}/{loader_version}/profile/json"
                resp = requests.get(meta_url, timeout=15)
                resp.raise_for_status()
                quilt_meta = resp.json()
                
                version_json["libraries"] = quilt_meta.get("libraries", [])
                if "mainClass" in quilt_meta:
                    version_json["mainClass"] = quilt_meta["mainClass"]
                    
                logger.info(f"已获取 Quilt {loader_version} 元数据")
            except Exception as e:
                logger.warning(f"获取 Quilt 元数据失败: {e}")
                version_json["mainClass"] = "org.quiltmc.loader.impl.launch.knot.KnotClient"
        
        # Write version JSON
        version_json_path = version_dir / f"{version_name}.json"
        with open(version_json_path, 'w', encoding='utf-8') as f:
            json.dump(version_json, f, indent=2, ensure_ascii=False)


# Singleton
def get_importer(minecraft_dir: Path) -> ModpackImporter:
    """Get modpack importer instance"""
    return ModpackImporter(minecraft_dir)

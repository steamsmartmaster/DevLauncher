"""Version management for Minecraft"""
import os
import json
import shutil
import logging
from typing import Optional
from pathlib import Path

import minecraft_launcher_lib

logger = logging.getLogger("DevLauncher")


class VersionSetting:
    """Per-version game settings"""
    
    DEFAULT = {
        "java_path": "",
        "max_memory": 4096,
        "min_memory": 1024,
        "jvm_args": "",
        "game_args": "",
        "width": 854,
        "height": 480,
        "fullscreen": False,
        "uses_global": True,
        "isolation": False
    }
    
    def __init__(self, version_dir: str):
        self.version_dir = Path(version_dir)
        self.config_file = self.version_dir / "devlauncher.cfg"
        self._settings = self.DEFAULT.copy()
        self._load()
    
    def _load(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._settings.update(saved)
            except Exception as e:
                logger.error(f"加载版本设置失败: {e}")
    
    def save(self):
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存版本设置失败: {e}")
    
    def get(self, key: str, default=None):
        return self._settings.get(key, default)
    
    def set(self, key: str, value):
        self._settings[key] = value
        self.save()
    
    def to_dict(self):
        return self._settings.copy()


class VersionManager:
    """Handle Minecraft version listing and installation"""

    def __init__(self, minecraft_dir: str):
        self.minecraft_dir = minecraft_dir
        os.makedirs(minecraft_dir, exist_ok=True)

    def get_version_list(self) -> list[dict]:
        """Get list of available Minecraft versions"""
        return minecraft_launcher_lib.utils.get_version_list()

    def get_installed_versions(self) -> list[dict]:
        """Get list of installed Minecraft versions with details.

        Shows user-managed versions (devlauncher.cfg) and modpack versions
        (inheritsFrom). Vanilla versions auto-downloaded as modpack
        dependencies are hidden: they have neither, and the modpack entry
        that needs them is listed instead.
        """
        versions = []
        versions_dir = Path(self.minecraft_dir) / "versions"
        if not versions_dir.exists():
            return versions

        for v_dir in versions_dir.iterdir():
            if not v_dir.is_dir():
                continue
            json_file = v_dir / f"{v_dir.name}.json"
            if not json_file.exists():
                continue
            try:
                with open(json_file, "r", encoding="utf-8-sig") as f:
                    version_data = json.load(f)
            except Exception as e:
                logger.warning(f"跳过版本 {v_dir.name}: {e}")
                continue

            inherits_from = version_data.get("inheritsFrom", "")
            has_cfg = (v_dir / "devlauncher.cfg").exists()
            # Keep user-managed versions and modpacks; hide auto-downloaded
            # vanilla parents regardless of whether a pack references them.
            if not (has_cfg or inherits_from):
                continue
            versions.append({
                "id": v_dir.name,
                "type": version_data.get("type", "unknown"),
                "releaseTime": version_data.get("releaseTime", ""),
                "inheritsFrom": inherits_from,
                "has_cfg": has_cfg
            })

        return versions

    def get_installed_version_ids(self) -> list[str]:
        """Get list of installed version IDs"""
        return minecraft_launcher_lib.utils.get_installed_versions(self.minecraft_dir)

    def get_latest_version(self) -> str:
        """Get the latest release version"""
        return minecraft_launcher_lib.utils.get_latest_version()["release"]

    def get_latest_snapshot(self) -> str:
        """Get the latest snapshot version"""
        return minecraft_launcher_lib.utils.get_latest_version()["snapshot"]

    def install_version(
        self,
        version_id: str,
        callback: Optional[dict] = None
    ) -> None:
        """Install a specific Minecraft version"""
        if callback is None:
            callback = {}
        minecraft_launcher_lib.install.install_minecraft_version(
            version_id,
            self.minecraft_dir,
            callback=callback
        )

    def is_version_installed(self, version_id: str) -> bool:
        """Check if a version is installed"""
        return version_id in minecraft_launcher_lib.utils.get_installed_versions(self.minecraft_dir)

    def get_version_path(self, version_id: str) -> Optional[Path]:
        """Get the path to a version directory"""
        version_path = Path(self.minecraft_dir) / "versions" / version_id
        if version_path.exists():
            return version_path
        return None

    def get_version_setting(self, version_id: str) -> VersionSetting:
        """Get settings for a specific version"""
        version_path = self.get_version_path(version_id)
        if version_path:
            return VersionSetting(str(version_path))
        return VersionSetting(str(Path(self.minecraft_dir) / "versions" / version_id))

    def rename_version(self, old_id: str, new_id: str) -> bool:
        """Rename a version"""
        old_path = self.get_version_path(old_id)
        if not old_path or not old_path.exists():
            logger.error(f"版本不存在: {old_id}")
            return False
        
        new_path = Path(self.minecraft_dir) / "versions" / new_id
        if new_path.exists():
            logger.error(f"目标版本已存在: {new_id}")
            return False
        
        try:
            # Rename directory
            old_path.rename(new_path)
            
            # Rename files
            old_json = new_path / f"{old_id}.json"
            new_json = new_path / f"{new_id}.json"
            if old_json.exists():
                old_json.rename(new_json)
                # Update id in JSON
                with open(new_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["id"] = new_id
                with open(new_json, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            
            old_jar = new_path / f"{old_id}.jar"
            new_jar = new_path / f"{new_id}.jar"
            if old_jar.exists():
                old_jar.rename(new_jar)
            
            logger.info(f"版本重命名: {old_id} -> {new_id}")
            return True
        except Exception as e:
            logger.error(f"重命名版本失败: {e}")
            return False

    def delete_version(self, version_id: str) -> bool:
        """Delete a version (move to trash)"""
        version_path = self.get_version_path(version_id)
        if not version_path:
            logger.error(f"版本不存在: {version_id}")
            return False
        
        try:
            # Move to _removed directory
            removed_dir = Path(self.minecraft_dir) / "_removed"
            removed_dir.mkdir(exist_ok=True)
            
            dest = removed_dir / version_id
            if dest.exists():
                shutil.rmtree(dest)
            
            shutil.move(str(version_path), str(dest))
            logger.info(f"版本已删除: {version_id}")
            return True
        except Exception as e:
            logger.error(f"删除版本失败: {e}")
            return False

    def duplicate_version(self, src_id: str, dst_id: str) -> bool:
        """Duplicate a version"""
        src_path = self.get_version_path(src_id)
        if not src_path:
            logger.error(f"源版本不存在: {src_id}")
            return False
        
        dst_path = Path(self.minecraft_dir) / "versions" / dst_id
        if dst_path.exists():
            logger.error(f"目标版本已存在: {dst_id}")
            return False
        
        try:
            shutil.copytree(str(src_path), str(dst_path))
            
            # Rename files
            old_json = dst_path / f"{src_id}.json"
            new_json = dst_path / f"{dst_id}.json"
            if old_json.exists():
                old_json.rename(new_json)
                with open(new_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["id"] = dst_id
                with open(new_json, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            
            old_jar = dst_path / f"{src_id}.jar"
            new_jar = dst_path / f"{dst_id}.jar"
            if old_jar.exists():
                old_jar.rename(new_jar)
            
            logger.info(f"版本复制: {src_id} -> {dst_id}")
            return True
        except Exception as e:
            logger.error(f"复制版本失败: {e}")
            return False

    def get_version_json(self, version_id: str) -> Optional[dict]:
        """Get version JSON data"""
        version_path = self.get_version_path(version_id)
        if not version_path:
            return None
        
        json_file = version_path / f"{version_id}.json"
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"读取版本JSON失败: {e}")
        return None

    def enable_version_isolation(self, version_id: str) -> bool:
        """Enable version isolation for a version"""
        version_path = self.get_version_path(version_id)
        if not version_path:
            logger.error(f"版本不存在: {version_id}")
            return False
        
        try:
            # Create isolated directories
            isolated_dirs = ["mods", "config", "saves", "resourcepacks", "shaderpacks", "libraries"]
            for dir_name in isolated_dirs:
                dir_path = version_path / dir_name
                dir_path.mkdir(exist_ok=True)
            
            # Update version setting
            setting = self.get_version_setting(version_id)
            setting.set("isolation", True)
            
            logger.info(f"版本隔离已启用: {version_id}")
            return True
        except Exception as e:
            logger.error(f"启用版本隔离失败: {e}")
            return False

    def disable_version_isolation(self, version_id: str) -> bool:
        """Disable version isolation for a version"""
        version_path = self.get_version_path(version_id)
        if not version_path:
            logger.error(f"版本不存在: {version_id}")
            return False
        
        try:
            # Remove isolated directories
            isolated_dirs = ["mods", "config", "saves", "resourcepacks", "shaderpacks"]
            for dir_name in isolated_dirs:
                dir_path = version_path / dir_name
                if dir_path.exists():
                    shutil.rmtree(dir_path)
            
            # Update version setting
            setting = self.get_version_setting(version_id)
            setting.set("isolation", False)
            
            logger.info(f"版本隔离已禁用: {version_id}")
            return True
        except Exception as e:
            logger.error(f"禁用版本隔离失败: {e}")
            return False

    def is_version_isolated(self, version_id: str) -> bool:
        """Check if a version has isolation enabled"""
        setting = self.get_version_setting(version_id)
        return setting.get("isolation", False)

    def get_isolated_path(self, version_id: str, subdir: str) -> Optional[Path]:
        """Get the isolated path for a version's subdirectory"""
        version_path = self.get_version_path(version_id)
        if not version_path:
            return None
        
        isolated_path = version_path / subdir
        if not isolated_path.exists():
            isolated_path.mkdir(parents=True, exist_ok=True)
        return isolated_path

    def get_mods_path(self, version_id: str) -> Path:
        """Get mods path (isolated or global)"""
        if self.is_version_isolated(version_id):
            return self.get_isolated_path(version_id, "mods") or Path(self.minecraft_dir) / "mods"
        # Fallback: check if version directory has its own mods/ with content
        # (handles modpacks imported by older launcher versions that didn't set isolation flag)
        if version_id:
            version_mods = Path(self.minecraft_dir) / "versions" / version_id / "mods"
            if version_mods.exists() and any(version_mods.iterdir()):
                return version_mods
        return Path(self.minecraft_dir) / "mods"

    def get_saves_path(self, version_id: str) -> Path:
        """Get saves path (isolated or global)"""
        if self.is_version_isolated(version_id):
            return self.get_isolated_path(version_id, "saves") or Path(self.minecraft_dir) / "saves"
        return Path(self.minecraft_dir) / "saves"

    def get_resourcepacks_path(self, version_id: str) -> Path:
        """Get resourcepacks path (isolated or global)"""
        if self.is_version_isolated(version_id):
            return self.get_isolated_path(version_id, "resourcepacks") or Path(self.minecraft_dir) / "resourcepacks"
        return Path(self.minecraft_dir) / "resourcepacks"

    def get_config_path(self, version_id: str) -> Path:
        """Get config path (isolated or global)"""
        if self.is_version_isolated(version_id):
            return self.get_isolated_path(version_id, "config") or Path(self.minecraft_dir) / "config"
        return Path(self.minecraft_dir) / "config"

    def is_valid_game_version(self, version_str: str) -> bool:
        """Check if a string looks like a valid Minecraft game version (e.g. '1.21.1', '1.20.1-pre1')"""
        import re
        return bool(re.match(r'^\d+\.\d+(\.\d+)?(-.+)?$', version_str))

    def get_version_json_path(self, version_id: str) -> str:
        """Get full path to version JSON file"""
        return os.path.join(self.minecraft_dir, "versions", version_id, f"{version_id}.json")

    def get_installed_loaders(self, version_id: str) -> list[dict]:
        """Detect installed mod loaders from version JSON"""
        json_path = self.get_version_json_path(version_id)
        from .api_modloaders import get_installed_loaders as _detect
        return _detect(json_path)

    def install_mod_loader(self, version_id: str, loader_type: str, loader_version: str,
                           callback: dict = None, installer_url: str = "") -> bool:
        """Install a mod loader onto a version"""
        from .api_modloaders import install_mod_loader as _install
        return _install(loader_type, version_id, loader_version, self.minecraft_dir, callback, installer_url=installer_url)

    def remove_mod_loader(self, version_id: str, loader_type: str) -> bool:
        """Remove a mod loader by restoring from vanilla backup (HMCL-inspired approach)"""
        from .api_modloaders import remove_mod_loader as _remove
        version_dir = os.path.join(self.minecraft_dir, "versions", version_id)
        return _remove(version_dir, version_id, loader_type)

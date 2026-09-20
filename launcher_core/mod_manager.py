"""Mod management for installed mods"""
import os
import json
import shutil
import logging
import zipfile
import base64
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("DevLauncher")


class ModInfo:
    """Information about a mod"""
    
    def __init__(self, path: str):
        self.path = Path(path)
        self.filename = self.path.name
        self.enabled = not self.filename.endswith(".disabled")
        
        # Parse display name from filename
        name = self.filename
        if name.endswith(".disabled"):
            name = name[:-9]  # Remove .disabled
        if name.endswith(".jar"):
            name = name[:-4]
        # Remove version-like suffixes (common patterns)
        for suffix in ["-fabric", "-forge", "-neoforge", "-quilt"]:
            if suffix in name:
                name = name.split(suffix)[0]
        self.name = name
        self.version = ""
        self.mod_id = ""
        self.description = ""
        self.authors = ""
        self.mc_version = ""
        self.icon_path = ""
        
        # Try to extract metadata from JAR
        self._extract_metadata()
    
    def _extract_metadata(self):
        """Extract mod metadata from JAR file (fabric.mod.json, mods.toml, quilt.mod.json)"""
        try:
            jar_path = self.path
            if not jar_path.exists() or not jar_path.suffix == '.jar':
                return
            
            with zipfile.ZipFile(jar_path, 'r') as zf:
                namelist = zf.namelist()
                logger.debug(f"JAR {self.filename}: {len(namelist)} files")
                # Try Fabric/Quilt: fabric.mod.json
                if 'fabric.mod.json' in namelist:
                    logger.debug(f"  -> fabric.mod.json found")
                    self._parse_fabric_mod(zf, 'fabric.mod.json')
                # Try Quilt: quilt.mod.json
                elif 'quilt.mod.json' in namelist:
                    logger.debug(f"  -> quilt.mod.json found")
                    self._parse_quilt_mod(zf)
                # Try Forge: META-INF/mods.toml
                elif 'META-INF/mods.toml' in namelist:
                    logger.debug(f"  -> META-INF/mods.toml found")
                    self._parse_forge_mods_toml(zf)
                # Try Forge legacy: mcmod.info
                elif 'mcmod.info' in namelist:
                    logger.debug(f"  -> mcmod.info found")
                    self._parse_mcmod_info(zf)
                else:
                    logger.debug(f"  -> no metadata found")
                if self.name:
                    logger.debug(f"  -> name={self.name}, mod_id={self.mod_id}, version={self.version}")
        except Exception as e:
            logger.debug(f"无法读取模组元数据 {self.filename}: {e}")
    
    def _parse_fabric_mod(self, zf, filename):
        """Parse fabric.mod.json"""
        try:
            data = json.loads(zf.read(filename))
            self.mod_id = data.get("id", "")
            self.name = data.get("name", self.name)
            self.version = data.get("version", "")
            self.description = data.get("description", "")
            authors = data.get("authors", [])
            if isinstance(authors, list):
                self.authors = ", ".join(authors[:3])
            elif isinstance(authors, str):
                self.authors = authors
            # Icon - can be string or list
            icon = data.get("icon", "")
            if isinstance(icon, list):
                icon = icon[0] if icon else ""
            if icon and icon in zf.namelist():
                self.icon_path = icon
            # Environment MC version from depends
            depends = data.get("depends", {})
            mc_ver = depends.get("minecraft", "")
            if mc_ver:
                self.mc_version = mc_ver
            logger.debug(f"fabric.mod.json: id={self.mod_id}, name={self.name}, ver={self.version}")
        except Exception as e:
            logger.debug(f"fabric.mod.json 解析失败: {e}")
    
    def _parse_quilt_mod(self, zf):
        """Parse quilt.mod.json"""
        try:
            data = json.loads(zf.read("quilt.mod.json"))
            quilt = data.get("quilt_loader", {})
            self.mod_id = quilt.get("id", "")
            self.name = quilt.get("metadata", {}).get("name", self.name)
            self.version = quilt.get("version", "")
            self.description = quilt.get("metadata", {}).get("description", "")
            contributors = quilt.get("metadata", {}).get("contributors", {})
            if isinstance(contributors, dict):
                self.authors = ", ".join(list(contributors.keys())[:3])
            icon = quilt.get("metadata", {}).get("icon", "")
            if icon and icon in zf.namelist():
                self.icon_path = icon
        except Exception:
            pass
    
    def _parse_forge_mods_toml(self, zf):
        """Parse META-INF/mods.toml (Forge 1.13+)"""
        try:
            content = zf.read("META-INF/mods.toml").decode("utf-8")
            # Simple TOML-like parsing for mods.toml
            in_mod = False
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("[[mods]]"):
                    in_mod = True
                elif line.startswith("[") and in_mod:
                    in_mod = False
                elif in_mod and line.startswith("modId"):
                    self.mod_id = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif in_mod and line.startswith("displayName"):
                    self.name = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif in_mod and line.startswith("version"):
                    self.version = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif in_mod and line.startswith("description"):
                    self.description = line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    
    def _parse_mcmod_info(self, zf):
        """Parse mcmod.info (Forge legacy)"""
        try:
            data = json.loads(zf.read("mcmod.info"))
            if isinstance(data, list) and len(data) > 0:
                info = data[0]
                self.mod_id = info.get("modid", "")
                self.name = info.get("name", self.name)
                self.version = info.get("version", "")
                self.description = info.get("description", "")
                self.mc_version = info.get("mcversion", "")
                authors = info.get("authorList", [])
                if isinstance(authors, list):
                    self.authors = ", ".join(authors[:3])
                elif isinstance(authors, str):
                    self.authors = authors
                # Icon
                icon = info.get("logoFile", "")
                if icon and icon in zf.namelist():
                    self.icon_path = icon
                logger.debug(f"mcmod.info: id={self.mod_id}, name={self.name}, ver={self.version}, mc={self.mc_version}")
        except Exception as e:
            logger.debug(f"mcmod.info 解析失败: {e}")
    
    def get_icon_data_uri(self) -> str:
        """Get mod icon as data URI"""
        if not self.path.exists():
            return ""
        try:
            with zipfile.ZipFile(self.path, 'r') as zf:
                namelist = zf.namelist()
                # Try multiple icon locations
                icon_candidates = []
                if self.icon_path:
                    icon_candidates.append(self.icon_path)
                # Common icon locations
                if self.mod_id:
                    icon_candidates.extend([
                        f"assets/{self.mod_id}/icon.png",
                        f"assets/{self.mod_id}/logo.png",
                        f"assets/{self.mod_id}/textures/icon.png",
                    ])
                icon_candidates.extend([
                    "icon.png", "logo.png", "mod_icon.png",
                ])
                for icon_path in icon_candidates:
                    if not icon_path:
                        continue
                    for name in namelist:
                        if name.lower() == icon_path.lower() or name == icon_path:
                            if name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                icon_data = zf.read(name)
                                ext = name.rsplit('.', 1)[-1].lower()
                                mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif"}.get(ext, "image/png")
                                return f"data:{mime};base64,{base64.b64encode(icon_data).decode()}"
        except Exception as e:
            logger.debug(f"无法读取模组图标 {self.filename}: {e}")
        
        # Fallback: fetch from Modrinth API with local cache
        return self._fetch_icon_from_modrinth()
    
    def _fetch_icon_from_modrinth(self) -> str:
        """Fetch mod icon from Modrinth API with local caching"""
        if not self.mod_id:
            return ""
        
        # Check local cache first
        cache_dir = Path.home() / ".mc-launcher" / "icon-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{self.mod_id}.png"
        
        if cache_file.exists():
            try:
                icon_data = cache_file.read_bytes()
                return f"data:image/png;base64,{base64.b64encode(icon_data).decode()}"
            except Exception:
                pass
        
        # Fetch from Modrinth API
        try:
            import requests
            resp = requests.get(
                f"https://api.modrinth.com/v2/project/{self.mod_id}",
                headers={"User-Agent": "DevLauncher/1.0"},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                icon_url = data.get("icon_url", "")
                if icon_url:
                    icon_resp = requests.get(icon_url, timeout=10)
                    if icon_resp.status_code == 200:
                        icon_data = icon_resp.content
                        cache_file.write_bytes(icon_data)
                        logger.debug(f"  -> Modrinth icon cached: {self.mod_id}")
                        return f"data:image/png;base64,{base64.b64encode(icon_data).decode()}"
        except Exception as e:
            logger.debug(f"  -> Modrinth icon fetch failed for {self.mod_id}: {e}")
        
        # Try search by name as last resort
        try:
            import requests
            resp = requests.get(
                "https://api.modrinth.com/v2/search",
                params={"query": self.name, "limit": 1},
                headers={"User-Agent": "DevLauncher/1.0"},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                hits = data.get("hits", [])
                if hits:
                    icon_url = hits[0].get("icon_url", "")
                    if icon_url:
                        icon_resp = requests.get(icon_url, timeout=10)
                        if icon_resp.status_code == 200:
                            icon_data = icon_resp.content
                            # Cache with the project ID from search result
                            project_id = hits[0].get("project_id", self.mod_id)
                            alt_cache = cache_dir / f"{project_id}.png"
                            alt_cache.write_bytes(icon_data)
                            logger.debug(f"  -> Modrinth icon cached (search): {project_id}")
                            return f"data:image/png;base64,{base64.b64encode(icon_data).decode()}"
        except Exception as e:
            logger.debug(f"  -> Modrinth search failed for {self.name}: {e}")
        
        return ""
    
    def to_dict(self):
        return {
            "name": self.name,
            "filename": self.filename,
            "enabled": self.enabled,
            "path": str(self.path),
            "size": self.path.stat().st_size if self.path.exists() else 0,
            "mod_id": self.mod_id,
            "version": self.version,
            "description": self.description,
            "authors": self.authors,
            "mc_version": self.mc_version,
            "icon": self.get_icon_data_uri()
        }


class ModManager:
    """Manage mods in a .minecraft/mods directory"""
    
    def __init__(self, minecraft_dir: str):
        self.minecraft_dir = Path(minecraft_dir)
        self.mods_dir = self.minecraft_dir / "mods"
        self.mods_dir.mkdir(parents=True, exist_ok=True)
    
    def get_mods(self) -> list[dict]:
        """Get all mods in the mods directory"""
        mods = []
        if not self.mods_dir.exists():
            return mods
        
        for item in self.mods_dir.iterdir():
            if item.is_file() and (item.suffix == ".jar" or item.suffix == ".disabled"):
                mod = ModInfo(str(item))
                mods.append(mod.to_dict())
            elif item.is_dir():
                # Support mod folders (like Fabric mods)
                for sub_item in item.iterdir():
                    if sub_item.is_file() and sub_item.suffix == ".jar":
                        mod = ModInfo(str(sub_item))
                        mods.append(mod.to_dict())
        
        return sorted(mods, key=lambda m: m["name"].lower())
    
    def enable_mod(self, filename: str, mods_dir: Path = None) -> bool:
        """Enable a disabled mod (rename .disabled to .jar)"""
        target_dir = mods_dir or self.mods_dir
        mod_path = target_dir / filename
        if not mod_path.exists():
            logger.error(f"模组不存在: {filename} (目录: {target_dir})")
            return False
        
        if not filename.endswith(".disabled"):
            logger.info(f"模组已启用: {filename}")
            return True
        
        new_path = target_dir / filename[:-9]  # Remove .disabled
        try:
            mod_path.rename(new_path)
            logger.info(f"模组已启用: {filename} -> {new_path.name}")
            return True
        except Exception as e:
            logger.error(f"启用模组失败: {e}")
            return False
    
    def disable_mod(self, filename: str, mods_dir: Path = None) -> bool:
        """Disable a mod (rename .jar to .disabled)"""
        target_dir = mods_dir or self.mods_dir
        mod_path = target_dir / filename
        if not mod_path.exists():
            logger.error(f"模组不存在: {filename} (目录: {target_dir})")
            return False
        
        if filename.endswith(".disabled"):
            logger.info(f"模组已禁用: {filename}")
            return True
        
        new_path = target_dir / (filename + ".disabled")
        try:
            mod_path.rename(new_path)
            logger.info(f"模组已禁用: {filename} -> {new_path.name}")
            return True
        except Exception as e:
            logger.error(f"禁用模组失败: {e}")
            return False
    
    def delete_mod(self, filename: str, mods_dir: Path = None) -> bool:
        """Delete a mod (move to _removed_mods)"""
        target_dir = mods_dir or self.mods_dir
        mod_path = target_dir / filename
        if not mod_path.exists():
            logger.error(f"模组不存在: {filename} (目录: {target_dir})")
            return False
        
        try:
            removed_dir = target_dir / "_removed_mods"
            removed_dir.mkdir(exist_ok=True)
            
            dest = removed_dir / filename
            if dest.exists():
                dest.unlink()
            
            shutil.move(str(mod_path), str(dest))
            logger.info(f"模组已删除: {filename}")
            return True
        except Exception as e:
            logger.error(f"删除模组失败: {e}")
            return False
    
    def install_mod(self, source_path: str, filename: Optional[str] = None) -> bool:
        """Install a mod from a file"""
        source = Path(source_path)
        if not source.exists():
            logger.error(f"源文件不存在: {source_path}")
            return False
        
        if filename is None:
            filename = source.name
        
        dest = self.mods_dir / filename
        try:
            shutil.copy2(str(source), str(dest))
            logger.info(f"模组已安装: {filename}")
            return True
        except Exception as e:
            logger.error(f"安装模组失败: {e}")
            return False

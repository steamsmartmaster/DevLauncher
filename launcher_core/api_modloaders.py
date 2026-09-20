"""API clients for fetching and installing mod loaders (Fabric, Forge, NeoForge, Quilt, OptiFine)

HMCL-inspired approach:
- Save vanilla JSON backup before any loader installation
- Merge loader into existing version (don't create new version)
- Remove by restoring from backup
- Support clean switching between loaders
"""
import os
import json
import shutil
import logging
import subprocess
import zipfile
from dataclasses import dataclass, asdict
from typing import Optional
from pathlib import Path

import requests
import minecraft_launcher_lib

logger = logging.getLogger("DevLauncher")

USER_AGENT = "DevLauncher/1.0.0 (contact@example.com)"


# === Vanilla JSON Backup Utilities ===

def get_vanilla_json_path(version_dir: str) -> str:
    """Get path to the vanilla JSON backup"""
    return os.path.join(version_dir, "devlauncher.vanilla.json")


def save_vanilla_json(version_dir: str, version_id: str) -> bool:
    """Save a backup of the vanilla version JSON before loader installation.
    
    This backup is used to restore the version when removing a mod loader.
    Only saves if no backup exists yet (first installation).
    """
    vanilla_path = get_vanilla_json_path(version_dir)
    version_json = os.path.join(version_dir, f"{version_id}.json")
    
    if not os.path.exists(version_json):
        logger.error(f"版本 JSON 不存在: {version_json}")
        return False
    
    # Only save backup if not already present
    if os.path.exists(vanilla_path):
        logger.info(f"Vanilla JSON 备份已存在: {vanilla_path}")
        return True
    
    try:
        shutil.copy2(version_json, vanilla_path)
        logger.info(f"已保存 vanilla JSON 备份: {vanilla_path}")
        return True
    except Exception as e:
        logger.error(f"保存 vanilla JSON 备份失败: {e}")
        return False


def restore_vanilla_json(version_dir: str, version_id: str) -> bool:
    """Restore the version JSON from vanilla backup.
    
    Used when removing a mod loader to return the version to its original state.
    """
    vanilla_path = get_vanilla_json_path(version_dir)
    version_json = os.path.join(version_dir, f"{version_id}.json")
    
    if not os.path.exists(vanilla_path):
        logger.error(f"Vanilla JSON 备份不存在: {vanilla_path}")
        return False
    
    try:
        shutil.copy2(vanilla_path, version_json)
        logger.info(f"已从 vanilla 备份恢复: {version_json}")
        return True
    except Exception as e:
        logger.error(f"恢复 vanilla JSON 失败: {e}")
        return False


def has_vanilla_backup(version_dir: str) -> bool:
    """Check if a vanilla JSON backup exists"""
    return os.path.exists(get_vanilla_json_path(version_dir))


def get_installed_loaders_from_json(version_dir: str, version_id: str) -> list[dict]:
    """Detect installed mod loaders by checking the vanilla backup and current JSON.
    
    If vanilla backup exists, compare with current JSON to find added loaders.
    If no backup, detect from library patterns.
    """
    vanilla_path = get_vanilla_json_path(version_dir)
    version_json = os.path.join(version_dir, f"{version_id}.json")
    
    if not os.path.exists(version_json):
        return []
    
    with open(version_json, "r", encoding="utf-8") as f:
        current_data = json.load(f)
    
    # If we have a vanilla backup, compare libraries
    if os.path.exists(vanilla_path):
        with open(vanilla_path, "r", encoding="utf-8") as f:
            vanilla_data = json.load(f)
        
        vanilla_libs = {lib.get("name", "") for lib in vanilla_data.get("libraries", [])}
        current_libs = current_data.get("libraries", [])
        
        detected = []
        seen_types = set()
        
        for lib in current_libs:
            name = lib.get("name", "")
            if name in vanilla_libs:
                continue  # Skip vanilla libraries
            
            loader_type = _detect_loader_type(name)
            if loader_type and loader_type not in seen_types:
                seen_types.add(loader_type)
                loader_ver = name.split(":")[-1] if ":" in name else ""
                detected.append({
                    "type": loader_type,
                    "version": loader_ver,
                    "name": LOADER_DISPLAY_NAMES.get(loader_type, loader_type)
                })
        
        return detected
    
    # Fallback: detect from library patterns
    return _detect_loaders_from_libraries(current_data.get("libraries", []))


def _detect_loader_type(lib_name: str) -> Optional[str]:
    """Detect loader type from a library name"""
    if "net.fabricmc:fabric-loader" in lib_name:
        return "fabric"
    elif "net.minecraftforge:forge" in lib_name or "net.minecraftforge:fml" in lib_name:
        return "forge"
    elif "net.neoforged" in lib_name:
        return "neoforge"
    elif "org.quiltmc" in lib_name:
        return "quilt"
    elif "optifine:OptiFine" in lib_name or "optifine" in lib_name.lower():
        return "optifine"
    return None


def _detect_loaders_from_libraries(libs: list) -> list[dict]:
    """Detect installed loaders from library list"""
    detected = []
    seen = set()
    
    for lib in libs:
        name = lib.get("name", "")
        loader_type = _detect_loader_type(name)
        if loader_type and loader_type not in seen:
            seen.add(loader_type)
            loader_ver = name.split(":")[-1] if ":" in name else ""
            detected.append({
                "type": loader_type,
                "version": loader_ver,
                "name": LOADER_DISPLAY_NAMES.get(loader_type, loader_type)
            })
    
    return detected


# === Mod Loader Version Data ===

@dataclass
class ModLoaderVersion:
    """Represents an available mod loader version"""
    loader_type: str       # fabric, forge, neoforge, quilt, optifine
    game_version: str      # Minecraft version this loader supports
    loader_version: str    # Loader version (e.g., "0.16.14", "47.3.0")
    download_url: str = ""
    installer_url: str = ""
    recommended: bool = False
    stable: bool = True

    def to_dict(self):
        return asdict(self)


# === Fabric API ===

class FabricAPI:
    """Fabric mod loader API client"""
    BASE_URL = "https://meta.fabricmc.net/v2"

    def get_versions(self, game_version: str) -> list[ModLoaderVersion]:
        """Get available Fabric loader versions for a game version"""
        try:
            url = f"{self.BASE_URL}/versions/loader/{game_version}"
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            versions = []
            for item in data:
                loader = item.get("loader", {})
                versions.append(ModLoaderVersion(
                    loader_type="fabric",
                    game_version=game_version,
                    loader_version=loader.get("version", ""),
                    download_url=loader.get("url", ""),
                    installer_url=f"{self.BASE_URL}/installer/loader/{game_version}/{loader.get('version', '')}/latest",
                    recommended=loader.get("stable", False),
                    stable=loader.get("stable", False),
                ))
            logger.info(f"Fabric: 获取到 {len(versions)} 个 loader 版本 (MC {game_version})")
            return versions
        except Exception as e:
            logger.error(f"Fabric API 错误: {e}")
            return []

    def get_latest(self, game_version: str) -> Optional[ModLoaderVersion]:
        """Get the latest stable Fabric loader version"""
        versions = self.get_versions(game_version)
        stable = [v for v in versions if v.stable]
        return stable[0] if stable else (versions[0] if versions else None)

    def install(self, game_version: str, loader_version: str, minecraft_dir: str,
                callback: dict = None) -> bool:
        """Install Fabric loader by merging into existing version JSON.
        
        HMCL-inspired approach:
        1. Save vanilla JSON backup
        2. Fetch Fabric launcher meta
        3. Merge libraries, mainClass, arguments into existing version
        """
        try:
            if callback is None:
                callback = {}
            set_status = callback.get("setStatus", lambda _: None)

            set_status("正在安装 Fabric Loader...")

            version_dir = os.path.join(minecraft_dir, "versions", game_version)
            version_json_path = os.path.join(version_dir, f"{game_version}.json")

            if not os.path.exists(version_json_path):
                logger.error(f"版本 JSON 不存在: {version_json_path}")
                return False

            # Step 1: Save vanilla JSON backup
            if not save_vanilla_json(version_dir, game_version):
                logger.warning("保存 vanilla JSON 备份失败，继续安装...")

            # Step 2: Fetch Fabric launcher meta
            meta_url = f"{self.BASE_URL}/versions/loader/{game_version}/{loader_version}/profile/json"
            resp = requests.get(meta_url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            fabric_meta = resp.json()

            # Step 3: Read existing version JSON
            with open(version_json_path, "r", encoding="utf-8") as f:
                version_data = json.load(f)

            # Step 4: Merge libraries (remove old Fabric libs first)
            existing_libs = version_data.get("libraries", [])
            fabric_libs = fabric_meta.get("libraries", [])

            # Remove old Fabric libraries
            existing_libs = [lib for lib in existing_libs
                           if not any(k in lib.get("name", "") for k in ["net.fabricmc"])]

            # Add Fabric libraries
            existing_libs.extend(fabric_libs)
            version_data["libraries"] = existing_libs

            # Set main class
            if "mainClass" in fabric_meta:
                version_data["mainClass"] = fabric_meta["mainClass"]

            # Merge arguments
            if "arguments" in fabric_meta:
                existing_args = version_data.get("arguments", {})
                fabric_args = fabric_meta.get("arguments", {})
                for key in ["game", "jvm"]:
                    if key in fabric_args:
                        existing_args.setdefault(key, [])
                        existing_args[key].extend(fabric_args[key])
                version_data["arguments"] = existing_args

            # Write back
            with open(version_json_path, "w", encoding="utf-8") as f:
                json.dump(version_data, f, indent=2, ensure_ascii=False)

            set_status("Fabric Loader 安装完成")
            logger.info(f"Fabric Loader {loader_version} 安装成功 (MC {game_version})")
            return True

        except Exception as e:
            logger.error(f"Fabric 安装失败: {e}", exc_info=True)
            return False


# === Forge API ===

class ForgeAPI:
    """Forge mod loader API client"""
    BMCLAPI_URL = "https://bmclapi2.bangbang93.com"

    def get_versions(self, game_version: str) -> list[ModLoaderVersion]:
        """Get available Forge versions for a game version"""
        try:
            url = f"{self.BMCLAPI_URL}/forge/minecraft/{game_version}"
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            versions = []
            for item in data:
                forge_version = item.get("version", "")
                parts = forge_version.split("-", 1)
                loader_ver = parts[1] if len(parts) > 1 else forge_version

                is_recommended = item.get("recommended", False)

                forge_full = f"{game_version}-{forge_version}"
                installer_url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{forge_full}/forge-{forge_full}-installer.jar"

                versions.append(ModLoaderVersion(
                    loader_type="forge",
                    game_version=game_version,
                    loader_version=loader_ver,
                    installer_url=installer_url,
                    recommended=is_recommended,
                    stable=True,
                ))

            versions.sort(key=lambda v: (not v.recommended, v.loader_version), reverse=True)
            logger.info(f"Forge: 获取到 {len(versions)} 个版本 (MC {game_version})")
            return versions
        except Exception as e:
            logger.error(f"Forge API 错误: {e}")
            return []

    def get_latest(self, game_version: str) -> Optional[ModLoaderVersion]:
        """Get the latest recommended Forge version"""
        versions = self.get_versions(game_version)
        recommended = [v for v in versions if v.recommended]
        return recommended[0] if recommended else (versions[0] if versions else None)

    def install(self, game_version: str, loader_version: str, minecraft_dir: str,
                callback: dict = None, installer_url: str = "") -> bool:
        """Install Forge by running the official installer, then merging into existing version.
        
        HMCL-inspired approach:
        1. Save vanilla JSON backup
        2. Run Forge installer (creates temp version directory)
        3. Read the Forge version JSON from installer output
        4. Merge Forge libraries/mainClass into existing version
        5. Clean up the temp version directory
        """
        try:
            if callback is None:
                callback = {}
            set_status = callback.get("setStatus", lambda _: None)

            set_status("正在安装 Forge...")

            forge_full = f"{game_version}-{loader_version}"

            # Use provided installer_url or construct from Maven
            if installer_url:
                url = installer_url
            else:
                url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{forge_full}/forge-{forge_full}-installer.jar"

            # Download installer to temp location
            tmp_dir = os.path.join(minecraft_dir, "versions", ".tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            installer_path = os.path.join(tmp_dir, f"forge-{forge_full}-installer.jar")

            set_status("下载 Forge 安装器...")
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120, stream=True)
            resp.raise_for_status()
            with open(installer_path, "wb") as f:
                shutil.copyfileobj(resp.raw, f)
            logger.info(f"Forge 安装器已下载: {installer_path}")

            # Find Java
            java_path = minecraft_launcher_lib.utils.get_java_executable()
            if not java_path:
                logger.error("未找到 Java，无法运行 Forge 安装器")
                set_status("错误: 未找到 Java")
                return False

            # Create launcher_profiles.json if missing
            profiles_path = os.path.join(minecraft_dir, "launcher_profiles.json")
            if not os.path.exists(profiles_path):
                profiles_data = {
                    "profiles": {
                        "devlauncher": {
                            "name": "DevLauncher",
                            "type": "custom",
                            "created": "2026-01-01T00:00:00.000Z",
                            "lastUsed": "2026-01-01T00:00:00.000Z",
                            "lastVersionId": "",
                            "javaArgs": ""
                        }
                    },
                    "selectedProfile": "devlauncher",
                    "clientToken": "devlauncher-token"
                }
                with open(profiles_path, "w") as f:
                    json.dump(profiles_data, f)
                logger.info("已创建 launcher_profiles.json")

            # Step 1: Save vanilla JSON backup before running installer
            version_dir = os.path.join(minecraft_dir, "versions", game_version)
            save_vanilla_json(version_dir, game_version)

            # Step 2: Determine Forge version for install method
            # Forge 1.13+ uses --installClient; older versions are extracted as ZIP
            mc_version_parts = game_version.split(".")
            mc_major = int(mc_version_parts[0]) if mc_version_parts else 0
            mc_minor = int(mc_version_parts[1]) if len(mc_version_parts) > 1 else 0
            is_old_forge = (mc_major < 1 or (mc_major == 1 and mc_minor < 13))

            if is_old_forge:
                # Old Forge (1.12.2 and earlier): extract from install_profile.json
                set_status("解压 Forge 安装器...")
                forge_id = f"{game_version}-Forge-{loader_version}"
                forge_dir = os.path.join(minecraft_dir, "versions", forge_id)

                with zipfile.ZipFile(installer_path, "r") as zf:
                    zip_names = zf.namelist()
                    logger.info(f"Forge ZIP 文件列表: {zip_names[:20]}...")

                    # Old Forge: check version.json first, then install_profile.json
                    version_info = None
                    if "version.json" in zip_names:
                        with zf.open("version.json") as f:
                            version_info = json.load(f)
                        logger.info("从 version.json 提取版本信息")
                    elif "install_profile.json" in zip_names:
                        with zf.open("install_profile.json") as f:
                            install_profile = json.load(f)
                        version_info = install_profile.get("versionInfo")
                        if version_info:
                            logger.info("从 install_profile.json 提取版本信息")
                        else:
                            logger.warning("install_profile.json 中未找到 versionInfo")

                    if not version_info:
                        logger.error("Forge 安装器中未找到版本信息")
                        set_status("Forge 安装失败: 版本信息未找到")
                        return False

                    os.makedirs(forge_dir, exist_ok=True)
                    forge_json_name = f"{forge_id}.json"
                    forge_json_path = os.path.join(forge_dir, forge_json_name)
                    with open(forge_json_path, "w", encoding="utf-8") as f:
                        json.dump(version_info, f, indent=2, ensure_ascii=False)
                    logger.info(f"已提取版本 JSON: {forge_json_name}")
                    version_json_name = forge_json_name

                    # Old Forge libraries are NOT in the ZIP - they have url fields
                    # and will be downloaded by minecraft_launcher_lib at launch
                    logger.info("旧版 Forge: 库将由启动器在启动时下载")

                # Clean up installer
                try:
                    os.remove(installer_path)
                except OSError:
                    pass

                # Now read the extracted Forge JSON and merge into original version
                forge_json_path = os.path.join(forge_dir, version_json_name)
                if os.path.exists(forge_json_path):
                    with open(forge_json_path, "r", encoding="utf-8") as f:
                        forge_data = json.load(f)

                    original_json = os.path.join(version_dir, f"{game_version}.json")
                    with open(original_json, "r", encoding="utf-8") as f:
                        original_data = json.load(f)

                    # Merge libraries
                    original_libs = original_data.get("libraries", [])
                    forge_libs = forge_data.get("libraries", [])
                    original_libs = [lib for lib in original_libs
                                   if not any(k in lib.get("name", "") for k in ["net.minecraftforge", "fml"])]
                    original_libs.extend(forge_libs)
                    original_data["libraries"] = original_libs

                    if "mainClass" in forge_data:
                        original_data["mainClass"] = forge_data["mainClass"]

                    if "minecraftArguments" in forge_data:
                        # Old Forge uses minecraftArguments instead of arguments
                        existing_args = original_data.get("minecraftArguments", "")
                        forge_args = forge_data.get("minecraftArguments", "")
                        if forge_args:
                            combined = existing_args + " " + forge_args
                            original_data["minecraftArguments"] = combined

                    if "arguments" in forge_data:
                        existing_args = original_data.get("arguments", {})
                        forge_args = forge_data.get("arguments", {})
                        for key in ["game", "jvm"]:
                            if key in forge_args:
                                existing_args.setdefault(key, [])
                                existing_args[key].extend(forge_args[key])
                        original_data["arguments"] = existing_args

                    # Update id and jar to match the actual version directory name
                    original_data["id"] = game_version
                    original_data["jar"] = game_version

                    with open(original_json, "w", encoding="utf-8") as f:
                        json.dump(original_data, f, indent=2, ensure_ascii=False)

                    logger.info(f"已将旧版 Forge 合并到 {game_version}")

                    # Clean up the Forge-specific version directory
                    try:
                        shutil.rmtree(forge_dir)
                        logger.info(f"已清理 Forge 临时目录: {forge_dir}")
                    except Exception as e:
                        logger.warning(f"清理 Forge 临时目录失败: {e}")

                    set_status("Forge 安装完成")
                    logger.info(f"Forge {loader_version} 安装成功 (MC {game_version})")
                    return True
                else:
                    logger.error(f"Forge 安装后未找到版本JSON: {forge_json_path}")
                    set_status("Forge 安装失败: 版本文件未生成")
                    return False
            else:
                # New Forge (1.13+): use --installClient
                set_status("运行 Forge 安装器...")
                cmd = [java_path, "-jar", installer_path, "--installClient", minecraft_dir]
                logger.info(f"执行: {' '.join(cmd)}")

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600
                )

                logger.info(f"Forge 安装器 stdout: {result.stdout}")
                if result.returncode != 0:
                    logger.error(f"Forge 安装器失败 (exit {result.returncode}): {result.stderr}")
                    set_status(f"Forge 安装失败: exit code {result.returncode}")
                    return False

                # Clean up installer
                try:
                    os.remove(installer_path)
                    os.rmdir(tmp_dir)
                except OSError:
                    pass

                # Step 3: Forge installer creates a new version directory
                forge_id = f"{game_version}-Forge-{loader_version}"
                forge_dir = os.path.join(minecraft_dir, "versions", forge_id)
                forge_json = os.path.join(forge_dir, f"{forge_id}.json")

                if os.path.exists(forge_json):
                    with open(forge_json, "r", encoding="utf-8") as f:
                        forge_data = json.load(f)

                    original_json = os.path.join(version_dir, f"{game_version}.json")
                    with open(original_json, "r", encoding="utf-8") as f:
                        original_data = json.load(f)

                    original_libs = original_data.get("libraries", [])
                    forge_libs = forge_data.get("libraries", [])
                    original_libs = [lib for lib in original_libs
                                   if not any(k in lib.get("name", "") for k in ["net.minecraftforge", "fml"])]
                    original_libs.extend(forge_libs)
                    original_data["libraries"] = original_libs

                    if "mainClass" in forge_data:
                        original_data["mainClass"] = forge_data["mainClass"]

                    if "arguments" in forge_data:
                        existing_args = original_data.get("arguments", {})
                        forge_args = forge_data.get("arguments", {})
                        for key in ["game", "jvm"]:
                            if key in forge_args:
                                existing_args.setdefault(key, [])
                                existing_args[key].extend(forge_args[key])
                        original_data["arguments"] = existing_args

                    with open(original_json, "w", encoding="utf-8") as f:
                        json.dump(original_data, f, indent=2, ensure_ascii=False)

                    logger.info(f"已将 Forge 合并到 {game_version}")

                    try:
                        shutil.rmtree(forge_dir)
                        logger.info(f"已清理 Forge 临时目录: {forge_dir}")
                    except Exception as e:
                        logger.warning(f"清理 Forge 临时目录失败: {e}")

                    set_status("Forge 安装完成")
                    logger.info(f"Forge {loader_version} 安装成功 (MC {game_version})")
                    return True
                else:
                    logger.error(f"Forge 安装后未找到版本JSON: {forge_json}")
                    set_status("Forge 安装失败: 版本文件未生成")
                    return False

        except subprocess.TimeoutExpired:
            logger.error("Forge 安装器超时")
            set_status("Forge 安装超时")
            return False
        except Exception as e:
            logger.error(f"Forge 安装失败: {e}", exc_info=True)
            set_status(f"Forge 安装失败: {e}")
            return False


# === NeoForge API ===

class NeoForgeAPI:
    """NeoForge mod loader API client"""
    BMCLAPI_URL = "https://bmclapi2.bangbang93.com"
    MAVEN_URL = "https://maven.neoforged.net/releases/net/neoforged/neoforge"

    def get_versions(self, game_version: str) -> list[ModLoaderVersion]:
        """Get available NeoForge versions for a game version"""
        try:
            url = f"{self.BMCLAPI_URL}/neoforge/list/{game_version}"
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            versions = []
            for item in data:
                nf_version = item.get("version", "")
                versions.append(ModLoaderVersion(
                    loader_type="neoforge",
                    game_version=game_version,
                    loader_version=nf_version,
                    download_url=item.get("url", ""),
                    installer_url=item.get("installer", ""),
                    recommended=item.get("recommended", False),
                    stable=True,
                ))

            versions.sort(key=lambda v: v.loader_version, reverse=True)
            logger.info(f"NeoForge: 获取到 {len(versions)} 个版本 (MC {game_version})")
            return versions
        except Exception as e:
            logger.error(f"NeoForge API 错误: {e}")
            return []

    def get_latest(self, game_version: str) -> Optional[ModLoaderVersion]:
        """Get the latest NeoForge version"""
        versions = self.get_versions(game_version)
        return versions[0] if versions else None

    def install(self, game_version: str, loader_version: str, minecraft_dir: str,
                callback: dict = None) -> bool:
        """Install NeoForge by extracting from installer and merging into existing version.
        
        HMCL-inspired approach:
        1. Save vanilla JSON backup
        2. Download NeoForge installer
        3. Extract install_profile.json
        4. Merge libraries into existing version
        """
        try:
            if callback is None:
                callback = {}
            set_status = callback.get("setStatus", lambda _: None)

            set_status("正在安装 NeoForge...")

            version_dir = os.path.join(minecraft_dir, "versions", game_version)
            version_json_path = os.path.join(version_dir, f"{game_version}.json")

            if not os.path.exists(version_json_path):
                logger.error(f"版本 JSON 不存在: {version_json_path}")
                return False

            # Step 1: Save vanilla JSON backup
            if not save_vanilla_json(version_dir, game_version):
                logger.warning("保存 vanilla JSON 备份失败，继续安装...")

            # Step 2: Download NeoForge installer
            installer_url = f"{self.BMCLAPI_URL}/neoforge/download/{loader_version}"
            installer_path = os.path.join(version_dir, f"neoforge-{loader_version}-installer.jar")

            set_status("下载 NeoForge 安装器...")
            resp = requests.get(installer_url, headers={"User-Agent": USER_AGENT}, timeout=60, stream=True)
            resp.raise_for_status()
            with open(installer_path, "wb") as f:
                shutil.copyfileobj(resp.raw, f)

            # Step 3: Extract install_profile.json
            with zipfile.ZipFile(installer_path, "r") as zf:
                if "install_profile.json" in zf.namelist():
                    with zf.open("install_profile.json") as ipf:
                        install_profile = json.load(ipf)
                else:
                    logger.error("NeoForge 安装器中未找到 install_profile.json")
                    return False

            # Step 4: Read existing version JSON
            with open(version_json_path, "r", encoding="utf-8") as f:
                version_data = json.load(f)

            # Step 5: Merge libraries
            forge_libs = install_profile.get("libraries", [])
            existing_libs = version_data.get("libraries", [])

            # Remove old NeoForge/Forge libraries
            existing_libs = [lib for lib in existing_libs
                           if not any(k in lib.get("name", "") for k in ["net.neoforged", "net.minecraftforge"])]

            # Add NeoForge libraries
            existing_libs.extend(forge_libs)
            version_data["libraries"] = existing_libs

            # Write back
            with open(version_json_path, "w", encoding="utf-8") as f:
                json.dump(version_data, f, indent=2, ensure_ascii=False)

            # Clean up installer
            try:
                os.remove(installer_path)
            except OSError:
                pass

            set_status("NeoForge 安装完成")
            logger.info(f"NeoForge {loader_version} 安装成功 (MC {game_version})")
            return True

        except Exception as e:
            logger.error(f"NeoForge 安装失败: {e}", exc_info=True)
            return False


# === Quilt API ===

class QuiltAPI:
    """Quilt mod loader API client"""
    BASE_URL = "https://meta.quiltmc.org/v3"

    def get_versions(self, game_version: str) -> list[ModLoaderVersion]:
        """Get available Quilt loader versions for a game version"""
        try:
            url = f"{self.BASE_URL}/versions/loader/{game_version}"
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            versions = []
            for item in data:
                loader = item.get("loader", {})
                versions.append(ModLoaderVersion(
                    loader_type="quilt",
                    game_version=game_version,
                    loader_version=loader.get("version", ""),
                    download_url=loader.get("url", ""),
                    installer_url=f"{self.BASE_URL}/installer/loader/{game_version}/{loader.get('version', '')}/latest",
                    recommended=loader.get("stable", False),
                    stable=loader.get("stable", False),
                ))
            logger.info(f"Quilt: 获取到 {len(versions)} 个版本 (MC {game_version})")
            return versions
        except Exception as e:
            logger.error(f"Quilt API 错误: {e}")
            return []

    def get_latest(self, game_version: str) -> Optional[ModLoaderVersion]:
        """Get the latest stable Quilt version"""
        versions = self.get_versions(game_version)
        stable = [v for v in versions if v.stable]
        return stable[0] if stable else (versions[0] if versions else None)

    def install(self, game_version: str, loader_version: str, minecraft_dir: str,
                callback: dict = None) -> bool:
        """Install Quilt loader by merging into existing version JSON.
        
        HMCL-inspired approach:
        1. Save vanilla JSON backup
        2. Fetch Quilt launcher meta
        3. Merge libraries, mainClass, arguments into existing version
        """
        try:
            if callback is None:
                callback = {}
            set_status = callback.get("setStatus", lambda _: None)

            set_status("正在安装 Quilt Loader...")

            version_dir = os.path.join(minecraft_dir, "versions", game_version)
            version_json_path = os.path.join(version_dir, f"{game_version}.json")

            if not os.path.exists(version_json_path):
                logger.error(f"版本 JSON 不存在: {version_json_path}")
                return False

            # Step 1: Save vanilla JSON backup
            if not save_vanilla_json(version_dir, game_version):
                logger.warning("保存 vanilla JSON 备份失败，继续安装...")

            # Step 2: Fetch Quilt launcher meta
            meta_url = f"{self.BASE_URL}/versions/loader/{game_version}/{loader_version}/profile/json"
            resp = requests.get(meta_url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            quilt_meta = resp.json()

            # Step 3: Read existing version JSON
            with open(version_json_path, "r", encoding="utf-8") as f:
                version_data = json.load(f)

            # Step 4: Merge libraries
            existing_libs = version_data.get("libraries", [])
            quilt_libs = quilt_meta.get("libraries", [])

            # Remove old Quilt/Fabric libraries
            existing_libs = [lib for lib in existing_libs
                           if not any(k in lib.get("name", "") for k in ["org.quiltmc", "net.fabricmc"])]

            # Add Quilt libraries
            existing_libs.extend(quilt_libs)
            version_data["libraries"] = existing_libs

            # Set main class
            if "mainClass" in quilt_meta:
                version_data["mainClass"] = quilt_meta["mainClass"]

            # Merge arguments
            if "arguments" in quilt_meta:
                existing_args = version_data.get("arguments", {})
                quilt_args = quilt_meta.get("arguments", {})
                for key in ["game", "jvm"]:
                    if key in quilt_args:
                        existing_args.setdefault(key, [])
                        existing_args[key].extend(quilt_args[key])
                version_data["arguments"] = existing_args

            # Write back
            with open(version_json_path, "w", encoding="utf-8") as f:
                json.dump(version_data, f, indent=2, ensure_ascii=False)

            set_status("Quilt Loader 安装完成")
            logger.info(f"Quilt Loader {loader_version} 安装成功 (MC {game_version})")
            return True

        except Exception as e:
            logger.error(f"Quilt 安装失败: {e}", exc_info=True)
            return False


# === OptiFine API ===

class OptiFineAPI:
    """OptiFine API client"""
    VERSIONS_URL = "https://optifine.net/api/versions?mc="

    def get_versions(self, game_version: str) -> list[ModLoaderVersion]:
        """Get available OptiFine versions for a game version"""
        try:
            url = f"{self.VERSIONS_URL}{game_version}"
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            versions = []
            for item in data:
                of_version = item.get("type", "") + " " + item.get("patch", "")
                download_url = item.get("downloadUrl", "")
                versions.append(ModLoaderVersion(
                    loader_type="optifine",
                    game_version=game_version,
                    loader_version=of_version.strip(),
                    download_url=download_url or "",
                    installer_url=download_url or "",
                    recommended="pre" not in of_version.lower(),
                    stable="pre" not in of_version.lower(),
                ))
            logger.info(f"OptiFine: 获取到 {len(versions)} 个版本 (MC {game_version})")
            return versions
        except Exception as e:
            logger.error(f"OptiFine API 错误: {e}")
            return []

    def get_latest(self, game_version: str) -> Optional[ModLoaderVersion]:
        """Get the latest stable OptiFine version"""
        versions = self.get_versions(game_version)
        stable = [v for v in versions if v.stable]
        return stable[0] if stable else (versions[0] if versions else None)

    def install(self, game_version: str, loader_version: str, minecraft_dir: str,
                callback: dict = None) -> bool:
        """Install OptiFine by adding it as a library.
        
        HMCL-inspired approach:
        1. Save vanilla JSON backup
        2. Download OptiFine JAR
        3. Add as library to existing version
        """
        try:
            if callback is None:
                callback = {}
            set_status = callback.get("setStatus", lambda _: None)

            set_status("正在安装 OptiFine...")

            version_dir = os.path.join(minecraft_dir, "versions", game_version)
            version_json_path = os.path.join(version_dir, f"{game_version}.json")

            if not os.path.exists(version_json_path):
                logger.error(f"版本 JSON 不存在: {version_json_path}")
                return False

            # Step 1: Save vanilla JSON backup
            if not save_vanilla_json(version_dir, game_version):
                logger.warning("保存 vanilla JSON 备份失败，继续安装...")

            # Step 2: Download OptiFine JAR
            if not installer_url:
                logger.error("OptiFine 下载链接无效")
                return False

            of_jar_name = f"OptiFine-{game_version}-{loader_version}.jar"
            of_jar_path = os.path.join(version_dir, of_jar_name)

            set_status("下载 OptiFine...")
            resp = requests.get(installer_url, headers={"User-Agent": USER_AGENT}, timeout=60, stream=True)
            resp.raise_for_status()
            with open(of_jar_path, "wb") as f:
                shutil.copyfileobj(resp.raw, f)

            # Step 3: Add as library to version JSON
            with open(version_json_path, "r", encoding="utf-8") as f:
                version_data = json.load(f)

            # Add OptiFine library entry
            of_lib = {
                "name": f"optifine:OptiFine:{game_version}_{loader_version}",
                "downloads": {
                    "artifact": {
                        "path": f"optifine/OptiFine/{game_version}_{loader_version}/{of_jar_name}",
                        "url": "",
                        "sha1": "",
                        "size": os.path.getsize(of_jar_path) if os.path.exists(of_jar_path) else 0
                    }
                },
                "rules": [{"action": "allow"}]
            }

            existing_libs = version_data.get("libraries", [])
            existing_libs = [lib for lib in existing_libs
                           if "optifine:OptiFine" not in lib.get("name", "")]
            existing_libs.append(of_lib)
            version_data["libraries"] = existing_libs

            # Add OptiFine tweak class
            if "arguments" not in version_data:
                version_data["arguments"] = {}
            args = version_data["arguments"]
            if "jvm" not in args:
                args["jvm"] = []
            optifine_tweak = "--tweakClass optifine.OptiFineTweaker"
            if optifine_tweak not in " ".join(args.get("game", [])):
                args.setdefault("game", [])
                args["game"].append(optifine_tweak)

            with open(version_json_path, "w", encoding="utf-8") as f:
                json.dump(version_data, f, indent=2, ensure_ascii=False)

            set_status("OptiFine 安装完成")
            logger.info(f"OptiFine {loader_version} 安装成功 (MC {game_version})")
            return True

        except Exception as e:
            logger.error(f"OptiFine 安装失败: {e}", exc_info=True)
            return False


# === Singleton instances ===
fabric_api = FabricAPI()
forge_api = ForgeAPI()
neoforge_api = NeoForgeAPI()
quilt_api = QuiltAPI()
optifine_api = OptiFineAPI()

# Registry for easy access
MOD_LOADER_APIS = {
    "fabric": fabric_api,
    "forge": forge_api,
    "neoforge": neoforge_api,
    "quilt": quilt_api,
    "optifine": optifine_api,
}

LOADER_DISPLAY_NAMES = {
    "fabric": "Fabric",
    "forge": "Forge",
    "neoforge": "NeoForge",
    "quilt": "Quilt",
    "optifine": "OptiFine",
}


# === Parallel Fetch Utilities ===

def _fetch_loader_versions(loader_type: str, api, game_version: str) -> tuple[str, list[ModLoaderVersion]]:
    """Fetch versions for a single loader type (used in parallel)"""
    try:
        versions = api.get_versions(game_version)
        return (loader_type, versions)
    except Exception:
        return (loader_type, [])


def _fetch_loader_latest(loader_type: str, api, game_version: str) -> tuple[str, Optional[ModLoaderVersion]]:
    """Fetch latest version for a single loader type (used in parallel)"""
    try:
        latest = api.get_latest(game_version)
        return (loader_type, latest)
    except Exception:
        return (loader_type, None)


def get_available_loaders(game_version: str) -> dict[str, list[ModLoaderVersion]]:
    """Get all available mod loader versions for a game version (parallel fetch)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    result = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_fetch_loader_versions, lt, api, game_version): lt
            for lt, api in MOD_LOADER_APIS.items()
        }
        for future in as_completed(futures):
            loader_type, versions = future.result()
            if versions:
                result[loader_type] = versions
    return result


def get_recommended_loaders(game_version: str) -> dict[str, ModLoaderVersion]:
    """Get the recommended (latest) version for each loader (parallel fetch)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    result = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_fetch_loader_latest, lt, api, game_version): lt
            for lt, api in MOD_LOADER_APIS.items()
        }
        for future in as_completed(futures):
            loader_type, latest = future.result()
            if latest:
                result[loader_type] = latest
    return result


def install_mod_loader(loader_type: str, game_version: str, loader_version: str,
                       minecraft_dir: str, callback: dict = None,
                       installer_url: str = "") -> bool:
    """Install a mod loader"""
    api = MOD_LOADER_APIS.get(loader_type)
    if not api:
        logger.error(f"未知的模组加载器: {loader_type}")
        return False
    return api.install(game_version, loader_version, minecraft_dir, callback, installer_url=installer_url)


def remove_mod_loader(version_dir: str, version_id: str, loader_type: str) -> bool:
    """Remove a mod loader by restoring from vanilla backup.
    
    HMCL-inspired approach:
    - Restore the original vanilla JSON from backup
    - This cleanly removes all loader modifications
    """
    vanilla_path = get_vanilla_json_path(version_dir)
    version_json = os.path.join(version_dir, f"{version_id}.json")
    
    if not os.path.exists(vanilla_path):
        logger.error(f"Vanilla JSON 备份不存在，无法移除 {loader_type}")
        return False
    
    try:
        # Restore from vanilla backup
        shutil.copy2(vanilla_path, version_json)
        logger.info(f"已移除 {loader_type} (从 vanilla 备份恢复)")
        return True
    except Exception as e:
        logger.error(f"移除 {loader_type} 失败: {e}")
        return False


def get_installed_loaders(version_json_path: str) -> list[dict]:
    """Detect installed mod loaders from a version JSON"""
    try:
        if not os.path.exists(version_json_path):
            return []

        with open(version_json_path, "r", encoding="utf-8") as f:
            version_data = json.load(f)

        libs = version_data.get("libraries", [])
        detected = []

        for lib in libs:
            name = lib.get("name", "")
            loader_type = _detect_loader_type(name)
            if loader_type:
                loader_ver = name.split(":")[-1] if ":" in name else ""
                detected.append({
                    "type": loader_type,
                    "version": loader_ver,
                    "name": LOADER_DISPLAY_NAMES.get(loader_type, loader_type)
                })

        # Deduplicate
        seen = set()
        unique = []
        for item in detected:
            key = item["type"]
            if key not in seen:
                seen.add(key)
                unique.append(item)

        return unique

    except Exception as e:
        logger.error(f"检测模组加载器失败: {e}")
        return []

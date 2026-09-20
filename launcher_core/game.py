import subprocess
import os
import json
import logging
import shutil
import zipfile
import platform
from typing import Optional
from pathlib import Path

import minecraft_launcher_lib

logger = logging.getLogger("DevLauncher")


class GameLauncher:
    """Handle Minecraft game launching"""

    def __init__(self, minecraft_dir: str):
        self.minecraft_dir = minecraft_dir
        self._process: Optional[subprocess.Popen] = None
        self._is_running = False
        logger.info(f"GameLauncher 初始化, 游戏目录: {minecraft_dir}")

    def launch(
        self,
        version_id: str,
        username: str,
        uuid: str,
        token: str,
        jvm_args: Optional[list[str]] = None,
        min_memory: int = 1024,
        max_memory: int = 4096
    ) -> tuple[bool, str]:
        """Launch Minecraft with given parameters. Returns (success, message)."""
        logger.info(f"准备启动游戏 - 版本: {version_id}, 用户: {username}")
        
        # 检查版本是否已安装
        installed_versions = minecraft_launcher_lib.utils.get_installed_versions(self.minecraft_dir)
        if not any(v["id"] == version_id for v in installed_versions):
            msg = f"版本 {version_id} 未安装，请先安装"
            logger.error(msg)
            return False, msg
        logger.info(f"版本 {version_id} 已安装")
        
        # 检查 Java
        java_path = minecraft_launcher_lib.utils.get_java_executable()
        if not java_path:
            msg = "未找到 Java，请安装 Java 后重试"
            logger.error(msg)
            return False, msg
        logger.info(f"Java 路径: {java_path}")
        
        # 检查版本文件是否存在
        version_path = os.path.join(self.minecraft_dir, "versions", version_id)
        jar_path = os.path.join(version_path, f"{version_id}.jar")
        json_path = os.path.join(version_path, f"{version_id}.json")
        
        if not os.path.exists(json_path):
            msg = f"版本配置不存在: {json_path}"
            logger.error(msg)
            return False, msg
        
        # JAR check: skip for mod-loader versions that use inheritsFrom (Forge/Fabric etc.)
        has_inherits = False
        inherits_from = ""
        try:
            with open(json_path, "r", encoding="utf-8-sig") as f:
                vd = json.load(f)
                has_inherits = "inheritsFrom" in vd
                inherits_from = vd.get("inheritsFrom", "")
        except Exception:
            pass
        
        if not has_inherits and not os.path.exists(jar_path):
            msg = f"版本文件不存在: {jar_path}"
            logger.error(msg)
            return False, msg
        
        # Ensure parent version (inheritsFrom) is installed
        if inherits_from:
            parent_json = os.path.join(self.minecraft_dir, "versions", inherits_from, f"{inherits_from}.json")
            for attempt in range(3):
                if os.path.exists(parent_json):
                    # Validate existing JSON is not corrupted (empty or invalid)
                    try:
                        with open(parent_json, 'r', encoding='utf-8-sig') as f:
                            json.load(f)
                        break  # Valid JSON, proceed
                    except Exception:
                        logger.warning(f"父版本 JSON 损坏，重新下载: {parent_json}")
                        os.remove(parent_json)
                
                logger.info(f"正在安装父版本 {inherits_from} (尝试 {attempt+1}/3)...")
                try:
                    def _install_cb(status):
                        logger.info(f"安装 {inherits_from}: {status}")
                    minecraft_launcher_lib.install.install_minecraft_version(
                        inherits_from, self.minecraft_dir,
                        callback={"setStatus": _install_cb}
                    )
                    logger.info(f"父版本 {inherits_from} 安装完成")
                    break
                except Exception as e:
                    logger.warning(f"安装父版本 {inherits_from} 失败 (尝试 {attempt+1}/3): {e}")
                    # Delete corrupted files and retry
                    if os.path.exists(parent_json):
                        os.remove(parent_json)
                    parent_dir = os.path.dirname(parent_json)
                    if os.path.exists(parent_dir):
                        shutil.rmtree(parent_dir, ignore_errors=True)
                    if attempt == 2:
                        msg = f"安装父版本 {inherits_from} 失败: {e}"
                        logger.error(msg)
                        return False, msg
        
        logger.info(f"版本文件检查通过")
        
        # Check version isolation and set gameDirectory if enabled
        version_config = os.path.join(version_path, "devlauncher.cfg")
        game_dir = self.minecraft_dir
        try:
            if os.path.exists(version_config):
                with open(version_config, "r") as f:
                    vc = json.load(f)
                if vc.get("isolation", False):
                    game_dir = version_path
                    logger.info(f"版本隔离已启用，游戏目录: {game_dir}")
        except Exception as e:
            logger.warning(f"读取版本配置失败: {e}")

        options = {
            "username": username,
            "uuid": uuid,
            "token": token,
            "jvmArguments": jvm_args or [
                f"-Xmx{max_memory}M",
                f"-Xms{min_memory}M"
            ],
            "launcherName": "DevLauncher",
            "launcherVersion": "1.0.0"
        }

        try:
            logger.info("生成启动命令...")
            command = minecraft_launcher_lib.command.get_minecraft_command(
                version_id,
                self.minecraft_dir,
                options
            )

            # Set gameDirectory if version isolation is enabled
            if game_dir != self.minecraft_dir:
                cmd_list = list(command)
                # Remove ALL existing --gameDir entries and their values
                new_cmd = []
                i = 0
                while i < len(cmd_list):
                    if cmd_list[i] == "--gameDir":
                        i += 2  # skip --gameDir and its value
                    else:
                        new_cmd.append(cmd_list[i])
                        i += 1
                new_cmd.extend(["--gameDir", game_dir])
                command = new_cmd
                logger.info(f"已设置 --gameDir: {game_dir}")

            # Fix duplicate arguments from MinecraftArguments + Forge JSON
            # MinecraftArguments expands ${version_type} etc., and Forge adds its own
            # Keep the last occurrence of each --arg (Forge values override MinecraftArguments)
            cmd_list = list(command)
            arg_positions = {}  # arg -> index in deduped list
            deduped = []
            skip_next = False
            for i, arg in enumerate(cmd_list):
                if skip_next:
                    skip_next = False
                    continue
                if arg.startswith("--"):
                    if arg in arg_positions:
                        # Replace previous value with this one (keep last occurrence)
                        idx = arg_positions[arg]
                        deduped[idx + 1] = cmd_list[i + 1]
                    else:
                        arg_positions[arg] = len(deduped)
                        deduped.append(arg)
                        deduped.append(cmd_list[i + 1])
                    skip_next = True
                else:
                    deduped.append(arg)
            command = deduped

            # Fix: resolve inheritsFrom for jar path
            # minecraft_launcher_lib doesn't add parent jar to classpath
            vn_path = os.path.join(self.minecraft_dir, "versions", version_id, f"{version_id}.json")
            if os.path.exists(vn_path):
                with open(vn_path, "r", encoding="utf-8") as f:
                    vn = json.load(f)
                inherits = vn.get("inheritsFrom")
                if inherits:
                    parent_jar = os.path.join(self.minecraft_dir, "versions", inherits, f"{inherits}.jar")
                    if os.path.exists(parent_jar):
                        cp_idx = command.index("-cp")
                        cp = command[cp_idx + 1]
                        if parent_jar.replace("\\", "/") not in cp.replace("\\", "/"):
                            command[cp_idx + 1] = cp + ";" + parent_jar
                            logger.info(f"Added inherited jar to classpath: {parent_jar}")

            # Extract natives for versions with inheritsFrom
            # minecraft_launcher_lib doesn't extract natives for inherited versions
            natives_dir = os.path.join(self.minecraft_dir, "versions", version_id, "natives")
            if not os.path.exists(natives_dir):
                self._extract_natives(version_id, inherits if inherits else version_id, natives_dir)

            logger.info(f"启动命令: {' '.join(command[:5])}...")
            # Log gameDir for debugging
            for i, arg in enumerate(command):
                if arg == "--gameDir" and i + 1 < len(command):
                    logger.info(f"--gameDir: {command[i+1]}")
            logger.info(f"完整启动命令长度: {len(command)} 个参数")
            for i, arg in enumerate(command):
                logger.debug(f"  arg[{i}]: {arg[:200]}")
            
            logger.info("启动游戏进程...")
            # Use log file for game output so errors are captured
            log_dir = os.path.join(self.minecraft_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            game_log_path = os.path.join(log_dir, "game.log")
            game_log = open(game_log_path, "w", encoding="utf-8", errors="replace")
            self._process = subprocess.Popen(
                command,
                cwd=self.minecraft_dir,
                stdout=game_log,
                stderr=subprocess.STDOUT
            )
            self._is_running = True
            logger.info(f"游戏进程已启动, PID: {self._process.pid}")
            return True, "游戏已启动"
        except FileNotFoundError as e:
            msg = f"找不到 Java 或 Minecraft 文件: {e}"
            logger.error(msg, exc_info=True)
            return False, msg
        except PermissionError as e:
            msg = f"权限不足: {e}"
            logger.error(msg, exc_info=True)
            return False, msg
        except Exception as e:
            msg = f"启动失败: {e}"
            logger.error(msg, exc_info=True)
            return False, msg

    def _extract_natives(self, version_id: str, source_version_id: str, natives_dir: str):
        """Extract native libraries to the natives directory"""
        os_name = "windows" if platform.system() == "Windows" else "linux" if platform.system() == "Linux" else "osx"
        logger.info(f"提取原生库: {source_version_id} -> {natives_dir}")

        # Load version JSON and resolve inheritsFrom chain
        all_versions = []
        current = source_version_id
        while current:
            vn_path = os.path.join(self.minecraft_dir, "versions", current, f"{current}.json")
            if not os.path.exists(vn_path):
                break
            with open(vn_path, "r", encoding="utf-8") as f:
                vn = json.load(f)
            all_versions.append(vn)
            current = vn.get("inheritsFrom")

        os.makedirs(natives_dir, exist_ok=True)
        extracted = 0

        for vn in all_versions:
            for lib in vn.get("libraries", []):
                natives_map = lib.get("natives", {})
                if not natives_map or os_name not in natives_map:
                    continue

                classifier = natives_map[os_name]
                lib_name = lib.get("name", "")
                dl = lib.get("downloads", {})
                classifiers = dl.get("classifiers", {})
                cls_info = classifiers.get(classifier, {})
                path = cls_info.get("path", "")

                if not path:
                    continue

                jar_path = os.path.join(self.minecraft_dir, "libraries", path)
                if not os.path.exists(jar_path):
                    logger.warning(f"Natives jar not found: {jar_path}")
                    continue

                try:
                    with zipfile.ZipFile(jar_path, "r") as zf:
                        for entry in zf.namelist():
                            if entry.endswith(".dll") or entry.endswith(".so") or entry.endswith(".dylib") or entry.endswith(".jnilib"):
                                data = zf.read(entry)
                                out_path = os.path.join(natives_dir, os.path.basename(entry))
                                with open(out_path, "wb") as f:
                                    f.write(data)
                                extracted += 1
                except Exception as e:
                    logger.warning(f"Failed to extract natives from {jar_path}: {e}")

        logger.info(f"提取了 {extracted} 个原生库文件")

    def is_running(self) -> bool:
        """Check if game is still running"""
        if self._process and self._is_running:
            return self._process.poll() is None
        return False

    def get_exit_code(self) -> Optional[int]:
        """Get the exit code of the game process"""
        if self._process:
            return self._process.poll()
        return None

    def kill(self) -> bool:
        """Kill the game process"""
        if self._process and self._is_running:
            try:
                self._process.terminate()
                self._is_running = False
                logger.info("游戏进程已终止")
                return True
            except Exception as e:
                logger.error(f"终止游戏进程失败: {e}")
                return False
        return False

    def get_java_path(self) -> str:
        """Get system Java path"""
        java_path = minecraft_launcher_lib.utils.get_java_executable()
        if java_path:
            return java_path
        return "java"

    def get_game_directory(self) -> str:
        """Get game directory path"""
        return self.minecraft_dir

    def get_logs_directory(self) -> str:
        """Get logs directory path"""
        logs_dir = os.path.join(self.minecraft_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        return logs_dir

"""插件系统核心：manifest 扫描 + importlib 独立加载 + 宿主 API。

- ``PluginContext``：每插件一个，由 PluginManager 构造；
  register_content / get_config / set_config / logger。
- ``PluginManager``：scan / detail / set_enabled / save_config /
  load_all / reload / uninstall / folder_of。

plugins_dir 默认由本文件位置推导（launcher_core/plugins.py → 仓库根/plugins），
不依赖 Path.cwd()：启动器可能被从任意工作目录启动，cwd 推导会指错目录。
仅 stdlib（json/shutil/importlib/pathlib/logging/os/re/inspect/sys）。
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path

logger = logging.getLogger("DevLauncher")

_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SETTING_TYPES = ("text", "toggle", "number")
_SETTING_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _module_name(plugin_id: str) -> str:
    """插件模块在 sys.modules 中的唯一名（直拼，允许 id 中的 - . 等白名单字符）。"""
    return f"devlauncher_plugin_{plugin_id}"


def _filter_settings(items, require_valid_type: bool = False) -> list[dict]:
    """过滤非法 settings 元素：非 dict / key 不合白名单一律丢弃（S1 引号注入防线）。

    key 必须匹配 ^[A-Za-z0-9_-]+$（会进入 data-key/onchange 等属性与内联上下文）。
    require_valid_type=True 时额外丢弃 type 不在 text/toggle/number 的元素
    （detail 组装 UI schema 用；PluginContext 保底用 False，与 _value_matches_type
    对未知 type 放行的既有语义一致）。
    """
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not isinstance(key, str) or not _SETTING_KEY_RE.match(key):
            logger.warning("插件设置项 key 不合白名单 [A-Za-z0-9_-]，过滤: %r", key)
            continue
        if require_valid_type and item.get("type", "text") not in _SETTING_TYPES:
            continue
        out.append(item)
    return out


def _atomic_write_json(path: Path, payload) -> None:
    """原子写 JSON：tmp + os.replace（照抄 accounts.py 手法）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _value_matches_type(item: dict, value) -> bool:
    type_name = item.get("type", "text")
    if type_name == "text":
        return isinstance(value, str)
    if type_name == "toggle":
        return isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _is_safe_id(plugin_id) -> bool:
    if not isinstance(plugin_id, str) or not plugin_id:
        return False
    if ".." in plugin_id:
        return False
    return bool(_ID_RE.fullmatch(plugin_id))


class PluginContext:
    """每插件一个的宿主 API 上下文。"""

    def __init__(self, plugin_id: str, plugin_dir: Path, settings: list | None = None) -> None:
        self.plugin_id = plugin_id
        self.plugin_dir = Path(plugin_dir)
        self.settings = _filter_settings(settings)
        self.logger = logging.getLogger(f"plugin.{plugin_id}")
        self._content = ""

    # ---------------- 内容区 ----------------

    def register_content(self, html: str) -> None:
        """详情页自定义内容区；后注册覆盖先注册。"""
        if not isinstance(html, str):
            raise TypeError(f"register_content 需要 str，收到 {type(html).__name__}")
        self._content = html

    @property
    def content(self) -> str:
        return self._content

    # ---------------- 配置 ----------------

    @property
    def config_path(self) -> Path:
        return self.plugin_dir / "config.json"

    def _read_disk(self) -> dict:
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("插件 %s config.json 读取失败: %s", self.plugin_id, e)
            return {}
        return data if isinstance(data, dict) else {}

    def get_config(self) -> dict:
        """按 manifest settings schema 补齐默认值；磁盘 config.json 优先。"""
        disk = self._read_disk()
        out = {}
        for item in self.settings:
            key = item["key"]
            if key in disk and _value_matches_type(item, disk[key]):
                out[key] = disk[key]
            else:
                out[key] = item.get("default")
        return out

    def _validate(self, cfg) -> dict:
        if not isinstance(cfg, dict):
            raise ValueError("配置必须是对象(dict)")
        schema = {item["key"]: item for item in self.settings}
        for key, value in cfg.items():
            if key not in schema:
                raise ValueError(f"未知配置项: {key}")
            if not _value_matches_type(schema[key], value):
                expected = schema[key].get("type", "text")
                raise ValueError(f"配置项 {key} 类型不符，期望 {expected}")
        return dict(cfg)

    def set_config(self, cfg: dict) -> None:
        """类型校验（text/toggle/number）+ 原子写 config.json；坏类型/坏 key → ValueError。"""
        validated = self._validate(cfg)
        merged = self._read_disk()
        merged.update(validated)
        _atomic_write_json(self.config_path, merged)


class PluginManager:
    def __init__(self, plugins_dir: Path | None = None) -> None:
        if plugins_dir is None:
            # dev：仓库根/plugins；frozen：exe 同目录/plugins（见 paths.app_base_dir）
            from .paths import app_base_dir
            plugins_dir = app_base_dir() / "plugins"
        self.plugins_dir = Path(plugins_dir)
        self._manifests: dict[str, dict] = {}
        self._dirs: dict[str, Path] = {}
        self._settings: dict[str, list] = {}
        self._enabled: dict[str, bool] = {}
        self._errors: dict[str, str] = {}
        self._instances: dict[str, object] = {}
        self._contexts: dict[str, PluginContext] = {}
        self._load_enabled()

    # ---------------- enabled.json ----------------

    def _load_enabled(self) -> None:
        path = self.plugins_dir / "enabled.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("enabled.json 读取失败，按全启用处理: %s", e)
            return
        if isinstance(data, dict):
            self._enabled = {str(k): bool(v) for k, v in data.items()}

    def _write_enabled(self) -> None:
        _atomic_write_json(self.plugins_dir / "enabled.json", self._enabled)

    def _is_enabled(self, plugin_id: str) -> bool:
        return bool(self._enabled.get(plugin_id, True))

    # ---------------- 扫描 ----------------

    def scan(self) -> list[dict]:
        manifests: dict[str, dict] = {}
        dirs: dict[str, Path] = {}
        settings: dict[str, list] = {}
        if self.plugins_dir.is_dir():
            for child in sorted(self.plugins_dir.iterdir()):
                if not child.is_dir():
                    continue
                # 防线下沉(M2)：目录联接/软链指向 plugins_dir 之外 → 扫描期即拒绝，
                # save_config/detail/uninstall/folder_of 因此天然安全
                if child.resolve().parent != self.plugins_dir.resolve():
                    logger.warning("插件目录越界(目录联接?)，跳过: %s", child)
                    continue
                manifest_path = child / "manifest.json"
                if not manifest_path.exists():
                    continue
                try:
                    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as e:
                    logger.warning("插件目录 %s manifest 解析失败，跳过: %s", child.name, e)
                    continue
                if not isinstance(raw, dict):
                    logger.warning("插件目录 %s manifest 非对象，跳过", child.name)
                    continue
                plugin_id = raw.get("id")
                name = raw.get("name")
                if not isinstance(plugin_id, str) or not plugin_id.strip():
                    logger.warning("插件目录 %s manifest 缺少 id，跳过", child.name)
                    continue
                if not isinstance(name, str) or not name.strip():
                    logger.warning("插件目录 %s manifest 缺少 name，跳过", child.name)
                    continue
                if not _is_safe_id(plugin_id):
                    logger.warning("插件 id 不符合白名单 [A-Za-z0-9._-]，跳过: %r", plugin_id)
                    continue
                if plugin_id in manifests:
                    logger.warning(
                        "插件 id 重复，跳过目录 %s: id %r 已由目录 %s 注册",
                        child.name, plugin_id, dirs[plugin_id].name,
                    )
                    continue
                manifests[plugin_id] = raw
                dirs[plugin_id] = child
                raw_settings = raw.get("settings")
                settings[plugin_id] = raw_settings if isinstance(raw_settings, list) else []

        for bucket in (self._errors, self._instances, self._contexts):
            for key in [k for k in bucket if k not in manifests]:
                bucket.pop(key, None)

        self._manifests = manifests
        self._dirs = dirs
        self._settings = settings
        for plugin_id in manifests:
            self._enabled.setdefault(plugin_id, True)

        ordered = sorted(manifests, key=lambda p: (manifests[p]["name"], p))
        return [self._summary(pid) for pid in ordered]

    def _status(self, plugin_id: str) -> str:
        if not self._is_enabled(plugin_id):
            return "disabled"
        if self._errors.get(plugin_id):
            return "error"
        return "enabled"

    def _summary(self, plugin_id: str) -> dict:
        manifest = self._manifests[plugin_id]
        ctx = self._contexts.get(plugin_id)
        return {
            "id": plugin_id,
            "name": manifest.get("name") or plugin_id,
            "version": manifest.get("version") or "",
            "author": manifest.get("author") or "",
            "icon": manifest.get("icon") or "",
            "description": manifest.get("description") or "",
            "status": self._status(plugin_id),
            "errorMsg": self._errors.get(plugin_id, ""),
            "hasSettings": bool(self._settings.get(plugin_id)),
            "hasContent": bool(ctx is not None and ctx.content),
            "dir": str(self._dirs[plugin_id]),
        }

    # ---------------- 详情 ----------------

    def detail(self, plugin_id) -> dict | None:
        self.scan()
        if plugin_id not in self._manifests:
            return None
        data = self._summary(plugin_id)
        ctx = PluginContext(plugin_id, self._dirs[plugin_id], self._settings.get(plugin_id))
        config = ctx.get_config()
        settings = []
        for item in _filter_settings(self._settings.get(plugin_id), require_valid_type=True):
            key = item["key"]
            settings.append({
                "key": key,
                "label": item.get("label", key),
                "type": item.get("type", "text"),
                "default": item.get("default"),
                "value": config.get(key, item.get("default")),
            })
        data["settings"] = settings
        loaded = self._contexts.get(plugin_id)
        if self._is_enabled(plugin_id) and loaded is not None and not self._errors.get(plugin_id):
            data["contentHtml"] = loaded.content
        else:
            data["contentHtml"] = ""
        return data

    # ---------------- 启停 ----------------

    def set_enabled(self, plugin_id, enabled: bool) -> None:
        self.scan()
        if plugin_id not in self._manifests:
            logger.warning("set_enabled: 未找到插件 %s", plugin_id)
            return
        self._enabled[plugin_id] = bool(enabled)
        try:
            self._write_enabled()
        except OSError:
            logger.error("插件 %s enabled.json 写入失败", plugin_id, exc_info=True)
            raise
        if not enabled:
            self._instances.pop(plugin_id, None)
            self._contexts.pop(plugin_id, None)
            sys.modules.pop(_module_name(plugin_id), None)
        else:
            # enable 立即加载(M3)：不依赖调用方补 load_all；异常被 _load_one 隔离成 error 态
            self._load_one(plugin_id)

    # ---------------- 配置保存 ----------------

    def save_config(self, plugin_id, cfg: dict) -> dict:
        self.scan()
        if plugin_id not in self._manifests:
            return {"success": False, "error": f"插件不存在: {plugin_id}"}
        ctx = PluginContext(plugin_id, self._dirs[plugin_id], self._settings.get(plugin_id))
        try:
            ctx.set_config(cfg)
        except (ValueError, OSError, TypeError) as e:
            logger.warning("插件 %s 配置保存失败: %s", plugin_id, e)
            return {"success": False, "error": str(e)}
        return {"success": True, "error": None}

    # ---------------- 加载 ----------------

    def _import_module(self, plugin_id: str, entry: Path):
        module_name = _module_name(plugin_id)
        spec = importlib.util.spec_from_file_location(module_name, entry)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法为 {entry} 创建模块 spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            # 顶层执行失败不留残留(M8)
            sys.modules.pop(module_name, None)
            raise
        return module

    def _load_one(self, plugin_id: str) -> None:
        self._instances.pop(plugin_id, None)
        self._contexts.pop(plugin_id, None)
        self._errors.pop(plugin_id, None)
        if not self._is_enabled(plugin_id):
            return
        directory = self._dirs[plugin_id]
        entry = directory / "plugin.py"
        ctx = PluginContext(plugin_id, directory, self._settings.get(plugin_id))
        try:
            if not entry.exists():
                raise FileNotFoundError(f"缺少入口文件: {entry}")
            module = self._import_module(plugin_id, entry)
            plugin_cls = getattr(module, "Plugin", None)
            if plugin_cls is None:
                raise AttributeError("plugin.py 未定义 Plugin 类")
            instance = plugin_cls()
            on_load = getattr(instance, "on_load", None)
            if not callable(on_load):
                raise TypeError("Plugin 未定义 on_load(self, ctx)")
            inspect.signature(on_load).bind(ctx)
            on_load(ctx)
        except Exception as e:
            self._errors[plugin_id] = f"{type(e).__name__}: {e}"
            logger.warning("插件 %s 加载失败: %s", plugin_id, self._errors[plugin_id])
            self._instances.pop(plugin_id, None)
            self._contexts.pop(plugin_id, None)
            return
        self._instances[plugin_id] = instance
        self._contexts[plugin_id] = ctx

    def load_all(self) -> None:
        self.scan()
        for plugin_id in sorted(self._manifests):
            self._load_one(plugin_id)

    def reload(self, plugin_id=None) -> None:
        self.scan()
        if plugin_id is None:
            targets = sorted(self._manifests)
        else:
            if plugin_id not in self._manifests:
                logger.warning("reload: 未找到插件 %s", plugin_id)
                return
            targets = [plugin_id]
        for pid in targets:
            self._load_one(pid)

    # ---------------- 卸载 / 目录 ----------------

    def uninstall(self, plugin_id) -> bool:
        self.scan()
        if not _is_safe_id(plugin_id) or plugin_id not in self._manifests:
            return False
        target = self._dirs[plugin_id]
        # 先清理运行时引用(M1)：rmtree 失败也不留悬空实例/上下文/模块
        self._instances.pop(plugin_id, None)
        self._contexts.pop(plugin_id, None)
        sys.modules.pop(_module_name(plugin_id), None)
        try:
            resolved_target = target.resolve()
            if resolved_target.parent != self.plugins_dir.resolve():
                logger.warning("卸载目标越界，拒绝: %s", resolved_target)
                return False
            shutil.rmtree(resolved_target)
        except OSError as e:
            logger.warning("卸载插件 %s 失败: %s", plugin_id, e)
            return False
        for bucket in (
            self._manifests, self._dirs, self._settings,
            self._errors, self._instances, self._contexts,
        ):
            bucket.pop(plugin_id, None)
        if plugin_id in self._enabled:
            self._enabled.pop(plugin_id, None)
            enabled_path = self.plugins_dir / "enabled.json"
            if enabled_path.exists():
                self._write_enabled()
        return True

    def folder_of(self, plugin_id) -> Path | None:
        self.scan()
        if not _is_safe_id(plugin_id) or plugin_id not in self._manifests:
            return None
        p = self._dirs[plugin_id]
        if p.resolve().parent != self.plugins_dir.resolve():
            logger.warning("插件目录越界(目录联接?), 拒绝返回: %s", p)
            return None
        return p

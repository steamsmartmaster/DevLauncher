# -*- coding: utf-8 -*-
"""读写 Minecraft 的 options.txt，并提供一份常用字段目录给 UI 渲染。

options.txt 是 `key:value` 的纯文本行文件，游戏每次启动/退出都会整个重写它。
两个不变量：
  1. 值一律按字符串存。MC 的 bool 写作 true/false、float 带小数点，
     提前按类型解析会在回写时改变格式（如把 0.0 写成 0），
     于是游戏启动后把整份文件按自己的默认值重写，用户改动消失。
  2. 未知键原样保留。keybinds / resourcePacks / skinCustomizations
     之类的大杂烩不该被启动器接管，改一个渲染距离就把它们冲掉不可接受。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

# guiScale 写 0 表示「自动」（游戏按窗口推算），不是把界面缩到看不见
_AUTO = 0

OPTION_SPECS: list[dict] = [
    {"key": "renderDistance", "label": "渲染距离", "type": "int",
     "group": "视图", "default": 12, "minimum": 2, "maximum": 32,
     "hint": "区块数"},
    {"key": "simulationDistance", "label": "模拟距离", "type": "int",
     "group": "视图", "default": 10, "minimum": 2, "maximum": 32,
     "hint": "生物与红石活跃的区块数"},
    {"key": "maxFps", "label": "最大帧率", "type": "int",
     "group": "视图", "default": 120, "minimum": 10, "maximum": 260},
    {"key": "gamma", "label": "亮度", "type": "float",
     "group": "视图", "default": 0.0, "minimum": 0.0, "maximum": 1.0},
    {"key": "fov", "label": "视野", "type": "int",
     "group": "视图", "default": 70, "minimum": 0, "maximum": 120},
    {"key": "guiScale", "label": "界面缩放", "type": "int",
     "group": "视图", "default": _AUTO, "minimum": 0, "maximum": 3,
     "hint": "0 为自动"},
    {"key": "mipmapLevels", "label": "Mipmap 等级", "type": "int",
     "group": "视图", "default": 4, "minimum": 0, "maximum": 4},
    {"key": "fullscreen", "label": "全屏", "type": "bool",
     "group": "视图", "default": False},
    {"key": "enableVsync", "label": "垂直同步", "type": "bool",
     "group": "视图", "default": True},
    {"key": "graphicsMode", "label": "华丽画质", "type": "bool",
     "group": "视图", "default": False,
     "hint": "开销很大，需要支持的显卡"},
    {"key": "ao", "label": "环境光遮蔽", "type": "bool",
     "group": "视图", "default": True},
    {"key": "entityShadows", "label": "生物阴影", "type": "bool",
     "group": "视图", "default": True},
    {"key": "viewBobbing", "label": "视角摇晃", "type": "bool",
     "group": "视图", "default": True},
    {"key": "particles", "label": "粒子效果", "type": "choice",
     "group": "视图", "default": "all", "choices": ("all", "decreased", "minimal")},
    {"key": "renderClouds", "label": "云", "type": "choice",
     "group": "视图", "default": "true", "choices": ("true", "false", "fast")},
    {"key": "entityDistanceScaling", "label": "生物距离缩放", "type": "float",
     "group": "视图", "default": 1.0, "minimum": 0.5, "maximum": 5.0},

    {"key": "chatVisibility", "label": "聊天", "type": "choice",
     "group": "界面", "default": "full",
     "choices": ("full", "commands", "hidden")},
    {"key": "chatOpacity", "label": "聊天不透明度", "type": "float",
     "group": "界面", "default": 1.0, "minimum": 0.0, "maximum": 1.0},
    {"key": "textBackgroundOpacity", "label": "文字背景不透明度", "type": "float",
     "group": "界面", "default": 0.5, "minimum": 0.0, "maximum": 1.0},
    {"key": "chatLines", "label": "聊天行数", "type": "int",
     "group": "界面", "default": 10, "minimum": 0, "maximum": 100},
    {"key": "subtitles", "label": "字幕", "type": "bool",
     "group": "界面", "default": False},
    {"key": "pauseOnLostFocus", "label": "失焦自动暂停", "type": "bool",
     "group": "界面", "default": True},
    {"key": "touchscreen", "label": "触屏模式", "type": "bool",
     "group": "界面", "default": False},
    {"key": "language", "label": "语言", "type": "string",
     "group": "界面", "default": "en_us", "hint": "如 zh_cn"},

    {"key": "musicVolume", "label": "音乐音量", "type": "float",
     "group": "声音", "default": 1.0, "minimum": 0.0, "maximum": 1.0},
    {"key": "soundVolume", "label": "音效音量", "type": "float",
     "group": "声音", "default": 1.0, "minimum": 0.0, "maximum": 1.0},
    {"key": "ambientVolume", "label": "环境音量", "type": "float",
     "group": "声音", "default": 1.0, "minimum": 0.0, "maximum": 1.0},
    {"key": "weatherVolume", "label": "天气音量", "type": "float",
     "group": "声音", "default": 1.0, "minimum": 0.0, "maximum": 1.0},
    {"key": "blockVolume", "label": "方块音量", "type": "float",
     "group": "声音", "default": 1.0, "minimum": 0.0, "maximum": 1.0},
    {"key": "hostileVolume", "label": "敌对生物音量", "type": "float",
     "group": "声音", "default": 1.0, "minimum": 0.0, "maximum": 1.0},
    {"key": "neutralVolume", "label": "中立生物音量", "type": "float",
     "group": "声音", "default": 1.0, "minimum": 0.0, "maximum": 1.0},
    {"key": "playerVolume", "label": "玩家音量", "type": "float",
     "group": "声音", "default": 1.0, "minimum": 0.0, "maximum": 1.0},

    {"key": "mouseSensitivity", "label": "鼠标灵敏度", "type": "float",
     "group": "控制", "default": 0.5, "minimum": 0.0, "maximum": 1.0},
    {"key": "invertMouse", "label": "反转鼠标", "type": "bool",
     "group": "控制", "default": False},
    {"key": "autoJump", "label": "自动跳跃", "type": "bool",
     "group": "控制", "default": False},
    {"key": "sneak", "label": "潜行切换", "type": "bool",
     "group": "控制", "default": False},
    {"key": "sprint", "label": "疾跑切换", "type": "bool",
     "group": "控制", "default": False},
    {"key": "mainHand", "label": "惯用手", "type": "choice",
     "group": "控制", "default": "right", "choices": ("left", "right")},
]

_SPEC_INDEX = {s["key"]: s for s in OPTION_SPECS}


def list_option_specs() -> list[dict]:
    return [dict(s) for s in OPTION_SPECS]


def parse_options(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key:
            data[key] = value
    return data


def format_options(data: Mapping[str, str]) -> str:
    return "".join(f"{k}:{v}\n" for k, v in data.items())


def read_options(path: Path) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    return parse_options(path.read_text(encoding="utf-8", errors="replace"))


def write_options(path: Path, data: Mapping[str, str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        # 游戏自己不备份，误覆盖后无从找回，所以这里替用户备份一份
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(format_options(data), encoding="utf-8")
    os.replace(tmp, path)


def coerce_value(raw: Any, spec: Mapping[str, Any]) -> Any:
    kind = spec["type"]
    default = spec["default"]
    try:
        if kind == "bool":
            if isinstance(raw, bool):
                return raw
            text = str(raw).strip().lower()
            if text in ("true", "false"):
                return text == "true"
        elif kind == "int":
            value = int(float(raw))
            return max(int(spec["minimum"]), min(int(spec["maximum"]), value))
        elif kind == "float":
            value = float(raw)
            return max(float(spec["minimum"]), min(float(spec["maximum"]), value))
        elif kind == "choice":
            text = str(raw).strip()
            if text in spec["choices"]:
                return text
        elif kind == "string":
            text = str(raw).strip()
            return text if text else default
    except (TypeError, ValueError):
        pass
    return default


def build_updates(parsed: Mapping[str, str],
                  updates: Mapping[str, Any]) -> dict[str, str]:
    """把 UI 传来的（带类型的）改动并进已解析的字符串字典。

    只覆盖 UI 明确提到的键，其余（含游戏自己写、启动器不认识的键）原样带走。
    """
    merged = dict(parsed)
    for key, value in updates.items():
        spec = _SPEC_INDEX.get(key)
        coerced = coerce_value(value, spec) if spec else value
        merged[key] = _stringify(coerced)
    return merged


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def options_path(versions: Any, version_id: str) -> Path:
    return Path(versions.get_game_dir(version_id)) / "options.txt"


def spec_for(key: str) -> Optional[dict]:
    spec = _SPEC_INDEX.get(key)
    return dict(spec) if spec else None


def specs_in_group(group: str) -> Sequence[dict]:
    return [dict(s) for s in OPTION_SPECS if s["group"] == group]


def groups() -> list[str]:
    seen: list[str] = []
    for spec in OPTION_SPECS:
        if spec["group"] not in seen:
            seen.append(spec["group"])
    return seen

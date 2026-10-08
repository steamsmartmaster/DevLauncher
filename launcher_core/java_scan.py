# -*- coding: utf-8 -*-
"""Java 安装扫描与版本探测（P0-1）。

IO 全部可注入（exists/scandir/runner），测试 hermetic：
scan_candidates → find_java_exes → detect_java/scan_javas；
required_java_major / recommend_java 按当前 MC 版本推荐。
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Iterable, Mapping, Optional, Sequence

_JAVA_BIN_NAMES = ("java.exe", "javaw.exe", "java")

_VENDOR_DIR_NAMES = (
    "Java", "Eclipse Adoptium", "Temurin", "Microsoft", "Azul",
    "BellSoft", "Amazon Corretto", "Zulu", "Liberica", "Dragonwell",
    "Red Hat", "SapMachine", "JetBrains", "jdk", "jre",
)

_VERSION_RE = re.compile(r'version\s+"([^"]+)"')
_VERSION_LOOSE_RE = re.compile(r"version\s+(\S+)")
_MC_RE = re.compile(r"1\.(\d+)(?:\.(\d+))?")


def scan_candidates(env: Mapping[str, str], minecraft_dir: str = "",
                    extra_roots: Sequence[str] = ()) -> dict:
    """从环境变量派生扫描候选：direct = 直查目录，walk = (目录, 最大深度)。"""
    direct: list[str] = []
    walk: list[tuple[str, int]] = []
    java_home = (env.get("JAVA_HOME") or "").strip()
    if java_home:
        direct.append(os.path.join(java_home, "bin"))
    for part in (env.get("PATH") or "").split(os.pathsep):
        part = part.strip().strip('"')
        if part:
            direct.append(part)
    for root_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = (env.get(root_key) or "").strip()
        if not root:
            continue
        for vendor in _VENDOR_DIR_NAMES:
            walk.append((os.path.join(root, vendor), 4))
            if root_key == "LOCALAPPDATA":
                walk.append((os.path.join(root, "Programs", vendor), 4))
    if minecraft_dir:
        walk.append((os.path.join(minecraft_dir, "runtime"), 6))
    for r in extra_roots:
        if r:
            walk.append((r, 4))
    return {"direct": direct, "walk": walk}


def _os_listdir_names(d: str) -> list[str]:
    return [e.name for e in os.scandir(d)]


def find_java_exes(direct: Iterable[str], walk: Sequence[tuple[str, int]],
                   exists=None, scandir=None) -> list[str]:
    """查找 java 可执行文件。direct 逐个直查；walk 递归下钻（命中即停）。"""
    exists = exists or os.path.exists
    scandir = scandir or _os_listdir_names
    found: list[str] = []

    def probe(d: str) -> Optional[str]:
        for name in _JAVA_BIN_NAMES:
            p = os.path.join(d, name)
            if exists(p):
                return p
        return None

    def descend(d: str, depth: int, max_depth: int):
        hit = probe(d)
        if hit:
            found.append(hit)
            return
        if depth >= max_depth:
            return
        try:
            entries = scandir(d)
        except OSError:
            return
        for name in entries:
            descend(os.path.join(d, name), depth + 1, max_depth)

    for d in direct:
        hit = probe(d)
        if hit:
            found.append(hit)
    for root, max_depth in walk:
        descend(root, 0, max_depth)
    return found


def parse_java_version(text: str):
    """解析 `java -version` 输出 → (major, full) 或 None。1.8.0_392 → 8。"""
    if not text:
        return None
    m = _VERSION_RE.search(text) or _VERSION_LOOSE_RE.search(text)
    if not m:
        return None
    full = m.group(1)
    core = full.split("-")[0].split("+")[0]
    try:
        major = int(core.split(".")[1]) if core.startswith("1.") else int(core.split(".")[0])
    except (IndexError, ValueError):
        return None
    if major <= 0:
        return None
    return major, full


def _run_java_version(path: str) -> str:
    proc = subprocess.run([path, "-version"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=8)
    return (proc.stderr or "") + "\n" + (proc.stdout or "")


def detect_java(path: str, runner=None) -> Optional[dict]:
    """探测单个 java：失败/解析失败返回 None。"""
    try:
        out = (runner or _run_java_version)(path)
    except Exception:
        return None
    parsed = parse_java_version(out or "")
    if not parsed:
        return None
    return {"path": path, "major": parsed[0], "version": parsed[1]}


def scan_javas(direct: Iterable[str], walk: Sequence[tuple[str, int]],
               exists=None, scandir=None, runner=None) -> list[dict]:
    """完整扫描：找 exe → 探测版本 → normcase 去重 → 按 major 降序。"""
    seen: set[str] = set()
    out: list[dict] = []
    for exe in find_java_exes(direct, walk, exists=exists, scandir=scandir):
        key = os.path.normcase(os.path.realpath(exe))
        if key in seen:
            continue
        seen.add(key)
        hit = detect_java(exe, runner=runner)
        if hit:
            out.append(hit)
    out.sort(key=lambda j: (-j["major"], j["path"].lower()))
    return out


def required_java_major(mc_version: str) -> int:
    """MC 版本 → 所需最低 Java 主版本。未知/快照按 21 处理。"""
    m = _MC_RE.match((mc_version or "").strip())
    if not m:
        return 21
    minor = int(m.group(1))
    if minor <= 16:
        return 8
    if minor == 17:
        return 16
    if minor in (18, 19):
        return 17
    if minor == 20:
        return 21 if int(m.group(2) or 0) >= 5 else 17
    return 21


def recommend_java(javas: Iterable[dict], mc_version: str) -> Optional[dict]:
    """推荐 Java：满足要求的最低版本（最贴近需求，避免高版本破坏旧 MC）；
    mc_version 为空时取可用最高版本；无满足项返回 None。"""
    pool = list(javas)
    if not pool:
        return None
    if not mc_version:
        return max(pool, key=lambda j: (j["major"], j["path"]))
    req = required_java_major(mc_version)
    suitable = [j for j in pool if j.get("major", 0) >= req]
    if not suitable:
        return None
    return min(suitable, key=lambda j: (j["major"], j["path"]))

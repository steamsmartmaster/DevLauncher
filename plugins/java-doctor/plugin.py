# -*- coding: utf-8 -*-
import html
import re
import subprocess
from pathlib import Path

from launcher_core.settings import Settings

_VERSION_RE = re.compile(r'(?i)\bversion\s+"?(\d+)(?:\.(\d+))?')
_PREFIX_RE = re.compile(r'(?i)\b(?:openjdk|java)\s+(\d+)')


def parse_java_version(text: str):
    """`java -version` 输出 → 主版本号；识别不出返回 None。

    两种历史写法并存：JDK 9+ 是 `openjdk 17.0.9` / `version "21.0.1"`，
    JDK 8 及更早是 `version "1.8.0_392"`（主版本藏在第二段）。
    """
    if not text:
        return None
    m = _VERSION_RE.search(text)
    if m:
        major = int(m.group(1))
        minor = int(m.group(2) or 0)
        if major == 1 and minor:
            return minor
        return major
    m = _PREFIX_RE.search(text)
    if m:
        return int(m.group(1))
    return None


def required_java(mc_version: str) -> int:
    m = re.match(r"1\.(\d+)", mc_version or "")
    if not m:
        return 17
    minor = int(m.group(1))
    if minor <= 16:
        return 8
    if minor == 17:
        return 16
    if minor == 20:
        parts = (mc_version or "").split(".")
        patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        return 21 if patch >= 5 else 17
    if minor <= 20:
        return 17
    return 21


def evaluate(found, required: int) -> dict:
    if found is None:
        return {"ok": False, "found": None, "required": required,
                "reason": f"无法识别 Java 版本，需要 Java {required}+"}
    if found < required:
        return {"ok": False, "found": found, "required": required,
                "reason": f"Java {found} 过旧，需要 Java {required}+"}
    return {"ok": True, "found": found, "required": required, "reason": ""}


def probe(java_path: str, timeout: float = 8.0):
    path = (java_path or "java").strip()
    if not path:
        path = "java"
    if Path(path).is_file():
        try:
            proc = subprocess.run([path, "-version"], capture_output=True,
                                  text=True, timeout=timeout)
            return parse_java_version((proc.stderr or "") + (proc.stdout or ""))
        except (OSError, subprocess.SubprocessError):
            return None
    try:
        proc = subprocess.run([path, "-version"], capture_output=True,
                              text=True, timeout=timeout,
                              shell=not Path(path).is_file())
        return parse_java_version((proc.stderr or "") + (proc.stdout or ""))
    except (OSError, subprocess.SubprocessError):
        return None


def build_html(result: dict, java_path: str, mc_version: str) -> str:
    status = "通过" if result["ok"] else "不通过"
    found = "未知" if result["found"] is None else f"Java {result['found']}"
    detail = (f"<p>已找到 {html.escape(found)}，满足 Java {result['required']} 要求。</p>"
              if result["ok"] else
              f"<p>{html.escape(result['reason'])}</p>")
    return (
        f"<div class='plugin-content'>"
        f"<h4>Java 体检 · {status}</h4>"
        f"<p>Minecraft {html.escape(mc_version)} 需要 Java {result['required']}，"
        f"当前 {html.escape(found)}。</p>"
        f"{detail}"
        f"<p>使用路径：<code>{html.escape(java_path or '(系统 PATH)')}</code></p>"
        f"</div>"
    )


class Plugin:
    def on_load(self, ctx):
        cfg = ctx.get_config()
        mc_version = str(cfg.get("check_mc_version") or "1.20.4")
        java_path = str(cfg.get("custom_java") or "").strip()
        if not java_path:
            java_path = str(Settings().get("java_path") or "").strip()
        required = required_java(mc_version)
        found = probe(java_path)
        result = evaluate(found, required)
        ctx.register_content(build_html(result, java_path, mc_version))
        ctx.logger.info("java-doctor: found=%s required=%s", found, required)

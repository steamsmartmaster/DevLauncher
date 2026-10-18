# -*- coding: utf-8 -*-
import html
import zipfile
from pathlib import Path

from launcher_core.settings import Settings

LEFTOVER_SUFFIXES = (".part", ".tmp", ".crdownload", ".download", ".bak")


def minecraft_dir() -> Path:
    raw = Settings().get("minecraft_dir")
    return Path(raw) if raw else Path.home() / ".minecraft"


def group_duplicates(names) -> list:
    """大小写折叠分组（Windows 文件系统不区分大小写，`Sodium.jar` 与 `sodium.jar`
    会在同一目录互相覆盖/解压失败，所以即便在 NTFS 上也要按小写归并检测）。"""
    buckets: dict[str, list] = {}
    for n in names:
        buckets.setdefault(str(n).lower(), []).append(n)
    return [v for v in buckets.values() if len(v) > 1]


def audit(mods_dir, min_size_kb: int = 0) -> dict:
    mods_dir = Path(mods_dir)
    out = {"total": 0, "bytes": 0, "invalid": [], "empty_files": [],
           "leftovers": [], "duplicates": [], "small": []}
    if not mods_dir.is_dir():
        return out
    min_size = max(0, int(min_size_kb or 0)) * 1024
    jar_names = []
    for entry in sorted(mods_dir.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        if name.lower().endswith(LEFTOVER_SUFFIXES):
            out["leftovers"].append(name)
            continue
        if not name.lower().endswith(".jar"):
            continue
        jar_names.append(name)
        size = entry.stat().st_size
        out["bytes"] += size
        if size == 0:
            out["empty_files"].append(name)
            continue
        if not zipfile.is_zipfile(entry):
            out["invalid"].append(name)
            continue
        out["total"] += 1
        if min_size and size < min_size:
            out["small"].append(name)
    out["duplicates"] = group_duplicates(jar_names)
    return out


def _row(label: str, items: list) -> str:
    if not items:
        return ""
    names = ", ".join(html.escape(str(x)) for x in items)
    return f"<li><b>{html.escape(label)}</b> ({len(items)}): {names}</li>"


def build_html(result: dict, mods_dir: str) -> str:
    problems = []
    problems.append(_row("无效 jar（不是 zip）", result["invalid"]))
    problems.append(_row("零字节文件", result["empty_files"]))
    problems.append(_row("下载残留", result["leftovers"]))
    problems.append(_row("大小写重名", ["/".join(g) for g in result["duplicates"]]))
    problems.append(_row("体积偏小", result["small"]))
    body = "".join(p for p in problems if p)
    status = "发现问题" if body else "未发现问题"
    kb = result["bytes"] / 1024
    if body:
        detail = f"<ul>{body}</ul>"
    else:
        detail = "<p>目录干净：没有无效 jar、残留文件或重名。</p>"
    return (
        f"<div class='plugin-content'>"
        f"<h4>模组目录体检 · {status}</h4>"
        f"<p>目录：<code>{html.escape(mods_dir)}</code></p>"
        f"<p>已安装 {result['total']} 个模组，共 {kb:.1f} KB</p>"
        f"{detail}</div>"
    )


class Plugin:
    def on_load(self, ctx):
        cfg = ctx.get_config()
        mc = minecraft_dir()
        candidates = [mc / "versions" / name / "mods"
                      for name in sorted(p.name for p in (mc / "versions").glob("*")
                                         if p.is_dir())]
        candidates.append(mc / "mods")
        total = 0
        sections = []
        for mods in candidates:
            if not mods.is_dir():
                continue
            res = audit(mods, cfg.get("min_size_kb", 1))
            total += res["total"]
            sections.append(build_html(res, str(mods)))
        if not sections:
            sections.append(
                "<div class='plugin-content'><p>没有找到任何 mods 目录。</p></div>")
        ctx.register_content(
            f"<div class='plugin-content'><h4>共扫描到 {total} 个模组</h4></div>"
            + "".join(sections)
        )
        ctx.logger.info("mods-doctor 扫描完成, 模组数=%s", total)

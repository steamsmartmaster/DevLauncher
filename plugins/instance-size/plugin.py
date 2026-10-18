# -*- coding: utf-8 -*-
import html
from pathlib import Path

from launcher_core.settings import Settings

BREAKDOWN_DIRS = ("mods", "config", "saves", "resourcepacks", "shaderpacks",
                  "logs", "screenshots", "stats")


def minecraft_dir() -> Path:
    raw = Settings().get("minecraft_dir")
    return Path(raw) if raw else Path.home() / ".minecraft"


def dir_size(path) -> int:
    path = Path(path)
    if not path.is_dir():
        return 0
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                continue
    return total


def _breakdown(root: Path) -> dict:
    out = {}
    for name in BREAKDOWN_DIRS:
        sub = root / name
        if sub.is_dir():
            out[name] = dir_size(sub)
    root_files = 0
    for f in root.iterdir():
        if f.is_file():
            try:
                root_files += f.stat().st_size
            except OSError:
                continue
    if root_files:
        out["files"] = root_files
    return out


def instance_report(name: str, version_dir: Path) -> dict:
    breakdown = _breakdown(version_dir)
    return {"name": name, "total_bytes": sum(breakdown.values()),
            "breakdown": breakdown}


def report(mc_dir) -> dict:
    mc = Path(mc_dir)
    if not mc.is_dir():
        return {"global": {"total_bytes": 0, "breakdown": {}},
                "instances": [], "grand_total": 0}
    global_breakdown = _breakdown(mc)
    instances = []
    versions_root = mc / "versions"
    if versions_root.is_dir():
        for child in sorted(versions_root.iterdir()):
            if child.is_dir():
                instances.append(instance_report(child.name, child))
    g_total = sum(global_breakdown.values())
    i_total = sum(i["total_bytes"] for i in instances)
    return {"global": {"total_bytes": g_total, "breakdown": global_breakdown},
            "instances": instances, "grand_total": g_total + i_total}


def human(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def build_html(data: dict, show_global: bool, show_top: int) -> str:
    rows = []
    if show_global:
        gb = data["global"]
        detail = ", ".join(f"{html.escape(k)}={human(v)}"
                           for k, v in sorted(gb["breakdown"].items(), key=lambda x: -x[1]))
        rows.append(f"<li><b>全局</b> {human(gb['total_bytes'])}"
                    + (f" — {detail}" if detail else "") + "</li>")
    ranked = sorted(data["instances"], key=lambda i: -i["total_bytes"])
    for inst in ranked[:max(0, int(show_top or 0))]:
        detail = ", ".join(f"{html.escape(k)}={human(v)}"
                           for k, v in sorted(inst["breakdown"].items(), key=lambda x: -x[1]))
        rows.append(f"<li><b>{html.escape(inst['name'])}</b> "
                    f"{human(inst['total_bytes'])}"
                    + (f" — {detail}" if detail else "") + "</li>")
    if not rows:
        body = "<p>没有可统计的实例。</p>"
    else:
        body = "<ul>" + "".join(rows) + "</ul>"
    return (
        f"<div class='plugin-content'>"
        f"<h4>总计 {human(data['grand_total'])}</h4>{body}</div>"
    )


class Plugin:
    def on_load(self, ctx):
        cfg = ctx.get_config()
        data = report(minecraft_dir())
        ctx.register_content(build_html(
            data,
            bool(cfg.get("show_global", True)),
            cfg.get("show_top", 10),
        ))
        ctx.logger.info("instance-size 统计完成, 实例数=%s", len(data["instances"]))

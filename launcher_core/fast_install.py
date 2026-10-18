"""版本安装提速：把 mll 串行的尾部相位与库/资源相位并跑。

mll 的 do_version_install 顺序是 libs → assets → logging → client jar → JVM
运行时，其中后两项各是几十 MB 的单文件，而前两项本身已经 32 路并行。也就是说
整条安装时间几乎总是被"最后那两个串行大文件"拖住。这里让它们并发执行，
进度由 MergedProgress 归一后交给上游。

Forge/NeoForge 等带 inheritsFrom 的版本不走本路径：它们的父版本安装、
natives 解压与 jar 复制都依赖 mll 的顺序语义，改顺序风险远大于收益。
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, Optional

from minecraft_launcher_lib import install as _mll_install
from minecraft_launcher_lib import runtime as _mll_runtime
from minecraft_launcher_lib.exceptions import VersionNotFound

from . import net

logger = logging.getLogger(__name__)

MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"

mll_install_minecraft_version = _mll_install.install_minecraft_version
install_libraries = _mll_install.install_libraries
install_assets = _mll_install.install_assets
install_jvm_runtime = _mll_runtime.install_jvm_runtime

_CONFIG = {"workers": None, "proxy": ""}
_UNSET = object()


def configure(workers=_UNSET, proxy=_UNSET) -> None:
    """下载参数（并发数、代理）。proxy 同时写进环境变量，mll 内部的
    requests 走 trust_env，这样它那些不经过本模块的下载也一并走代理。

    传 None 表示清回默认；省略参数表示该项不变（两者不能混用）。"""
    if workers is not _UNSET:
        if workers is None:
            _CONFIG["workers"] = None
        else:
            workers = int(workers)
            if workers < 1:
                raise ValueError("download_workers 必须 >= 1，实际 %s" % workers)
            _CONFIG["workers"] = workers
    if proxy is not _UNSET:
        _CONFIG["proxy"] = str(proxy).strip()
    net.apply_env_proxy(_CONFIG["proxy"])


def download_config() -> dict:
    return dict(_CONFIG)


class MergedProgress:
    """把并发相位的 setMax/setProgress 归一成上游熟悉的"单相位 0..100"。

    mll 的契约是每个相位各自 setMax→setProgress，隐含相位串行。多相位并发时
    两路 setProgress 会互相覆盖、setMax 会让相位序号跳变。对上游只报一次
    setMax(100) 之后一律报合并百分比，上游逻辑（main.py 的进度条）无需感知
    并发。进度只增不减：新相位加入会稀释分子，但用户不该看到条子倒退。
    """

    def __init__(self, callback: Optional[dict] = None) -> None:
        self._cb = callback or {}
        self._lock = threading.Lock()
        self._max: dict[str, int] = {}
        self._cur: dict[str, int] = {}
        self._best = 0.0
        self._announced = False
        self._emitted = -1

    def phase(self, name: str) -> dict:
        return {
            "setStatus": self.set_status,
            "setMax": lambda m, n=name: self._set_max(n, m),
            "setProgress": lambda p, n=name: self._set_progress(n, p),
        }

    def set_status(self, msg) -> None:
        fn = self._cb.get("setStatus")
        if fn:
            fn(str(msg))

    def _set_max(self, name: str, max_count) -> None:
        with self._lock:
            self._max[name] = max(1, int(max_count))
            pct = self._merge_locked()
            announce = self._take_announce(pct)
        self._emit(pct, announce)

    def _set_progress(self, name: str, current) -> None:
        with self._lock:
            self._cur[name] = max(0, int(current))
            pct = self._merge_locked()
            announce = self._take_announce(pct)
        self._emit(pct, announce)

    def _merge_locked(self) -> Optional[float]:
        total = sum(self._max.values())
        if total <= 0:
            return None
        done = sum(min(self._cur.get(n, 0), mx) for n, mx in self._max.items())
        pct = max(0.0, min(100.0, done * 100.0 / total))
        self._best = max(self._best, pct)
        return self._best

    def _take_announce(self, pct: Optional[float]) -> bool:
        if pct is None or self._announced:
            return False
        self._announced = True
        return True

    def _emit(self, pct: Optional[float], announce: bool) -> None:
        if pct is None:
            return
        if announce:
            fn = self._cb.get("setMax")
            if fn:
                fn(100)
        value = int(round(pct))
        if value == self._emitted:
            return
        self._emitted = value
        fn = self._cb.get("setProgress")
        if fn:
            fn(value)

    def finish(self) -> None:
        with self._lock:
            self._best = 100.0
            announce = self._take_announce(self._best)
        self._emit(100.0, announce)


def run_phases(tasks: Iterable[Callable[[], None]]) -> None:
    """并发跑完所有相位，第一个异常重新抛出。"""
    tasks = list(tasks)
    if not tasks:
        return
    errors: list[BaseException] = []

    def _run(task: Callable[[], None]) -> None:
        try:
            task()
        except BaseException as exc:  # noqa: BLE001 - 汇总后统一抛第一个
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        for _ in pool.map(_run, tasks):
            pass
    if errors:
        raise errors[0]


def tail_jobs(data: dict, minecraft_directory) -> list[tuple[str, Path, str]]:
    """客户端 jar 与日志配置：mll 排在最后、逐个串行下载的两项。"""
    mc = Path(minecraft_directory)
    jobs: list[tuple[str, Path, str]] = []
    downloads = data.get("downloads") or {}
    client = downloads.get("client") or {}
    if client.get("url"):
        jobs.append((client["url"],
                     mc / "versions" / data.get("id", "") / (data.get("id", "") + ".jar"),
                     client.get("sha1") or ""))
    log_file = ((data.get("logging") or {}).get("client") or {}).get("file") or {}
    if log_file.get("url"):
        jobs.append((log_file["url"],
                     mc / "assets" / "log_configs" / (log_file.get("id") or ""),
                     log_file.get("sha1") or ""))
    return jobs


def download_tail(data: dict, minecraft_directory, phase: dict,
                  session=None) -> None:
    """尾部按字节报进度，避免 30MB 的 jar 和 2KB 的日志配置等权跳变。"""
    jobs = tail_jobs(data, minecraft_directory)
    if not jobs:
        return
    total = sum(_size_of(dest) for _u, dest, _s in jobs) or 1
    done = 0
    phase["setMax"](total)
    for url, dest, sha1 in jobs:
        def _cb(finished: int, _total: int, base: int = done) -> None:
            phase["setProgress"](min(total, base + finished))
        if not net.download_file(url, dest, sha1=sha1, session=session,
                                 callback=_cb):
            raise RuntimeError("下载失败: %s" % dest.name)
        done = _size_of(dest)
        phase["setProgress"](min(total, done))


def _size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def resolve_version_json(version: str, minecraft_directory,
                         session=None) -> dict:
    """读取版本 JSON，缺失时查官方 manifest 并下载（带 sha1 与超时）。"""
    dest = Path(minecraft_directory) / "versions" / version / (version + ".json")
    if dest.is_file() and dest.stat().st_size:
        return json.loads(dest.read_text(encoding="utf-8-sig"))

    session = session or net.build_session()
    resp = session.get(MANIFEST_URL, timeout=30)
    try:
        resp.raise_for_status()
        entry = next((i for i in resp.json().get("versions", [])
                      if i.get("id") == version), None)
        if entry is None:
            raise VersionNotFound(version)
        net.download_file(entry["url"], dest,
                          sha1=entry.get("sha1") or "", session=session)
    finally:
        closer = getattr(resp, "close", None)
        if callable(closer):
            closer()
    return json.loads(dest.read_text(encoding="utf-8-sig"))


def fast_install(version: str, minecraft_directory, callback: Optional[dict] = None,
                 workers: Optional[int] = None, proxy: Optional[str] = None,
                 session=None) -> None:
    """安装一个原版版本：尾部与库/资源并发，进度合并后上报。"""
    if workers is None:
        workers = _CONFIG["workers"]
    if proxy is None:
        proxy = _CONFIG["proxy"]
    if proxy:
        net.apply_env_proxy(proxy)
    session = session or net.build_session(proxy=proxy)

    data = resolve_version_json(version, minecraft_directory, session=session)
    mp = MergedProgress(callback)
    if "inheritsFrom" in data:
        mll_install_minecraft_version(version, str(minecraft_directory),
                                      callback=mp.phase("mll"))
        mp.finish()
        return

    mc = str(minecraft_directory)
    lib_phase, asset_phase, runtime_phase = (mp.phase("libraries"),
                                             mp.phase("assets"),
                                             mp.phase("runtime"))
    client_phase = mp.phase("client")

    tasks = [
        lambda: (install_libraries(data["id"], data.get("libraries", []), mc,
                                   lib_phase, max_workers=workers),
                 install_assets(data, mc, asset_phase, max_workers=workers)),
        lambda: download_tail(data, mc, client_phase, session=session),
    ]
    java = (data.get("javaVersion") or {}).get("component")
    if java:
        tasks.append(lambda: install_jvm_runtime(java, mc, runtime_phase,
                                                 max_workers=workers))

    mp.set_status("Install java runtime" if java else "Installation")
    run_phases(tasks)
    mp.finish()


__all__ = [
    "MergedProgress",
    "configure",
    "download_config",
    "fast_install",
    "run_phases",
    "tail_jobs",
    "download_tail",
    "resolve_version_json",
    "VersionNotFound",
]

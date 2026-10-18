"""共享 HTTP 层：代理、重试、断点友好的原子下载。

为什么单独一个模块：仓库里 api_modrinth / api_curseforge / modpack_importer /
api_modloaders 各自 new 一个 requests.Session，代理与重试得逐处改；集中到这里
后设置项只写一次就能覆盖全部出站请求，包括 minecraft_launcher_lib 内部的
requests 调用（它走 trust_env，会读下面写进 os.environ 的代理）。
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Callable, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

USER_AGENT = "DevLauncher/1.0"
CHUNK = 1 << 16
TIMEOUT = (10, 60)


def build_session(proxy: str = "", retries: int = 3,
                  backoff: float = 0.6) -> requests.Session:
    """带重试与可选代理的 Session。

    只对幂等方法重试——POST（如皮肤上传）重放可能造成重复写入，交给调用方处理。
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:
        retry = Retry(
            total=retries, connect=retries, read=retries, status=retries,
            backoff_factor=backoff,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            raise_on_status=False,
        )
    except TypeError:
        retry = Retry(
            total=retries, connect=retries, read=retries, status=retries,
            backoff_factor=backoff,
            status_forcelist=(429, 500, 502, 503, 504),
            method_whitelist=frozenset({"GET", "HEAD"}),
            raise_on_status=False,
        )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=32, pool_maxsize=32)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


def apply_env_proxy(proxy: str) -> None:
    """把代理写进环境变量，让没经过 build_session 的第三方调用也走代理。"""
    for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        if proxy:
            os.environ[key] = proxy
        else:
            os.environ.pop(key, None)


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def is_fresh(dest: Path, sha1: str) -> bool:
    """已有文件哈希相符则跳过下载——mll 的校验语义是 sha1 为空即不校验。"""
    if not sha1 or not dest.is_file():
        return False
    try:
        return sha1_of(dest).lower() == sha1.lower()
    except OSError:
        return False


def _download_attempt(url: str, tmp: Path, session: requests.Session,
                      allow_resume: bool, callback, timeout) -> None:
    """单次 GET 写入 tmp，任何失败都抛出交给外层重试。

    续传的两个坑都在这里：
      * Range 只在断点存在时发；416 说明断点已越界，删掉片段后必须**不再带
        Range** 重来，否则永远 416；
      * 服务器忽略 Range 回 200 时，已下载的前缀必须作废改写（wb），否则
        两段字节拼出的文件是坏的，而哈希校验只在最后跑一次。
    """
    start = 0
    headers = {}
    mode = "wb"
    if allow_resume and tmp.is_file():
        start = tmp.stat().st_size
        if start:
            headers["Range"] = "bytes=%d-" % start
            mode = "ab"

    resp = session.get(url, stream=True, timeout=timeout, headers=headers)
    if resp.status_code == 416:
        resp.close()
        if tmp.exists():
            os.remove(tmp)
        _download_attempt(url, tmp, session, False, callback, timeout)
        return

    resp.raise_for_status()
    if start and resp.status_code != 206:
        start, mode = 0, "wb"

    total = int(resp.headers.get("content-length", 0) or 0)
    total_all = start + total
    downloaded = start
    with open(tmp, mode) as f:
        for chunk in resp.iter_content(CHUNK):
            if not chunk:
                continue
            f.write(chunk)
            downloaded += len(chunk)
            if callback and total_all > 0:
                callback(downloaded, total_all)


def _discard(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def download_file(url: str, dest, sha1: str = "",
                  session: Optional[requests.Session] = None,
                  callback: Optional[Callable[[int, int], None]] = None,
                  timeout=TIMEOUT, retries: int = 3) -> bool:
    """下载到 `dest.part` 再原子替换，断流按 Range 续传，最后按 sha1 验收。

    callback(done, total) 收的是**累计**字节数（含续传前缀），因此跨重试仍然
    单调不回跳——进度条不回跳就是靠这个约定。

    返回 True 表示目标已是可用文件；哈希不符或重试耗尽返回 False 且不留垃圾。
    网络异常不再向上抛：调用方（安装器/皮肤上传）拿到 False 就能统一走失败分支。
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")

    if is_fresh(dest, sha1):
        if callback:
            total = dest.stat().st_size
            callback(total, total)
        return True

    own = session is None
    session = session or build_session()
    ok = False
    try:
        for attempt in range(1, max(1, retries) + 1):
            try:
                _download_attempt(url, tmp, session, attempt > 1,
                                  callback, timeout)
                ok = True
                break
            except Exception as exc:  # noqa: BLE001 - 统一转成 False
                logger.warning("download %s attempt %d/%d: %s",
                               dest.name, attempt, retries, exc)
    finally:
        if own:
            session.close()

    if not ok:
        _discard(tmp)
        return False

    if sha1 and not is_fresh(tmp, sha1):
        logger.warning("hash mismatch %s expect=%s", dest.name, sha1)
        _discard(tmp)
        return False

    os.replace(tmp, dest)
    return True

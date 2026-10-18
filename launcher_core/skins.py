"""Minecraft 皮肤 / 披风（Minecraft Services API）。

只对微软正式号开放；离线号 access_token 固定为 "offline_token"（见
auth.py），调用一律前置拦截，避免无意义的 401。
披风只能在"已拥有"的里装备/隐藏，服务端没有自定义披风上传接口。
"""
import struct
from pathlib import Path
from typing import Callable, Optional

from . import net, tokens

PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
SKINS_URL = PROFILE_URL + "/skins"
CAPES_URL = PROFILE_URL + "/capes/active"
OFFLINE_TOKEN = "offline_token"
PNG_SIG = b"\x89PNG\r\n\x1a\n"
VALID_SIZES = ((64, 64), (64, 32))
VALID_VARIANTS = ("slim", "classic")


class SkinError(RuntimeError):
    pass


def is_offline(access_token: Optional[str]) -> bool:
    return not access_token or access_token == OFFLINE_TOKEN


def png_size(path) -> tuple[int, int]:
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        raise SkinError("读不到图片: %s" % e)
    if len(raw) < 24 or raw[:8] != PNG_SIG or raw[12:16] != b"IHDR":
        raise SkinError("不是有效的 PNG 图片")
    return struct.unpack(">II", raw[16:24])


def validate_png(path) -> tuple[int, int]:
    w, h = png_size(path)
    if (w, h) not in VALID_SIZES:
        raise SkinError("皮肤必须是 64x64 或 64x32，当前 %dx%d" % (w, h))
    return w, h


def _headers(access_token: Optional[str]) -> dict:
    if is_offline(access_token):
        raise SkinError("离线账号无法更改皮肤/披风，请先登录微软账号")
    return {"Authorization": "Bearer %s" % access_token}


def _check(resp) -> dict:
    if resp.status_code < 300:
        try:
            return resp.json()
        except ValueError:
            return {}
    msg = ""
    try:
        body = resp.json()
        msg = body.get("errorMessage") or body.get("error") or ""
    except ValueError:
        msg = (resp.text or "")[:200]
    raise SkinError("HTTP %d: %s" % (resp.status_code, msg or resp.reason))


def _request(session, method: str, url: str, headers: dict, **kw):
    session = session or net.build_session()
    resp = session.request(method, url, headers=headers, timeout=30, **kw)
    return _check(resp)


def list_profile(access_token: Optional[str], session=None) -> dict:
    data = _request(session, "GET", PROFILE_URL, _headers(access_token))
    return {
        "name": data.get("name", ""),
        "id": data.get("id", ""),
        "skins": list(data.get("skins") or []),
        "capes": list(data.get("capes") or []),
    }


def upload_skin(access_token: Optional[str], path, variant: str = "slim",
                session=None) -> dict:
    headers = _headers(access_token)
    if variant not in VALID_VARIANTS:
        raise SkinError("variant 只能是 slim 或 classic，实际 %s" % variant)
    validate_png(path)
    p = Path(path)
    with open(p, "rb") as fh:
        files = {"file": (p.name, fh, "image/png")}
        form = {"variant": variant}
        return _request(session, "POST", SKINS_URL, headers,
                        data=form, files=files)


def equip_cape(access_token: Optional[str], cape_id: str, session=None) -> dict:
    if not cape_id:
        raise SkinError("缺少 capeId")
    return _request(session, "PUT", CAPES_URL, _headers(access_token),
                    json={"capeId": cape_id})


def hide_cape(access_token: Optional[str], session=None) -> dict:
    return _request(session, "DELETE", CAPES_URL, _headers(access_token))


def is_unauthorized(exc: Exception) -> bool:
    """True 当且仅当 SkinError 且错误消息里带 HTTP 401。"""
    return isinstance(exc, SkinError) and "HTTP 401" in str(exc)


def ensure_fresh_token(access_token: str,
                       refresh: Callable[[], Optional[str]]) -> str:
    """请求前的主动刷新：本地判定 JWT 已过期才调 refresh()。

    离线令牌原样返回；refresh 失败（None/空）时保留原令牌，交给
    call_with_refresh 的 401 兜底处理。
    """
    if is_offline(access_token):
        return access_token
    if tokens.is_expired(access_token):
        new_token = refresh()
        if new_token:
            return new_token
    return access_token


def call_with_refresh(call: Callable[[str], dict], access_token: str,
                      refresh: Callable[[], Optional[str]]) -> dict:
    """先按原令牌执行；收到 401 时刷新一次并用新令牌重试，且只重试一次。

    刷新失败（None/空/与旧令牌相同）时抛出统一的"登录已过期"错误并
    chained 原始 401；非 401 的 SkinError 原样透传。
    """
    try:
        return call(access_token)
    except SkinError as exc:
        if not is_unauthorized(exc):
            raise
        new_token = refresh()
        if not new_token or new_token == access_token:
            raise SkinError("登录已过期，请重新登录") from exc
        return call(new_token)


__all__ = [
    "SkinError",
    "is_offline",
    "png_size",
    "validate_png",
    "list_profile",
    "upload_skin",
    "equip_cape",
    "hide_cape",
    "is_unauthorized",
    "ensure_fresh_token",
    "call_with_refresh",
    "PROFILE_URL",
    "SKINS_URL",
    "CAPES_URL",
    "OFFLINE_TOKEN",
]

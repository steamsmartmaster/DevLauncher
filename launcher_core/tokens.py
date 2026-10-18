"""JWT 过期时间的本地判定（不联网）。

皮肤/披风请求发出前，先看 access_token 自带的 exp 声明决定是否要先刷新；
这里只做 base64url 解码 + JSON 解析，任何畸形输入（非 JWT、离线标记、
坏 base64、缺 exp、非 dict payload）一律返回 None，绝不抛异常。
"""
import base64
import json
import time


def jwt_expiry(token: str) -> int | None:
    """取 JWT payload 里的 exp（秒级时间戳）；解析不了返回 None。"""
    try:
        segments = token.split(".")
        if len(segments) != 3:
            return None
        payload_segment = segments[1]
        # JWT 用无填充的 base64url，补齐 "=" 再解码
        payload_segment += "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_segment))
        if not isinstance(payload, dict):
            return None
        return int(payload["exp"])
    except Exception:
        return None


def is_expired(token: str, now: float | None = None, skew: int = 60) -> bool:
    """exp 已知且 exp <= now + skew 视为过期（提前 skew 秒刷新）；exp 未知一律 False。"""
    exp = jwt_expiry(token)
    if exp is None:
        return False
    if now is None:
        now = time.time()
    return exp <= now + skew


__all__ = [
    "jwt_expiry",
    "is_expired",
]

import base64
import json
import struct
from pathlib import Path

import pytest

from launcher_core import skins
from launcher_core.skins import SkinError

TOKEN = "eyJhbGciOiJSUzI1NiJ9.test"


def _jwt(payload: dict) -> str:
    def seg(obj):
        raw = json.dumps(obj).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return "%s.%s.%s" % (seg({"alg": "HS256"}), seg(payload), "sig")


def make_png(path, w=64, h=64) -> Path:
    ihdr = struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
    data = (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + ihdr + struct.pack(">I", 0))
    p = Path(path)
    p.write_bytes(data)
    return p


class _Resp:
    def __init__(self, status=200, payload=None, text="", reason="OK"):
        self.status_code = status
        self.payload = payload
        self.text = text
        self.reason = reason

    def json(self):
        if self.payload is None:
            raise ValueError("no json")
        return self.payload


class _Sess:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kw):
        files = kw.get("files") or {}
        for key, (name, fh, ctype) in files.items():
            files[key] = (name, fh.read(), ctype)
        self.calls.append({"method": method, "url": url, **kw})
        return self.responses.pop(0)


# ---------- 尺寸校验 ----------

def test_validate_png_accepts_modern_and_legacy(tmp_path):
    assert skins.validate_png(make_png(tmp_path / "a.png", 64, 64)) == (64, 64)
    assert skins.validate_png(make_png(tmp_path / "b.png", 64, 32)) == (64, 32)


def test_validate_png_rejects_wrong_size(tmp_path):
    with pytest.raises(SkinError, match="64x64"):
        skins.validate_png(make_png(tmp_path / "c.png", 32, 32))


def test_validate_png_rejects_non_png(tmp_path):
    p = tmp_path / "d.png"
    p.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    with pytest.raises(SkinError, match="PNG"):
        skins.validate_png(p)


def test_validate_png_missing_file(tmp_path):
    with pytest.raises(SkinError, match="读不到"):
        skins.validate_png(tmp_path / "nope.png")


# ---------- 上传 ----------

def test_upload_skin_sends_multipart(tmp_path):
    p = make_png(tmp_path / "skin.png")
    s = _Sess(_Resp(200, {"skins": []}))
    out = skins.upload_skin(TOKEN, p, variant="slim", session=s)

    assert out == {"skins": []}
    call = s.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == skins.SKINS_URL
    assert call["headers"]["Authorization"] == "Bearer " + TOKEN
    assert call["data"] == {"variant": "slim"}
    name, body, ctype = call["files"]["file"]
    assert name == "skin.png"
    assert ctype == "image/png"
    assert body[:8] == b"\x89PNG\r\n\x1a\n", "必须把文件本体读进 multipart"


def test_upload_skin_rejects_unknown_variant(tmp_path):
    p = make_png(tmp_path / "skin.png")
    with pytest.raises(SkinError, match="slim"):
        skins.upload_skin(TOKEN, p, variant="normal", session=_Sess())


def test_upload_skin_skips_api_when_png_invalid(tmp_path):
    with pytest.raises(SkinError, match="64x64"):
        skins.upload_skin(TOKEN, make_png(tmp_path / "x.png", 16, 16),
                          session=_Sess())


# ---------- 离线号 ----------

@pytest.mark.parametrize("token", ["", None, skins.OFFLINE_TOKEN])
def test_offline_token_is_rejected_before_any_request(tmp_path, token):
    p = make_png(tmp_path / "skin.png")
    s = _Sess()
    with pytest.raises(SkinError, match="离线"):
        skins.list_profile(token, session=s)
    with pytest.raises(SkinError, match="离线"):
        skins.upload_skin(token, p, session=s)
    with pytest.raises(SkinError, match="离线"):
        skins.equip_cape(token, "cape", session=s)
    with pytest.raises(SkinError, match="离线"):
        skins.hide_cape(token, session=s)
    assert s.calls == [], "离线号不允许发出任何请求"


# ---------- 披风 ----------

def test_equip_cape_sends_json():
    s = _Sess(_Resp(200, {"capes": [{"state": "ACTIVE"}]}))
    out = skins.equip_cape(TOKEN, "cape-1", session=s)
    assert out == {"capes": [{"state": "ACTIVE"}]}
    assert s.calls[0]["method"] == "PUT"
    assert s.calls[0]["json"] == {"capeId": "cape-1"}


def test_equip_cape_requires_id():
    with pytest.raises(SkinError, match="capeId"):
        skins.equip_cape(TOKEN, "", session=_Sess())


def test_hide_cape_deletes():
    s = _Sess(_Resp(200, {}))
    skins.hide_cape(TOKEN, session=s)
    assert s.calls[0]["method"] == "DELETE"


# ---------- 读取与错误透传 ----------

def test_list_profile_normalizes():
    s = _Sess(_Resp(200, {"name": "Steve", "id": "abc",
                          "skins": [{"alias": "SLIM"}],
                          "capes": [{"alias": "MIGRATION"}]}))
    out = skins.list_profile(TOKEN, session=s)
    assert out["name"] == "Steve"
    assert len(out["skins"]) == 1
    assert len(out["capes"]) == 1
    assert s.calls[0]["method"] == "GET"


def test_api_error_is_surfaced():
    s = _Sess(_Resp(400, {"errorMessage": "Player does not own the requested cape"}))
    with pytest.raises(SkinError, match="does not own"):
        skins.equip_cape(TOKEN, "nope", session=s)


def test_http_error_without_json_body():
    s = _Sess(_Resp(401, None, text="<html>login</html>", reason="Unauthorized"))
    with pytest.raises(SkinError, match="401"):
        skins.list_profile(TOKEN, session=s)


# ---------- 令牌过期与 401 刷新重试 ----------

def _unauthorized_resp():
    return _Resp(401, {"error": "UnauthorizedOperationException"},
                 reason="Unauthorized")


def test_is_unauthorized_only_matches_skin_error_401():
    assert skins.is_unauthorized(SkinError("HTTP 401: Unauthorized")) is True
    assert skins.is_unauthorized(SkinError("HTTP 500: Server Error")) is False
    assert skins.is_unauthorized(RuntimeError("HTTP 401: Unauthorized")) is False


def test_call_with_refresh_retries_once_with_new_token():
    s = _Sess(_unauthorized_resp(), _Resp(200, {"name": "Steve"}))
    seen = []

    def call(token):
        seen.append(token)
        return skins.list_profile(token, session=s)

    out = skins.call_with_refresh(call, TOKEN, lambda: "new-token")

    assert out == {"name": "Steve", "id": "", "skins": [], "capes": []}
    assert seen == [TOKEN, "new-token"], "调用方必须被调两次，且第二次用新令牌"
    assert s.calls[0]["headers"]["Authorization"] == "Bearer " + TOKEN
    assert s.calls[1]["headers"]["Authorization"] == "Bearer new-token"


def test_call_with_refresh_raises_exact_message_when_refresh_returns_none():
    s = _Sess(_unauthorized_resp())

    def call(token):
        return skins.list_profile(token, session=s)

    with pytest.raises(SkinError) as ei:
        skins.call_with_refresh(call, TOKEN, lambda: None)
    assert str(ei.value) == "登录已过期，请重新登录"
    assert isinstance(ei.value.__cause__, SkinError), "必须 chained 原始 401"
    assert len(s.calls) == 1, "刷新失败不允许重试"


def test_call_with_refresh_raises_when_refresh_returns_same_token():
    s = _Sess(_unauthorized_resp())

    def call(token):
        return skins.list_profile(token, session=s)

    with pytest.raises(SkinError, match="^登录已过期，请重新登录$"):
        skins.call_with_refresh(call, TOKEN, lambda: TOKEN)


def test_call_with_refresh_propagates_non_401_and_skips_refresh():
    s = _Sess(_Resp(500, {"errorMessage": "Server Error"}, reason="Server Error"))
    refresh_calls = []

    def refresh():
        refresh_calls.append(1)
        return "new-token"

    with pytest.raises(SkinError, match="HTTP 500"):
        skins.call_with_refresh(
            lambda token: skins.list_profile(token, session=s), TOKEN, refresh)
    assert refresh_calls == [], "非 401 错误不允许触发刷新"
    assert len(s.calls) == 1


def test_call_with_refresh_does_not_retry_twice():
    s = _Sess(_unauthorized_resp(), _unauthorized_resp())
    refresh_calls = []

    def refresh():
        refresh_calls.append(1)
        return "new-token"

    with pytest.raises(SkinError, match="HTTP 401"):
        skins.call_with_refresh(
            lambda token: skins.list_profile(token, session=s), TOKEN, refresh)
    assert refresh_calls == [1], "刷新只允许发生一次"
    assert len(s.calls) == 2, "重试只允许发生一次"


def test_ensure_fresh_token_skips_refresh_when_token_is_fresh():
    fresh = _jwt({"exp": 4102444800})  # 2100-01-01，远未过期
    refresh_calls = []

    def refresh():
        refresh_calls.append(1)
        return "new-token"

    assert skins.ensure_fresh_token(fresh, refresh) == fresh
    assert refresh_calls == []


def test_ensure_fresh_token_refreshes_expired_token():
    expired = _jwt({"exp": 1000})
    assert skins.ensure_fresh_token(expired, lambda: "new-token") == "new-token"
    assert skins.ensure_fresh_token(expired, lambda: None) == expired
    assert skins.ensure_fresh_token(expired, lambda: "") == expired


@pytest.mark.parametrize("token", ["", skins.OFFLINE_TOKEN])
def test_ensure_fresh_token_returns_offline_marker_untouched(token):
    def refresh():
        raise AssertionError("离线令牌不允许触发刷新")

    assert skins.ensure_fresh_token(token, refresh) == token

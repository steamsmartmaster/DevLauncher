import base64
import json

from launcher_core import tokens


def _seg(obj) -> str:
    raw = json.dumps(obj).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _jwt(payload) -> str:
    return "%s.%s.%s" % (_seg({"alg": "HS256"}), _seg(payload), "sig")


# ---------- jwt_expiry ----------

def test_jwt_expiry_reads_exp_from_payload():
    assert tokens.jwt_expiry(_jwt({"iat": 1789187869, "exp": 1789274269})) == 1789274269


def test_jwt_expiry_accepts_padded_and_unpadded_segments():
    raw = json.dumps({"exp": 100}).encode("utf-8")
    padded = base64.urlsafe_b64encode(raw).decode("ascii")  # 带 "=" 填充
    unpadded = padded.rstrip("=")
    assert tokens.jwt_expiry("h.%s.sig" % padded) == 100
    assert tokens.jwt_expiry("h.%s.sig" % unpadded) == 100


def test_jwt_expiry_rejects_wrong_segment_count():
    assert tokens.jwt_expiry("abc") is None
    assert tokens.jwt_expiry("a.b") is None
    assert tokens.jwt_expiry("a.b.c.d") is None


def test_jwt_expiry_rejects_bad_base64():
    assert tokens.jwt_expiry("a.%%%%.c") is None
    assert tokens.jwt_expiry("h.A.sig") is None  # 数据段长度 %4 == 1 非法
    garbage = base64.urlsafe_b64encode(b"\xff\xfe\x00not json").rstrip(b"=").decode("ascii")
    assert tokens.jwt_expiry("h.%s.sig" % garbage) is None


def test_jwt_expiry_returns_none_when_payload_lacks_exp():
    assert tokens.jwt_expiry(_jwt({"iat": 123})) is None


def test_jwt_expiry_returns_none_for_non_dict_payload():
    assert tokens.jwt_expiry("h.%s.sig" % _seg([1, 2, 3])) is None
    assert tokens.jwt_expiry("h.%s.sig" % _seg("just-a-string")) is None
    assert tokens.jwt_expiry("h.%s.sig" % _seg(42)) is None


def test_jwt_expiry_returns_none_for_non_numeric_exp():
    assert tokens.jwt_expiry(_jwt({"exp": "not-a-number"})) is None
    assert tokens.jwt_expiry(_jwt({"exp": None})) is None


# ---------- is_expired ----------

def test_is_expired_true_for_past_exp():
    assert tokens.is_expired(_jwt({"exp": 1000}), now=2000.0) is True
    assert tokens.is_expired(_jwt({"exp": 1000})) is True  # 默认 now=time.time()


def test_is_expired_true_inside_skew_window():
    # exp 还剩 30 秒，但已进入 60 秒 skew 窗口 → 提前判过期
    assert tokens.is_expired(_jwt({"exp": 1030}), now=1000.0, skew=60) is True
    assert tokens.is_expired(_jwt({"exp": 1060}), now=1000.0, skew=60) is True  # 边界


def test_is_expired_false_beyond_skew():
    assert tokens.is_expired(_jwt({"exp": 1061}), now=1000.0, skew=60) is False
    assert tokens.is_expired(_jwt({"exp": 4600}), now=1000.0) is False
    assert tokens.is_expired(_jwt({"exp": 4102444800})) is False  # 2100-01-01


def test_is_expired_false_for_offline_marker_and_non_jwt_strings():
    assert tokens.is_expired("offline_token") is False
    assert tokens.is_expired("") is False
    assert tokens.is_expired("abc") is False
    assert tokens.is_expired("a.b") is False
    assert tokens.is_expired("a.b.c.d") is False
    assert tokens.is_expired("eyJhbGciOiJSUzI1NiJ9.test") is False


def test_is_expired_false_for_malformed_jwt():
    assert tokens.is_expired("h.%%%%.sig") is False
    assert tokens.is_expired(_jwt({"iat": 123})) is False  # 缺 exp

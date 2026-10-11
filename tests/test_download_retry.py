"""下载断流重试 + Range 续传：OVH S3 预签名 24MB 实测下到 7.7MB 即整单失败"""
import pytest
import requests

from launcher_core import api_modrinth
from launcher_core.api_modrinth import ModrinthAPI


class _Resp:
    """假流式响应：在 break_at 字节处复现 requests 的 ChunkedEncodingError(IncompleteRead)"""

    def __init__(self, payload, status=200, headers=None, break_at=None):
        self._payload = payload
        self.status_code = status
        self.headers = dict(headers or {})
        self._break_at = break_at
        if "content-length" not in self.headers:
            self.headers["content-length"] = str(len(payload))

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("%d Error" % self.status_code)

    def iter_content(self, chunk_size=8192):
        limit = len(self._payload) if self._break_at is None else self._break_at
        pos = 0
        while pos < limit:
            nxt = min(pos + chunk_size, limit)
            yield self._payload[pos:nxt]
            pos = nxt
        if limit < len(self._payload):
            raise requests.exceptions.ChunkedEncodingError(
                "('Connection broken: IncompleteRead(%d bytes read, %d more expected)', "
                "IncompleteRead(%d, %d))"
                % (limit, len(self._payload) - limit, limit, len(self._payload) - limit))


class _Session:
    """按调用次序吐预置响应，并记录每次请求的 Range 头"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, stream=False, timeout=None, headers=None, **kw):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        if not self._responses:
            raise AssertionError("第 %d 次请求无预置响应" % len(self.calls))
        return self._responses.pop(0)


def _api_with(responses):
    api = ModrinthAPI()
    api.session = _Session(responses)
    return api, api.session


def test_retry_resumes_from_breakpoint(tmp_path):
    """断流后按 Range 续传，拼回完整文件且进度不回跳"""
    payload = bytes(range(256)) * 8  # 2048B
    dest = tmp_path / "liquidbounce.zip"
    api, sess = _api_with([
        _Resp(payload, break_at=700),
        _Resp(payload[700:], status=206),
    ])
    seen = []
    ok = api.download_file("http://x/a.zip", str(dest), callback=seen.append)

    assert ok is True, "断流后应重试成功"
    assert dest.read_bytes() == payload, "续传后文件应完整"
    assert len(sess.calls) == 2, "应恰好重试一次"
    assert sess.calls[0]["headers"].get("Range") is None, "首次不应带 Range"
    assert sess.calls[1]["headers"].get("Range") == "bytes=700-", \
        "重试应从断点续传, 实际 %r" % sess.calls[1]["headers"].get("Range")
    assert seen, "应有进度回调"
    assert seen == sorted(seen), "进度不得回跳: %r" % seen
    assert seen[-1] == pytest.approx(1.0), "结束时应到 100%, 实际 %r" % seen[-1]


def test_retry_when_server_ignores_range(tmp_path):
    """服务器不支持 Range（回 200 全量）时应从头重下而非拼接出坏文件"""
    payload = b"A" * 1200
    dest = tmp_path / "client.jar"
    api, sess = _api_with([
        _Resp(payload, break_at=500),
        _Resp(payload, status=200),
    ])
    ok = api.download_file("http://x/c.jar", str(dest))

    assert ok is True
    assert dest.read_bytes() == payload, "服务器忽略 Range 时必须重下全量"
    assert len(sess.calls) == 2


def test_all_attempts_fail_returns_false_and_cleans_partial(tmp_path):
    """三次全断：返回 False 且不得留下半截文件被当成品"""
    payload = b"B" * 3000
    dest = tmp_path / "bad.zip"
    api, _ = _api_with([
        _Resp(payload, break_at=900),
        _Resp(payload[900:], status=206, break_at=400),
        _Resp(payload[1300:], status=206, break_at=400),
    ])
    ok = api.download_file("http://x/bad.zip", str(dest))

    assert ok is False, "全失败应返回 False"
    assert not dest.exists(), "失败后不应残留半截文件"


def test_success_first_try_uses_single_request(tmp_path):
    """正常路径不引入额外请求"""
    payload = b"C" * 500
    dest = tmp_path / "ok.jar"
    api, sess = _api_with([_Resp(payload)])
    seen = []
    assert api.download_file("http://x/ok.jar", str(dest), callback=seen.append) is True
    assert len(sess.calls) == 1
    assert dest.read_bytes() == payload
    assert seen == [1.0]


def test_download_file_retries_constant_is_configurable():
    assert api_modrinth.DOWNLOAD_RETRIES >= 2, "重试次数应至少 2"


def test_client_dl_cb_emits_progress_update():
    """客户端 zip 下载必须补 progressUpdate，否则面板只走条纹、看不到百分比"""
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    m = re.search(r"def dl_cb\(p\):[\s\S]{0,400}", src)
    assert m, "downloadClientVersion 内应定义 dl_cb"
    body = m.group(0)
    assert "progressUpdate.emit" in body, \
        "dl_cb 应 emit progressUpdate（report 的 button_detail 不含 current/total，JS 只能走条纹分支）"
    assert "report(" in body, "dl_cb 仍应保留 report 推进 installing 文案"

# -*- coding: utf-8 -*-
"""共享下载层 launcher_core.net：续传、哈希校验、代理与重试策略。

这里盯住三件容易写错的事：
  1. 断流续传必须发 Range 且只在第二次及以后发，服务器回 200 时要整段重来，
     否则两段字节拼出的文件是坏的（OVH/S3 24MB 下到 7.7MB 就断是实测场景）；
  2. 哈希不符要连 .part 一起删，半截文件留着会被下次当成成品跳过下载；
  3. 重试只对 GET/HEAD 生效 —— POST（皮肤上传）重放可能造成重复写入。
"""
import os

import pytest
import requests

from launcher_core import net


class _Resp:
    """假流式响应：在 break_at 字节处复现 IncompleteRead"""

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

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size=8192):
        limit = len(self._payload) if self._break_at is None else self._break_at
        pos = 0
        while pos < limit:
            nxt = min(pos + chunk_size, limit)
            yield self._payload[pos:nxt]
            pos = nxt
        if limit < len(self._payload):
            raise requests.exceptions.ChunkedEncodingError("IncompleteRead")


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

    def close(self):
        pass


def _fractions(seen):
    return [round(d / t, 6) for d, t in seen if t]


# ---------- 续传 ----------

def test_resume_sends_range_only_on_retry(tmp_path):
    payload = bytes(range(256)) * 8
    dest = tmp_path / "a.zip"
    sess = _Session([_Resp(payload, break_at=700),
                     _Resp(payload[700:], status=206)])
    seen = []

    ok = net.download_file("http://x/a.zip", dest, session=sess,
                           callback=lambda d, t: seen.append((d, t)))

    assert ok is True
    assert dest.read_bytes() == payload, "续传后文件应完整"
    assert len(sess.calls) == 2
    assert sess.calls[0]["headers"].get("Range") is None, "首次不得带 Range"
    assert sess.calls[1]["headers"].get("Range") == "bytes=700-"


def test_resume_progress_is_monotonic_and_reaches_full(tmp_path):
    payload = bytes(range(256)) * 8
    dest = tmp_path / "a.zip"
    sess = _Session([_Resp(payload, break_at=700),
                     _Resp(payload[700:], status=206)])
    seen = []
    net.download_file("http://x/a.zip", dest, session=sess,
                      callback=lambda d, t: seen.append((d, t)))

    frac = _fractions(seen)
    assert frac == sorted(frac), "进度不得回跳: %r" % frac
    assert frac[-1] == pytest.approx(1.0)
    assert seen[-1][0] == seen[-1][1] == len(payload), "done/total 应为累计值"


def test_server_ignoring_range_restarts_whole_file(tmp_path):
    payload = b"A" * 1200
    dest = tmp_path / "c.jar"
    sess = _Session([_Resp(payload, break_at=500),
                     _Resp(payload, status=200)])

    assert net.download_file("http://x/c.jar", dest, session=sess) is True
    assert dest.read_bytes() == payload, "服务器忽略 Range 时必须整段重下"
    assert not (tmp_path / "c.jar.part").exists(), "重下后不应残留续传片段"


def test_status_416_restarts_without_range(tmp_path):
    payload = b"B" * 100
    dest = tmp_path / "d.bin"
    sess = _Session([_Resp(payload, break_at=50),
                     _Resp(b"", status=416),
                     _Resp(payload, status=200)])

    assert net.download_file("http://x/d.bin", dest, session=sess) is True
    assert dest.read_bytes() == payload
    assert len(sess.calls) == 3
    assert sess.calls[1]["headers"].get("Range") == "bytes=50-"
    assert sess.calls[2]["headers"].get("Range") is None, "416 重试不得再带 Range"


def test_all_attempts_fail_returns_false_and_cleans_partial(tmp_path):
    payload = b"C" * 3000
    dest = tmp_path / "bad.zip"
    sess = _Session([_Resp(payload, break_at=900),
                     _Resp(payload[900:], status=206, break_at=400),
                     _Resp(payload[1300:], status=206, break_at=400),
                     _Resp(payload[1700:], status=206, break_at=400)])

    assert net.download_file("http://x/bad.zip", dest, session=sess,
                             retries=4) is False
    assert not dest.exists(), "失败后不得留下成品"
    assert not (tmp_path / "bad.zip.part").exists(), "失败后不得残留 .part"


def test_success_first_try_single_request(tmp_path):
    payload = b"D" * 500
    dest = tmp_path / "ok.jar"
    sess = _Session([_Resp(payload)])
    seen = []

    assert net.download_file("http://x/ok.jar", dest, session=sess,
                             callback=lambda d, t: seen.append((d, t))) is True
    assert len(sess.calls) == 1, "正常路径不得引入额外请求"
    assert dest.read_bytes() == payload
    assert _fractions(seen) == [1.0]


def test_creates_missing_parent_dirs(tmp_path):
    dest = tmp_path / "nested" / "deep" / "f.txt"
    sess = _Session([_Resp(b"x")])
    assert net.download_file("http://x/f.txt", dest, session=sess) is True
    assert dest.read_bytes() == b"x"


# ---------- 哈希 ----------

def test_sha1_match_skips_network(tmp_path):
    dest = tmp_path / "v.jar"
    dest.write_bytes(b"hello")
    digest = net.sha1_of(dest)
    sess = _Session([])

    assert net.download_file("http://x/v.jar", dest, sha1=digest,
                             session=sess) is True
    assert sess.calls == [], "哈希相符不得再发请求"


def test_sha1_mismatch_removes_partial_and_returns_false(tmp_path):
    dest = tmp_path / "v.jar"
    sess = _Session([_Resp(b"actual-bytes")])

    assert net.download_file("http://x/v.jar", dest, sha1="0" * 40,
                             session=sess) is False
    assert not dest.exists(), "哈希不符不得写成品"
    assert not (tmp_path / "v.jar.part").exists(), "哈希不符必须清理 .part"


def test_sha1_match_reports_full_progress(tmp_path):
    dest = tmp_path / "v.jar"
    dest.write_bytes(b"hello")
    seen = []
    net.download_file("http://x/v.jar", dest, sha1=net.sha1_of(dest),
                      session=_Session([]),
                      callback=lambda d, t: seen.append((d, t)))
    assert seen == [(5, 5)]


def test_sha1_is_case_insensitive(tmp_path):
    dest = tmp_path / "v.jar"
    dest.write_bytes(b"hello")
    assert net.download_file("http://x/v.jar", dest,
                             sha1=net.sha1_of(dest).upper(),
                             session=_Session([])) is True


# ---------- 会话与代理 ----------

def test_build_session_sets_proxies_when_given():
    sess = net.build_session(proxy="http://127.0.0.1:10808")
    assert sess.proxies.get("http") == "http://127.0.0.1:10808"
    assert sess.proxies.get("https") == "http://127.0.0.1:10808"
    assert "DevLauncher" in sess.headers.get("User-Agent", "")
    sess.close()


def test_build_session_without_proxy_leaves_env_alone():
    sess = net.build_session()
    assert not sess.proxies, "未配置代理不得硬塞代理"
    sess.close()


def test_retry_policy_covers_get_but_not_post():
    sess = net.build_session()
    retry = sess.get_adapter("https://example.com").max_retries
    methods = getattr(retry, "allowed_methods", None) or retry.method_whitelist
    assert "GET" in methods and "HEAD" in methods
    assert "POST" not in methods, "POST 重放可能重复写入，不得自动重试"
    sess.close()


def test_retry_status_codes_include_server_errors():
    sess = net.build_session()
    retry = sess.get_adapter("https://example.com").max_retries
    assert retry.status_forcelist == (429, 500, 502, 503, 504)
    assert retry.total >= 2, "重试次数应至少 2"
    sess.close()


def test_apply_env_proxy_sets_and_clears(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    net.apply_env_proxy("http://127.0.0.1:10808")
    assert os.environ.get("HTTPS_PROXY") == "http://127.0.0.1:10808"
    assert os.environ.get("HTTP_PROXY") == "http://127.0.0.1:10808"
    net.apply_env_proxy("")
    assert "HTTPS_PROXY" not in os.environ, "清空代理必须移除环境变量"
    assert "HTTP_PROXY" not in os.environ

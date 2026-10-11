# -*- coding: utf-8 -*-
"""LiquidBounce 官方构建 API 封装 launcher_core/api_liquidbounce.py（纯函数单测）。

契约：api.liquidbounce.net/api/v1/version/builds/nextgen 返回按时间倒序的数组，
首条即最新；release_only=True 时取首条 release==true（正式版）。
"""
from launcher_core import api_liquidbounce as al

SAMPLE = [
    {"build_id": 18303, "release": False, "mc_version": "26.3",
     "url": "https://liquidbounce.net/download/queue/18303"},
    {"build_id": 18302, "release": False, "mc_version": "26.3",
     "url": "https://liquidbounce.net/download/queue/18302"},
    {"build_id": 18191, "release": True, "mc_version": "26.3",
     "url": "https://liquidbounce.net/download/queue/18191"},
    {"build_id": 16941, "release": True, "mc_version": "26.2",
     "url": "https://liquidbounce.net/download/queue/16941"},
]


def test_latest_url_release_only():
    assert al.latest_download_url(SAMPLE, release_only=True) == \
        "https://liquidbounce.net/download/queue/18191"


def test_latest_url_any_build():
    assert al.latest_download_url(SAMPLE, release_only=False) == \
        "https://liquidbounce.net/download/queue/18303"


def test_latest_url_missing_field_falls_back_to_build_id():
    builds = [{"build_id": 123, "release": True}]
    assert al.latest_download_url(builds, release_only=True) == \
        "https://liquidbounce.net/download/queue/123"


def test_latest_url_empty_or_garbage():
    assert al.latest_download_url([], release_only=True) == ""
    assert al.latest_download_url(None, release_only=True) == ""
    assert al.latest_download_url("x", release_only=True) == ""
    assert al.latest_download_url([{}, {"release": False}], release_only=True) == ""


def test_builds_url_is_official_api():
    assert al.BUILDS_URL == "https://api.liquidbounce.net/api/v1/version/builds/nextgen"


def test_fetch_latest_build_uses_session(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return SAMPLE

        def raise_for_status(self):
            pass

    class FakeSession:
        headers = {}

        def get(self, url, timeout=None):
            captured["url"] = url
            captured["timeout"] = timeout
            return FakeResp()

    monkeypatch.setattr(al.requests, "get", FakeSession().get)
    url = al.fetch_latest_build(release_only=True)
    assert url == "https://liquidbounce.net/download/queue/18191"
    assert captured["url"] == al.BUILDS_URL
    assert captured["timeout"]


def test_fetch_latest_build_network_error_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(al.requests, "get", boom)
    assert al.fetch_latest_build(release_only=True) == ""

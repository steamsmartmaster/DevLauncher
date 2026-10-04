"""Meteor Client 下载 API 封装 launcher_core/api_meteor.py（纯函数单测；网络部分走冒烟）"""
from launcher_core import api_meteor as am

BASE = "https://meteorclient.com/api/download"


def test_meteor_download_url():
    assert am.meteor_download_url() == BASE
    assert am.meteor_download_url("") == BASE
    assert am.meteor_download_url("1.21.11") == BASE + "?version=1.21.11"
    assert am.meteor_download_url("26.1.2") == BASE + "?version=26.1.2"


def test_filename_from_content_disposition():
    assert am.filename_from_content_disposition(
        "attachment; filename=meteor-client-26.2-32.jar") == "meteor-client-26.2-32.jar"
    assert am.filename_from_content_disposition(
        'attachment; filename="meteor client.jar"') == "meteor client.jar"
    assert am.filename_from_content_disposition("") == ""
    assert am.filename_from_content_disposition("inline") == ""
    assert am.filename_from_content_disposition('attachment; filename*=UTF-8\'\'a.jar') == ""


def test_parse_archive_versions():
    html = """
    <a href="https://meteorclient.com/api/download?version=26.1.2">26.1.2 - 42</a>
    <a href="/api/download?version=1.21.11">1.21.11 - 86</a>
    <a href="/api/download?version=1.21.10">1.21.10 - 57</a>
    <a href="/api/downloadBaritone">Baritone</a>
    <a href="/archive">archive</a>
    """
    vs = am.parse_archive_versions(html)
    assert [v["version"] for v in vs] == ["26.1.2", "1.21.11", "1.21.10"]
    assert vs[0]["label"] == "26.1.2 - 42"
    assert vs[1]["label"] == "1.21.11 - 86"


def test_parse_archive_versions_empty():
    assert am.parse_archive_versions("") == []
    assert am.parse_archive_versions("<html>no links</html>") == []


def test_meteor_api_singleton():
    assert am.meteor_api is not None
    assert hasattr(am.meteor_api, "get_jar")
    assert hasattr(am.meteor_api, "get_archive_versions")

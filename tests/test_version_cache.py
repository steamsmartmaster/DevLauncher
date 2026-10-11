"""版本清单磁盘缓存 + 带 timeout 的网络获取：启动提速（stale-while-revalidate）"""
import inspect
import re
from pathlib import Path

from launcher_core import versions as ver

ROOT = Path(__file__).resolve().parents[1]
RAW = [{"id": "1.21.4", "type": "release",
        "releaseTime": "2024-12-03T12:00:00+00:00", "complianceLevel": 0}]


def test_cache_roundtrip(tmp_path):
    p = tmp_path / "manifest.json"
    ver.save_version_cache(RAW, p)
    assert ver.load_version_cache(p) == RAW


def test_cache_missing_or_corrupt_returns_none(tmp_path):
    assert ver.load_version_cache(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert ver.load_version_cache(bad) is None
    not_list = tmp_path / "notlist.json"
    not_list.write_text('{"a": 1}', encoding="utf-8")
    assert ver.load_version_cache(not_list) is None


def test_fetch_version_list_has_timeout():
    assert ver.VERSION_MANIFEST_URL.endswith("version_manifest_v2.json")
    src = inspect.getsource(ver.VersionManager.fetch_version_list)
    assert "timeout" in src, "网络获取必须带 timeout（禁无超时直连）"
    assert "raise_for_status" in src, "非 200 应显式失败"
    assert "requests.get" in src


def test_getversions_uses_cache_then_fetch():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    m = re.search(r"def getVersions\(self\):([\s\S]*?)\n    @pyqtSlot", src)
    assert m, "getVersions 应存在且后随下一槽位"
    body = m.group(1)
    assert "load_version_cache" in body, "应先读磁盘缓存立即回给 UI"
    assert "fetch_version_list" in body, "后台/其后应走带 timeout 的获取"
    assert "save_version_cache" in body, "取到新清单应落盘"
    assert "get_version_list()" not in body, "不再直连 mll 无超时 get_version_list"

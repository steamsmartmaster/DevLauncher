# -*- coding: utf-8 -*-
"""Modrinth 版本依赖解析（launcher_core.api_modrinth.parse_dependencies）。

实测样本（2026-10-13 api.modrinth.com/v2，非编造）：
  indium nQHYSjxO:
      [{"project_id":"AANobbMI","version_id":"ygf8cVZg",
        "file_name":null,"dependency_type":"required"}]
  simple-voice-chat b8AUcKCx:
      7 条 dependency_type=optional，version_id 全为 null
  modmenu 78N35pJi: 2 条 required，version_id 全为 null

关键语义：version_id 为 null 表示"未指定版本"，必须回退到 project_id 再挑版本，
绝不能当成"依赖已解析"。所以归一化后 version_id 保持 None 而不是空串。
"""
import json

from launcher_core.api_modrinth import (
    ModrinthAPI,
    attach_project_info,
    build_download_plan,
    parse_chosen_ids,
    parse_dependencies,
    pick_dependency_version,
)


INDIUM_VERSION = {
    "id": "nQHYSjxO",
    "project_id": "ZzsO8wVq",
    "version_type": "release",
    "dependencies": [
        {
            "version_id": "ygf8cVZg",
            "project_id": "AANobbMI",
            "file_name": None,
            "dependency_type": "required",
        }
    ],
}

VOICECHAT_VERSION = {
    "id": "b8AUcKCx",
    "dependencies": [
        {"version_id": None, "project_id": pid, "file_name": None,
         "dependency_type": "optional"}
        for pid in ("YlKdE5VK", "qyVF9oeo", "mOgUt4GM", "SRlzjEBS",
                    "UL4bJFDY", "9s6osm5g", "Vebnzrzj")
    ],
}


def test_none_and_empty_payload():
    assert parse_dependencies(None) == []
    assert parse_dependencies({}) == []
    assert parse_dependencies({"id": "x"}) == []


def test_required_dep_with_explicit_version():
    deps = parse_dependencies(INDIUM_VERSION)
    assert deps == [{
        "project_id": "AANobbMI",
        "version_id": "ygf8cVZg",
        "dependency_type": "required",
        "file_name": None,
    }]


def test_null_version_id_stays_none_not_empty_string():
    deps = parse_dependencies(VOICECHAT_VERSION)
    assert len(deps) == 7
    assert all(d["dependency_type"] == "optional" for d in deps)
    # None 与 "" 语义不同：前者要回退挑版本，后者是脏数据
    assert all(d["version_id"] is None for d in deps)
    assert all(d["project_id"] for d in deps)


def test_missing_dependency_type_defaults_to_required():
    deps = parse_dependencies({"dependencies": [
        {"project_id": "P7dR8mSH", "version_id": None},
    ]})
    assert deps[0]["dependency_type"] == "required"


def test_missing_project_id_is_dropped():
    # 没有 project_id 就无法下载，留着只会让 UI 渲染出空行
    deps = parse_dependencies({"dependencies": [
        {"version_id": "abc", "dependency_type": "required"},
        {"project_id": "ok", "dependency_type": "required"},
    ]})
    assert [d["project_id"] for d in deps] == ["ok"]


def test_non_dict_entries_are_skipped():
    deps = parse_dependencies({"dependencies": [
        None, "P7dR8mSH", 42, {"project_id": "keep", "dependency_type": "required"},
    ]})
    assert [d["project_id"] for d in deps] == ["keep"]


def test_dependencies_not_a_list_is_ignored():
    assert parse_dependencies({"dependencies": "P7dR8mSH"}) == []
    assert parse_dependencies({"dependencies": {"project_id": "x"}}) == []


def test_incompatible_and_embedded_preserved():
    deps = parse_dependencies({"dependencies": [
        {"project_id": "bad", "dependency_type": "incompatible"},
        {"project_id": "emb", "dependency_type": "embedded"},
        {"project_id": "opt", "dependency_type": "optional"},
        {"project_id": "req", "dependency_type": "required"},
    ]})
    assert [d["dependency_type"] for d in deps] == [
        "incompatible", "embedded", "optional", "required"]


def test_result_is_json_serializable():
    # 结果要经 pyqtSignal 发给 QWebEngine 的 JS，不可序列化会静默丢消息
    for payload in (INDIUM_VERSION, VOICECHAT_VERSION):
        json.dumps(parse_dependencies(payload))


def test_input_payload_is_not_mutated():
    snapshot = json.loads(json.dumps(INDIUM_VERSION))
    parse_dependencies(INDIUM_VERSION)
    assert INDIUM_VERSION == snapshot


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload=()):
        self.payload = list(payload)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return _FakeResp(self.payload)


def test_get_projects_dedupes_and_json_encodes_ids():
    api = ModrinthAPI()
    api.session = _FakeSession([{
        "id": "P7dR8mSH", "title": "Fabric API", "slug": "fabric-api",
        "icon_url": "icon.png", "project_type": "mod",
    }])
    out = api.get_projects(["P7dR8mSH", "P7dR8mSH", "", None, "P7dR8mSH"])
    assert list(out) == ["P7dR8mSH"]
    assert out["P7dR8mSH"]["title"] == "Fabric API"
    # ids 必须是 URL 里的 JSON 数组串，裸逗号拼接会被 API 当成单个 id
    assert json.loads(api.session.calls[0]["params"]["ids"]) == ["P7dR8mSH"]


def test_get_projects_empty_ids_makes_no_request():
    api = ModrinthAPI()
    api.session = _FakeSession()
    assert api.get_projects([]) == {}
    assert api.session.calls == []


def test_get_projects_failure_returns_empty_dict():
    class _BoomSession:
        def get(self, url, params=None, timeout=None):
            raise RuntimeError("network down")

    api = ModrinthAPI()
    api.session = _BoomSession()
    assert api.get_projects(["P7dR8mSH"]) == {}


def test_get_projects_chunks_large_id_lists():
    api = ModrinthAPI()
    api.session = _FakeSession()
    api.get_projects(["id%04d" % i for i in range(250)])
    sizes = [len(json.loads(c["params"]["ids"])) for c in api.session.calls]
    assert sizes == [100, 100, 50]


def test_get_projects_keeps_going_after_one_chunk_fails():
    class _FlakySession:
        def __init__(self):
            self.calls = 0

        def get(self, url, params=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("chunk 1 down")
            return _FakeResp([{"id": "ok2", "title": "Second"}])

    api = ModrinthAPI()
    api.session = _FlakySession()
    out = api.get_projects(["id%04d" % i for i in range(150)])
    assert api.session.calls == 2
    assert list(out) == ["ok2"]


def test_attach_project_info_falls_back_to_project_id():
    deps = parse_dependencies(INDIUM_VERSION)
    attach_project_info(deps, {})
    assert deps[0]["title"] == "AANobbMI"
    assert deps[0]["icon_url"] == ""


def test_attach_project_info_uses_batched_lookup():
    deps = parse_dependencies(VOICECHAT_VERSION)
    attach_project_info(deps, {
        "YlKdE5VK": {"title": "ViaFabric", "slug": "viafabric", "icon_url": "v.png"},
        "qyVF9oeo": {"title": "Sound Physics Remastered", "slug": "spr", "icon_url": ""},
    })
    by_id = {d["project_id"]: d for d in deps}
    assert by_id["YlKdE5VK"]["title"] == "ViaFabric"
    assert by_id["YlKdE5VK"]["slug"] == "viafabric"
    assert by_id["YlKdE5VK"]["icon_url"] == "v.png"
    # 查不到的不能留空标题——空串会让 UI 渲染出一行空白
    assert by_id["mOgUt4GM"]["title"] == "mOgUt4GM"
    json.dumps(deps)


INDIUM_VERSIONS = [
    {"id": "v1036", "version_type": "release", "version_number": "1.0.36+mc1.20.1",
     "game_versions": ["1.20.1", "1.20.5"], "loaders": ["fabric", "quilt"]},
    {"id": "v1035", "version_type": "release", "version_number": "1.0.35+mc1.21",
     "game_versions": ["1.21"], "loaders": ["fabric", "quilt"]},
    {"id": "vApha", "version_type": "alpha", "version_number": "2.0.0-alpha",
     "game_versions": ["1.20.1"], "loaders": ["fabric"]},
    {"id": "vForge", "version_type": "release", "version_number": "1.0.30",
     "game_versions": ["1.20.1"], "loaders": ["forge"]},
]


def test_pick_dependency_version_matches_game_version_and_loader():
    picked = pick_dependency_version(
        INDIUM_VERSIONS, game_versions=["1.20.1"], loaders=["fabric"])
    assert picked["id"] == "v1036"


def test_pick_dependency_version_prefers_release_over_alpha():
    # alpha 同样匹配 1.20.1+fabric，但 release 必须优先
    picked = pick_dependency_version(
        INDIUM_VERSIONS, game_versions=["1.20.1"], loaders=["fabric"])
    assert picked["version_type"] == "release"


def test_pick_dependency_version_falls_back_to_alpha():
    picked = pick_dependency_version(
        [{"id": "only-alpha", "version_type": "alpha",
          "game_versions": ["1.20.1"], "loaders": ["fabric"]}],
        game_versions=["1.20.1"], loaders=["fabric"])
    assert picked["id"] == "only-alpha"


def test_pick_dependency_version_respects_loader():
    picked = pick_dependency_version(
        INDIUM_VERSIONS, game_versions=["1.20.1"], loaders=["forge"])
    assert picked["id"] == "vForge"


def test_pick_dependency_version_no_match_is_none():
    assert pick_dependency_version(
        INDIUM_VERSIONS, game_versions=["1.99"], loaders=["fabric"]) is None


def test_pick_dependency_version_empty_inputs():
    assert pick_dependency_version(None, game_versions=["1.20.1"]) is None
    assert pick_dependency_version([], game_versions=["1.20.1"]) is None
    assert pick_dependency_version(["junk"], game_versions=["1.20.1"]) is None


def test_pick_dependency_version_without_filters_takes_first_release():
    picked = pick_dependency_version(INDIUM_VERSIONS)
    assert picked["id"] == "v1036"


def test_pick_dependency_version_coerces_scalar_filters():
    picked = pick_dependency_version(INDIUM_VERSIONS, game_versions="1.21", loaders="quilt")
    assert picked["id"] == "v1035"


def test_parse_chosen_ids_rejects_garbage():
    assert parse_chosen_ids(None) == []
    assert parse_chosen_ids("") == []
    assert parse_chosen_ids("not json {") == []
    assert parse_chosen_ids('{"a": 1}') == []
    assert parse_chosen_ids('"P7dR8mSH"') == []


def test_parse_chosen_ids_keeps_only_non_empty_strings():
    assert parse_chosen_ids('[1, "P7dR8mSH", "", null, "AANobbMI"]') == [
        "P7dR8mSH", "AANobbMI"]


def test_build_download_plan_main_file_only():
    version = {"files": [{"url": "http://x/a.jar", "filename": "a.jar"}]}
    assert build_download_plan(version, []) == [("http://x/a.jar", "a.jar")]


def test_build_download_plan_no_files_is_empty():
    assert build_download_plan({"files": []}, ["P7dR8mSH"]) == []
    assert build_download_plan({}, ["P7dR8mSH"]) == []


def test_build_download_plan_includes_checked_optional_dep():
    version = {
        "files": [{"url": "http://x/main.jar", "filename": "main.jar"}],
        "dependencies": [
            {"project_id": "AANobbMI", "version_id": "v1", "dependency_type": "optional"},
        ],
    }
    resolved = {"files": [{"url": "http://x/dep.jar", "filename": "dep.jar"}]}
    seen = []

    def resolve(dep, parent):
        seen.append((dep["project_id"], parent.get("files")[0]["filename"]))
        return resolved

    plan = build_download_plan(version, ["AANobbMI"], resolve)
    assert plan == [("http://x/main.jar", "main.jar"), ("http://x/dep.jar", "dep.jar")]
    assert seen == [("AANobbMI", "main.jar")]


def test_build_download_plan_skips_unchosen_optional():
    version = {
        "files": [{"url": "http://x/main.jar", "filename": "main.jar"}],
        "dependencies": [
            {"project_id": "AANobbMI", "version_id": "v1", "dependency_type": "optional"},
        ],
    }
    def resolve(dep, parent):
        raise AssertionError("未勾选的依赖不该触发解析")
    assert build_download_plan(version, [], resolve) == [("http://x/main.jar", "main.jar")]


def test_build_download_plan_never_installs_required_or_incompatible():
    version = {
        "files": [{"url": "http://x/main.jar", "filename": "main.jar"}],
        "dependencies": [
            {"project_id": "P7dR8mSH", "version_id": "v1", "dependency_type": "required"},
            {"project_id": "bad00001", "version_id": "v1", "dependency_type": "incompatible"},
            {"project_id": "emb00001", "version_id": "v1", "dependency_type": "embedded"},
        ],
    }
    def resolve(dep, parent):
        raise AssertionError("非 optional 依赖不该被下载")
    assert build_download_plan(version, ["P7dR8mSH", "bad00001", "emb00001"], resolve) == [
        ("http://x/main.jar", "main.jar")]


def test_build_download_plan_skips_unresolvable_dep():
    version = {
        "files": [{"url": "http://x/main.jar", "filename": "main.jar"}],
        "dependencies": [
            {"project_id": "AANobbMI", "version_id": "v1", "dependency_type": "optional"},
        ],
    }
    plan = build_download_plan(version, ["AANobbMI"], lambda dep, parent: None)
    assert plan == [("http://x/main.jar", "main.jar")]


def test_build_download_plan_falls_back_to_project_id_filename():
    version = {
        "files": [{"url": "http://x/main.jar", "filename": "main.jar"}],
        "dependencies": [
            {"project_id": "AANobbMI", "version_id": "v1", "dependency_type": "optional"},
        ],
    }
    resolved = {"files": [{"url": "http://x/dep.jar"}]}
    plan = build_download_plan(version, ["AANobbMI"], lambda dep, parent: resolved)
    assert plan[1] == ("http://x/dep.jar", "AANobbMI.jar")


def test_build_download_plan_ignores_file_without_url():
    version = {"files": [{"filename": "broken.jar"}, {"url": "http://x/b.jar", "filename": "b.jar"}]}
    assert build_download_plan(version, []) == [("http://x/b.jar", "b.jar")]


# -*- coding: utf-8 -*-
"""图形化游戏设置：launcher_core.game_options 对 options.txt 的读写与字段目录。

options.txt 是 `key:value` 的纯文本行文件，游戏每次启动/退出都会整个重写它。
所以这里必须保持两个性质：
  1. 未知键原样保留 —— 启动器不认识 keybinds / resourcePacks 之类的大杂烩，
     但改一个渲染距离就把它们冲掉是不可接受的；
  2. 值先按字符串存 —— MC 的 bool 写作 true/false、float 带小数点，
     提前按类型解析会在回写时改变格式，触发游戏重置。
"""
from pathlib import Path

from launcher_core.game_options import (
    build_updates,
    coerce_value,
    format_options,
    list_option_specs,
    options_path,
    parse_options,
    read_options,
    write_options,
)

SAMPLE = (
    "renderDistance:8\n"
    "maxFps:120\n"
    "gamma:0.5\n"
    "fullscreen:false\n"
    "particles:all\n"
    "resourcePacks:[\"vanilla\",\"file/faithful.zip\"]\n"
    "lang:zh_cn\n"
    "\n"
    "this line has no colon\n"
    "\n"
)


def specs_by_key():
    return {s["key"]: s for s in list_option_specs()}


# ---------- parse ----------

def test_parse_reads_key_value_pairs():
    data = parse_options(SAMPLE)
    assert data["renderDistance"] == "8"
    assert data["gamma"] == "0.5"
    assert data["fullscreen"] == "false"


def test_parse_splits_on_first_colon_only():
    data = parse_options(SAMPLE)
    assert data["resourcePacks"] == '["vanilla","file/faithful.zip"]'


def test_parse_ignores_blank_and_colonless_lines():
    data = parse_options(SAMPLE)
    assert len(data) == 7


def test_parse_empty_text():
    assert parse_options("") == {}
    assert parse_options("\n\n") == {}


# ---------- format ----------

def test_format_round_trips():
    text = format_options(parse_options(SAMPLE))
    assert parse_options(text) == parse_options(SAMPLE)


def test_format_terminates_with_newline():
    assert format_options({"a": "1"}).endswith("\n")


# ---------- specs ----------

def test_specs_have_unique_keys():
    keys = [s["key"] for s in list_option_specs()]
    assert len(keys) == len(set(keys))


def test_specs_have_ui_metadata():
    for s in list_option_specs():
        assert s["label"].strip(), s["key"]
        assert s["group"].strip(), s["key"]
        assert s["type"] in ("bool", "int", "float", "choice", "string"), s["key"]
        assert "default" in s, s["key"]


def test_choice_specs_list_choices_others_do_not():
    for s in list_option_specs():
        if s["type"] == "choice":
            assert s["choices"], s["key"]
            assert s["default"] in s["choices"], s["key"]
        else:
            assert not s.get("choices"), s["key"]


def test_bounded_specs_declare_min_max():
    for s in list_option_specs():
        if s["type"] in ("int", "float"):
            assert s["minimum"] is not None, s["key"]
            assert s["maximum"] is not None, s["key"]
            assert s["minimum"] < s["maximum"], s["key"]


def test_covers_the_settings_players_actually_change():
    keys = set(specs_by_key())
    for k in ("renderDistance", "maxFps", "gamma", "fov", "guiScale",
              "fullscreen", "enableVsync", "musicVolume", "soundVolume",
              "mouseSensitivity", "autoJump", "mainHand", "language"):
        assert k in keys, k


# ---------- coerce ----------

def test_coerce_bool():
    s = specs_by_key()["fullscreen"]
    assert coerce_value("true", s) is True
    assert coerce_value("false", s) is False


def test_coerce_bool_invalid_falls_back_to_default():
    s = specs_by_key()["fullscreen"]
    assert coerce_value("banana", s) is s["default"]


def test_coerce_int_clamps_low():
    s = specs_by_key()["renderDistance"]
    assert coerce_value("1", s) == s["minimum"]


def test_coerce_int_clamps_high():
    s = specs_by_key()["renderDistance"]
    assert coerce_value("999", s) == s["maximum"]


def test_coerce_int_in_range():
    s = specs_by_key()["renderDistance"]
    assert coerce_value("16", s) == 16


def test_coerce_float():
    s = specs_by_key()["gamma"]
    assert coerce_value("0.25", s) == 0.25


def test_coerce_float_clamps():
    s = specs_by_key()["gamma"]
    assert coerce_value("9.0", s) == s["maximum"]


def test_coerce_choice():
    s = specs_by_key()["particles"]
    assert coerce_value("minimal", s) == "minimal"


def test_coerce_choice_invalid_falls_back_to_default():
    s = specs_by_key()["particles"]
    assert coerce_value("ultra", s) == s["default"]


# ---------- read / write ----------

def test_read_missing_file_returns_empty(tmp_path):
    assert read_options(tmp_path / "nope.txt") == {}


def test_write_creates_file(tmp_path):
    path = tmp_path / "options.txt"
    write_options(path, {"renderDistance": "16"})
    assert path.read_text(encoding="utf-8") == "renderDistance:16\n"


def test_write_preserves_unknown_keys(tmp_path):
    path = tmp_path / "options.txt"
    path.write_text(SAMPLE, encoding="utf-8")
    parsed = read_options(path)
    write_options(path, build_updates(parsed, {"renderDistance": 32}))
    after = read_options(path)
    assert after["renderDistance"] == "32"
    assert after["resourcePacks"] == '["vanilla","file/faithful.zip"]'


def test_write_backs_up_previous_file(tmp_path):
    path = tmp_path / "options.txt"
    path.write_text("renderDistance:8\n", encoding="utf-8")
    write_options(path, {"renderDistance": "16"})
    assert (tmp_path / "options.txt.bak").read_text(encoding="utf-8") == "renderDistance:8\n"


def test_build_updates_stringifies_typed_values(tmp_path):
    parsed = {"renderDistance": "8", "gamma": "0.0"}
    out = build_updates(parsed, {"renderDistance": 32, "fullscreen": False})
    assert out["renderDistance"] == "32"
    assert out["fullscreen"] == "false"
    assert out["gamma"] == "0.0"


# ---------- path resolution ----------

def test_options_path_global(tmp_path):
    from launcher_core.versions import VersionManager
    mc = Path(tmp_path) / ".minecraft"
    vm = VersionManager(str(mc))
    assert options_path(vm, "1.20.1") == mc / "options.txt"


def test_options_path_isolated(tmp_path):
    from launcher_core.versions import VersionManager
    mc = Path(tmp_path) / ".minecraft"
    vm = VersionManager(str(mc))
    name = "MyPack"
    (mc / "versions" / name).mkdir(parents=True)
    assert vm.enable_version_isolation(name) is True
    assert options_path(vm, name) == mc / "versions" / name / "options.txt"

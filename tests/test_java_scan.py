# -*- coding: utf-8 -*-
"""P0-1 Java 扫描：java_scan 纯函数 + main/game/settings 接线静态断言。"""
import os
import re
from pathlib import Path

from launcher_core import java_scan as js

ROOT = Path(__file__).resolve().parents[1]


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def _pathlist(items):
    return os.pathsep.join(items)


def test_parse_java_version_formats():
    assert js.parse_java_version('java version "1.8.0_392"') == (8, "1.8.0_392")
    assert js.parse_java_version('openjdk version "17.0.9" 2023-10-17') == (17, "17.0.9")
    assert js.parse_java_version('openjdk version "21.0.1" 2023-10-17') == (21, "21.0.1")
    assert js.parse_java_version('java version "1.8.0"') == (8, "1.8.0")
    assert js.parse_java_version("garbage") is None
    assert js.parse_java_version("") is None


def test_scan_candidates_paths():
    env = {
        "JAVA_HOME": r"C:\jdk-17",
        "PATH": _pathlist([r"C:\Users\me\AppData\Local\Microsoft\WindowsApps"]),
        "ProgramFiles": r"C:\Program Files",
        "ProgramFiles(x86)": r"C:\Program Files (x86)",
        "LOCALAPPDATA": r"C:\Users\me\AppData\Local",
    }
    cand = js.scan_candidates(env, minecraft_dir=r"D:\mc")
    direct = {_norm(p) for p in cand["direct"]}
    assert _norm(r"C:\jdk-17\bin") in direct
    assert _norm(r"C:\Users\me\AppData\Local\Microsoft\WindowsApps") in direct
    walk = {_norm(d): dep for d, dep in cand["walk"]}
    assert _norm(r"C:\Program Files\Java") in walk
    assert _norm(r"C:\Program Files (x86)\Eclipse Adoptium") in walk
    assert _norm(r"D:\mc\runtime") in walk
    assert walk[_norm(r"D:\mc\runtime")] >= 6
    assert walk[_norm(r"C:\Program Files\Java")] >= 4


def test_find_java_exes_direct_and_walk():
    JAVA_A = r"D:\mc\runtime\java-runtime-ga\windows-x64\java-runtime\java\bin\javaw.exe"
    EXISTING = {
        _norm(r"C:\path1\java.exe"),
        _norm(r"C:\PF\Java\jdk-17\bin\java.exe"),
        _norm(JAVA_A),
    }
    TREE = {
        _norm(r"C:\PF\Java"): ["jdk-17", "old"],
        _norm(r"C:\PF\Java\jdk-17"): ["bin", "lib"],
        _norm(r"D:\mc\runtime"): ["java-runtime-ga"],
        _norm(r"D:\mc\runtime\java-runtime-ga"): ["windows-x64"],
        _norm(r"D:\mc\runtime\java-runtime-ga\windows-x64"): ["java-runtime"],
        _norm(r"D:\mc\runtime\java-runtime-ga\windows-x64\java-runtime"): ["java"],
        _norm(r"D:\mc\runtime\java-runtime-ga\windows-x64\java-runtime\java"): ["bin"],
    }

    def exists(p):
        return _norm(p) in EXISTING

    def scandir(d):
        if _norm(d) in TREE:
            return TREE[_norm(d)]
        raise FileNotFoundError(d)

    found = {_norm(p) for p in js.find_java_exes(
        [r"C:\path1"], [(r"C:\PF\Java", 4), (r"D:\mc\runtime", 6)],
        exists=exists, scandir=scandir)}
    assert _norm(r"C:\path1\java.exe") in found
    assert _norm(r"C:\PF\Java\jdk-17\bin\java.exe") in found
    assert _norm(JAVA_A) in found


def test_scan_javas_dedupe_sort_detect():
    EXISTING = {_norm(r"C:\a\java.exe"), _norm(r"C:\A\java.exe"),
                _norm(r"C:\b\java.exe")}

    def exists(p):
        return _norm(p) in EXISTING

    def runner(path):
        if "\\a\\" in path.lower():
            return 'openjdk version "21.0.1"'
        return 'java version "1.8.0_392"'

    out = js.scan_javas([r"C:\a", r"C:\A", r"C:\b"], [], exists=exists,
                        scandir=lambda d: [], runner=runner)
    assert len(out) == 2, out
    assert out[0]["major"] == 21 and out[1]["major"] == 8
    assert out[0]["path"].lower().endswith("java.exe")


def test_required_java_major_table():
    assert js.required_java_major("1.16.5") == 8
    assert js.required_java_major("1.17.1") == 16
    assert js.required_java_major("1.19.4") == 17
    assert js.required_java_major("1.20.4") == 17
    assert js.required_java_major("1.20.5") == 21
    assert js.required_java_major("1.21.11") == 21
    assert js.required_java_major("25w14a") == 21
    assert js.required_java_major("") == 21


def test_recommend_java():
    javas = [
        {"path": r"C:\j8", "major": 8, "version": "1.8.0"},
        {"path": r"C:\j17", "major": 17, "version": "17.0.9"},
        {"path": r"C:\j21", "major": 21, "version": "21.0.1"},
    ]
    # 满足要求的最低版本（最贴近需求，避免高版本 Java 破坏旧 MC 兼容性）
    assert js.recommend_java(javas, "1.19.4")["major"] == 17
    assert js.recommend_java(javas, "1.21.1")["major"] == 21
    assert js.recommend_java([javas[0]], "1.21.1") is None
    assert js.recommend_java(javas, "")["major"] == 21


def test_main_py_wiring_static():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert re.search(r"javasScanned\s*=\s*pyqtSignal\(str\)", src), "应有 javasScanned 信号"
    assert re.search(r"@pyqtSlot\(\)\s+def scanJavas\(self\)", src), "应有 scanJavas 槽"
    assert re.search(r"@pyqtSlot\(str\)\s+def hideJava\(self, path: str\)", src), "应有 hideJava 槽"
    assert "javasScanned.connect(self._on_javas_scanned)" in src, "MainWindow 应接信号"
    assert "onJavasScanned(" in src, "应经 runJavaScript 推送 onJavasScanned"
    assert "java_hidden" in src, "扫描过滤应读 java_hidden"
    m = re.search(r"def launchGame\(self[\s\S]{0,1400}", src)
    assert m and "java_executable=" in m.group(0), "launchGame 应透传 java_executable"


def test_game_launch_java_effective_static():
    src = (ROOT / "launcher_core" / "game.py").read_text(encoding="utf-8")
    assert re.search(r"def launch\([\s\S]{0,400}?java_executable", src), \
        "launch 应有 java_executable 参数"
    m = re.search(r"get_minecraft_command\([\s\S]{0,500}", src)
    assert m and "command[0]" in m.group(0), "命令生成后应替换 command[0]"


def test_settings_java_hidden_default():
    from launcher_core.settings import Settings
    assert "java_hidden" in Settings.DEFAULT_SETTINGS
    assert Settings.DEFAULT_SETTINGS["java_hidden"] == []

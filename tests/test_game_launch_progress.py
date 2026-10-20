import json
import os
import pathlib
import zipfile

import launcher_core.game as game_mod
from launcher_core.game import GameLauncher

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FakeProcess:
    def __init__(self, pid=4242):
        self.pid = pid
        self.returncode = None

    def poll(self):
        return self.returncode


def make_version(root, version_id="1.20.1", inherits=None, with_jar=True):
    vdir = root / "versions" / version_id
    vdir.mkdir(parents=True)
    data = {"id": version_id, "libraries": []}
    if inherits:
        data["inheritsFrom"] = inherits
    (vdir / (version_id + ".json")).write_text(json.dumps(data), encoding="utf-8")
    if with_jar:
        (vdir / (version_id + ".jar")).write_bytes(b"jar")
    return vdir


def fake_java(tmp_path):
    java = tmp_path / "jdk" / "bin" / "javaw.exe"
    java.parent.mkdir(parents=True)
    java.write_bytes(b"")
    return str(java)


def patch_launch(monkeypatch, root, java):
    monkeypatch.setattr(game_mod.minecraft_launcher_lib.utils, "get_installed_versions",
                        lambda d: [{"id": "1.20.1"}])
    monkeypatch.setattr(game_mod.minecraft_launcher_lib.utils, "get_java_executable",
                        lambda: java)
    monkeypatch.setattr(game_mod.minecraft_launcher_lib.command, "get_minecraft_command",
                        lambda vid, mdir, options: [
                            "javaw.exe", "-cp", "libs.jar",
                            "--gameDir", str(mdir),
                            "--username", options["username"],
                        ])
    proc = FakeProcess()
    monkeypatch.setattr(game_mod.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(GameLauncher, "_tail_game_log", lambda self, *a, **k: None)
    return proc


def test_launch_reports_stages_in_order(tmp_path, monkeypatch):
    make_version(tmp_path)
    java = fake_java(tmp_path)
    patch_launch(monkeypatch, tmp_path, java)
    events = []
    launcher = GameLauncher(str(tmp_path))

    ok, msg = launcher.launch(
        "1.20.1", "Steve", "uuid", "token",
        min_memory=1024, max_memory=4096,
        on_progress=lambda step, text: events.append((step, text)),
    )

    assert ok is True
    assert msg == "游戏已启动"
    assert [step for step, _ in events] == [
        "check_version", "version_ok",
        "check_java", "java_ok",
        "check_files", "files_ok",
        "gamedir",
        "build_command", "command_ok",
        "natives", "natives_ok",
        "spawn", "spawned", "waiting",
    ]
    spawned = dict(events)["spawned"]
    assert "4242" in spawned
    command_ok = dict(events)["command_ok"]
    assert "内存 1024-4096 MB" in command_ok
    assert "javaw.exe" in command_ok
    assert (tmp_path / "logs" / "game.log").exists()


def test_launch_without_callback_still_works(tmp_path, monkeypatch):
    make_version(tmp_path)
    patch_launch(monkeypatch, tmp_path, fake_java(tmp_path))

    ok, msg = GameLauncher(str(tmp_path)).launch("1.20.1", "Steve", "uuid", "token")

    assert ok is True
    assert msg == "游戏已启动"


def test_missing_configured_java_falls_back_to_autodetect(tmp_path, monkeypatch):
    make_version(tmp_path)
    java = fake_java(tmp_path)
    patch_launch(monkeypatch, tmp_path, java)
    events = []

    ok, _ = GameLauncher(str(tmp_path)).launch(
        "1.20.1", "Steve", "uuid", "token",
        java_executable=str(tmp_path / "gone" / "java.exe"),
        on_progress=lambda s, t: events.append((s, t)),
    )

    steps = [s for s, _ in events]
    assert ok is True
    assert "java_warn" in steps
    java_ok = dict(events)["java_ok"]
    assert "自动检测" in java_ok
    assert java in java_ok


def test_configured_java_is_used_directly(tmp_path, monkeypatch):
    make_version(tmp_path)
    java = fake_java(tmp_path)
    patch_launch(monkeypatch, tmp_path, java)
    events = []

    ok, _ = GameLauncher(str(tmp_path)).launch(
        "1.20.1", "Steve", "uuid", "token",
        java_executable=java,
        on_progress=lambda s, t: events.append((s, t)),
    )

    assert ok is True
    assert "设置" in dict(events)["java_ok"]
    assert "java_warn" not in [s for s, _ in events]


def test_no_java_reports_java_fail(tmp_path, monkeypatch):
    make_version(tmp_path)
    patch_launch(monkeypatch, tmp_path, None)
    events = []

    ok, msg = GameLauncher(str(tmp_path)).launch(
        "1.20.1", "Steve", "uuid", "token",
        on_progress=lambda s, t: events.append((s, t)),
    )

    assert ok is False
    assert "未找到 Java" in msg
    assert events[-1][0] == "java_fail"


def test_missing_version_fails_before_spawn(tmp_path, monkeypatch):
    patch_launch(monkeypatch, tmp_path, fake_java(tmp_path))
    monkeypatch.setattr(game_mod.minecraft_launcher_lib.utils, "get_installed_versions",
                        lambda d: [])
    events = []

    ok, msg = GameLauncher(str(tmp_path)).launch(
        "1.20.1", "Steve", "uuid", "token",
        on_progress=lambda s, t: events.append((s, t)),
    )

    assert ok is False
    assert "未安装" in msg
    assert [s for s, _ in events] == ["check_version"]


def test_tail_game_log_streams_lines_and_detects_ready(tmp_path):
    log = tmp_path / "game.log"
    log.write_text("[main/INFO]: Setting user: Steve\n", encoding="utf-8")
    launcher = GameLauncher(str(tmp_path))
    launcher._process = FakeProcess()
    launcher._is_running = True
    events = []

    launcher._tail_game_log(str(log), lambda s, t: events.append((s, t)), timeout=0.4)

    assert events[0][0] == "log"
    assert "Setting user" in events[0][1]
    assert ("ready", "游戏窗口已就绪") in events


def test_tail_game_log_reports_early_exit(tmp_path):
    log = tmp_path / "game.log"
    log.write_text("", encoding="utf-8")
    launcher = GameLauncher(str(tmp_path))
    proc = FakeProcess()
    proc.returncode = 1
    launcher._process = proc
    launcher._is_running = True
    events = []

    launcher._tail_game_log(str(log), lambda s, t: events.append((s, t)), timeout=0.4)

    assert events[-1][0] == "exit"
    assert "1" in events[-1][1]


def test_extract_natives_returns_count(tmp_path, monkeypatch):
    monkeypatch.setattr(game_mod.platform, "system", lambda: "Windows")
    vdir = tmp_path / "versions" / "1.20.1"
    vdir.mkdir(parents=True)
    jar_rel = "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-windows.jar"
    jar = tmp_path / "libraries" / jar_rel
    jar.parent.mkdir(parents=True)
    with zipfile.ZipFile(jar, "w") as zf:
        zf.writestr("lwjgl.dll", b"dll")
    (vdir / "1.20.1.json").write_text(json.dumps({
        "id": "1.20.1",
        "libraries": [{
            "name": "org.lwjgl:lwjgl:3.3.1",
            "natives": {"windows": "natives-windows"},
            "downloads": {"classifiers": {"natives-windows": {"path": jar_rel}}},
        }],
    }), encoding="utf-8")

    natives = tmp_path / "versions" / "1.20.1" / "natives"
    count = GameLauncher(str(tmp_path))._extract_natives("1.20.1", "1.20.1", str(natives))

    assert count == 1
    assert (natives / "lwjgl.dll").exists()


def test_main_and_ui_wire_launch_detail():
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    html_src = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")

    assert "launchDetail = pyqtSignal(str, str)" in main_src
    assert "self.bridge.launchDetail.connect(self._on_launch_detail)" in main_src
    assert "on_progress=self.launchDetail.emit" in main_src
    assert "appendLaunchDetail(" in main_src
    assert 'id="launchDetailPanel"' in html_src
    assert "function appendLaunchDetail(" in html_src

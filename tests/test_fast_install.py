# -*- coding: utf-8 -*-
"""版本安装提速 launcher_core.fast_install：并行相位 + 合并进度。

为什么要合并进度：mll 的 install_libraries / install_assets 各自 setMax→
setProgress，这套契约隐含"相位串行"。一旦让尾部（客户端 jar / JVM 运行时）
与它们并发跑，两路 setProgress 会互相覆盖、setMax 会让相位计数跳号，进度条
就会乱跳。MergedProgress 把多路归一成"单相位 0..100"，对上游只报一次
setMax(100)，上游拿到的仍是它熟悉的形状。
"""
import threading

import pytest

from launcher_core import fast_install as fi


# ---------- MergedProgress ----------

def test_progress_reports_single_set_max_of_100():
    seen = {"max": [], "pct": []}
    mp = fi.MergedProgress({
        "setMax": seen["max"].append,
        "setProgress": seen["pct"].append,
    })
    lib = mp.phase("libraries")
    lib["setMax"](100)
    lib["setProgress"](50)
    assert seen["max"] == [100], "对上游只能报一次 setMax(100)"
    assert seen["pct"][-1] == 50


def test_progress_merges_concurrent_phases():
    seen = []
    mp = fi.MergedProgress({"setProgress": seen.append})
    lib = mp.phase("libraries")
    ast = mp.phase("assets")
    lib["setMax"](10)
    ast["setMax"](30)
    lib["setProgress"](6)
    # libraries 完成 6/10，assets 尚未开始 -> 6/(10+30)=15%
    assert seen[-1] == 15


def test_progress_never_goes_backwards():
    seen = []
    mp = fi.MergedProgress({"setProgress": seen.append})
    lib = mp.phase("libraries")
    ast = mp.phase("assets")
    lib["setMax"](100)
    lib["setProgress"](80)          # 80%
    ast["setMax"](100)              # 新相位加入会稀释分子，但不许倒退
    ast["setProgress"](0)
    assert seen == sorted(seen), "进度不得回跳: %r" % seen
    assert seen[-1] >= 80


def test_progress_clamps_when_mll_counts_past_max():
    """mll 用 setMax(len-1) 却数到 len，frac 会短暂 >1"""
    seen = []
    mp = fi.MergedProgress({"setProgress": seen.append})
    lib = mp.phase("libraries")
    lib["setMax"](9)
    lib["setProgress"](10)
    assert seen[-1] == 100
    assert max(seen) <= 100


def test_status_is_forwarded_to_upstream():
    got = []
    mp = fi.MergedProgress({"setStatus": got.append})
    mp.phase("assets")["setStatus"]("Download Assets")
    assert got == ["Download Assets"]


def test_finish_forces_100():
    seen = []
    mp = fi.MergedProgress({"setProgress": seen.append})
    mp.phase("libraries")["setMax"](10)
    mp.finish()
    assert seen[-1] == 100


def test_identical_percent_is_not_re_emitted():
    """每个 64KB 块都 emit 会把 Qt 信号队列刷爆"""
    seen = []
    mp = fi.MergedProgress({"setProgress": seen.append})
    lib = mp.phase("libraries")
    lib["setMax"](10000)
    for i in range(50):
        lib["setProgress"](i)   # 最大 49/10000=0.49%，四舍五入都是 0
    assert seen == [0], "同一整数百分比只应上报一次: %r" % seen


def test_works_without_any_upstream_callback():
    mp = fi.MergedProgress(None)
    lib = mp.phase("libraries")
    lib["setStatus"]("x")
    lib["setMax"](5)
    lib["setProgress"](3)
    mp.finish()


# ---------- 并行执行 ----------

def test_run_phases_runs_every_task():
    done = []
    fi.run_phases([lambda: done.append("a"),
                   lambda: done.append("b"),
                   lambda: done.append("c")])
    assert sorted(done) == ["a", "b", "c"]


def test_run_phases_raises_first_error():
    def boom():
        raise RuntimeError("phase failed")

    with pytest.raises(RuntimeError, match="phase failed"):
        fi.run_phases([boom, lambda: None])


def test_run_phases_runs_concurrently_not_sequentially():
    """三个相位必须真的并发，否则提速无从谈起"""
    gate = threading.Barrier(3, timeout=5)
    fi.run_phases([gate.wait, gate.wait, gate.wait])
    # barrier 未超时即三线程同时到达


# ---------- 尾部任务清单 ----------

DATA = {
    "id": "1.21",
    "downloads": {
        "client": {"url": "https://piston.example/client.jar",
                   "sha1": "a" * 40},
    },
    "logging": {
        "client": {"file": {"id": "client-1.21.xml",
                            "url": "https://piston.example/client.xml",
                            "sha1": "b" * 40}},
    },
}


def test_tail_jobs_include_client_jar_and_logging(tmp_path):
    jobs = fi.tail_jobs(DATA, tmp_path)
    urls = [j[0] for j in jobs]
    assert "https://piston.example/client.jar" in urls
    assert "https://piston.example/client.xml" in urls


def test_tail_jobs_paths_land_in_expected_dirs(tmp_path):
    jobs = {j[0]: j for j in fi.tail_jobs(DATA, tmp_path)}
    jar = jobs["https://piston.example/client.jar"][1]
    log = jobs["https://piston.example/client.xml"][1]
    assert jar.name == "1.21.jar"
    assert jar.parent == tmp_path / "versions" / "1.21"
    assert log.parent == tmp_path / "assets" / "log_configs"
    assert log.name == "client-1.21.xml"


def test_tail_jobs_carry_sha1():
    for _url, _dest, sha1 in fi.tail_jobs(DATA, "."):
        assert len(sha1) == 40, "尾部文件必须带 sha1，否则损坏不会被发现"


def test_tail_jobs_skips_missing_downloads(tmp_path):
    jobs = fi.tail_jobs({"id": "old"}, tmp_path)
    assert jobs == [], "旧版本没有 downloads 段，不得报错"


# ---------- 版本 JSON 解析 ----------

class _Resp:
    def __init__(self, payload=None, body=b""):
        self._payload = payload
        self._body = body
        self.status_code = 200
        self.headers = {"content-length": str(len(body))}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=65536):
        yield self._body


class _Sess:
    """按调用次序吐响应：先 manifest，后版本 JSON"""

    def __init__(self, responses):
        self._r = list(responses)
        self.urls = []

    def get(self, url, **kw):
        self.urls.append(url)
        return self._r.pop(0)

    def close(self):
        pass


def test_resolve_reads_existing_json_without_network(tmp_path):
    vdir = tmp_path / "versions" / "1.21"
    vdir.mkdir(parents=True)
    (vdir / "1.21.json").write_text('{"id": "1.21", "downloads": {}}',
                                    encoding="utf-8")
    sess = _Sess([])
    data = fi.resolve_version_json("1.21", tmp_path, session=sess)
    assert data["id"] == "1.21"
    assert sess.urls == [], "本地已有 JSON 不得再请求"


def test_resolve_fetches_manifest_then_json(tmp_path):
    body = b'{"id": "1.21", "downloads": {}}'
    sess = _Sess([
        _Resp(payload={"versions": [{"id": "1.21",
                                     "url": "https://m/1.21.json",
                                     "sha1": ""}]}),
        _Resp(body=body),
    ])

    data = fi.resolve_version_json("1.21", tmp_path, session=sess)

    assert data["id"] == "1.21"
    assert any("version_manifest" in u for u in sess.urls), "缺 JSON 要查 manifest"
    assert (tmp_path / "versions" / "1.21" / "1.21.json").read_bytes() == body


def test_resolve_raises_for_unknown_version(tmp_path):
    sess = _Sess([_Resp(payload={"versions": [{"id": "other"}]})])
    with pytest.raises(fi.VersionNotFound):
        fi.resolve_version_json("nope", tmp_path, session=sess)


# ---------- fast_install 装配 ----------

VANILLA = {
    "id": "1.21",
    "downloads": {"client": {"url": "https://p/c.jar", "sha1": ""}},
    "logging": {"client": {"file": {"id": "c.xml", "url": "https://l/c.xml",
                                    "sha1": ""}}},
    "javaVersion": {"component": "java-runtime-gamma"},
}


def _write_json(tmp_path, version, data):
    vdir = tmp_path / "versions" / version
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / (version + ".json")).write_text(__import__("json").dumps(data),
                                            encoding="utf-8")


def test_fast_install_launches_all_phases_in_one_pool(tmp_path, monkeypatch):
    _write_json(tmp_path, "1.21", VANILLA)
    ran = []
    monkeypatch.setattr(fi, "install_libraries", lambda *a, **k: ran.append("libraries"))
    monkeypatch.setattr(fi, "install_assets", lambda *a, **k: ran.append("assets"))
    monkeypatch.setattr(fi, "install_jvm_runtime", lambda *a, **k: ran.append("runtime"))
    monkeypatch.setattr(fi, "download_tail", lambda *a, **k: ran.append("client"))
    monkeypatch.setattr(fi, "run_phases", lambda tasks: [t() for t in tasks])

    fi.fast_install("1.21", tmp_path, callback={"setMax": lambda m: None,
                                                "setProgress": lambda p: None},
                    session=_Sess([]))

    assert sorted(ran) == ["assets", "client", "libraries", "runtime"], \
        "四个相位都要启动: %r" % ran


def test_fast_install_uses_merged_single_phase_progress(tmp_path, monkeypatch):
    _write_json(tmp_path, "1.21", VANILLA)
    for name in ("install_libraries", "install_assets", "install_jvm_runtime",
                 "download_tail"):
        monkeypatch.setattr(fi, name, lambda *a, **k: None)
    monkeypatch.setattr(fi, "run_phases", lambda tasks: [t() for t in tasks])
    maxes, pcts = [], []
    cb = {"setMax": maxes.append, "setProgress": pcts.append}

    fi.fast_install("1.21", tmp_path, callback=cb, session=_Sess([]))

    assert maxes == [100], "上游只该看到一个相位"
    assert pcts and pcts[-1] == 100, "结束必须到 100"


def test_fast_install_falls_back_when_inherits_from(tmp_path, monkeypatch):
    _write_json(tmp_path, "forge-1.21",
                {"id": "forge-1.21", "inheritsFrom": "1.21"})
    called, maxes, pcts = [], [], []

    def _fake_mll(version, mc, callback=None):
        called.append(version)
        callback["setStatus"]("Download Libraries")
        callback["setMax"](99)
        callback["setProgress"](99)

    monkeypatch.setattr(fi, "mll_install_minecraft_version", _fake_mll)
    monkeypatch.setattr(fi, "run_phases",
                        lambda tasks: pytest.fail("inheritsFrom 不得走并行路径"))

    fi.fast_install("forge-1.21", tmp_path,
                    callback={"setMax": maxes.append,
                              "setProgress": pcts.append},
                    session=_Sess([]))

    assert called == ["forge-1.21"], "Forge/NeoForge 必须回退给 mll 顺序安装"
    assert maxes == [100], "回退路径也必须归一成单相位，上游形状要统一"
    assert pcts[-1] == 100


# ---------- 下载设置 ----------

def test_settings_expose_download_tuning():
    from launcher_core.settings import Settings
    assert Settings.DEFAULT_SETTINGS["download_proxy"] == ""
    assert Settings.DEFAULT_SETTINGS["download_workers"] >= 1


def test_configure_applies_env_proxy_so_mll_follows(monkeypatch):
    import os
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    try:
        fi.configure(proxy="http://127.0.0.1:10808")
        assert os.environ.get("HTTPS_PROXY") == "http://127.0.0.1:10808"
        fi.configure(proxy="")
        assert "HTTPS_PROXY" not in os.environ, "清空代理必须同时清环境变量"
    finally:
        fi.configure(proxy="")


def test_fast_install_passes_configured_workers(tmp_path, monkeypatch):
    _write_json(tmp_path, "1.21", VANILLA)
    for name in ("install_assets", "install_jvm_runtime", "download_tail"):
        monkeypatch.setattr(fi, name, lambda *a, **k: None)
    monkeypatch.setattr(fi, "run_phases", lambda tasks: [t() for t in tasks])
    seen = {}
    monkeypatch.setattr(
        fi, "install_libraries",
        lambda *a, **k: seen.update(k))

    try:
        fi.configure(workers=8)
        fi.fast_install("1.21", tmp_path, callback={}, session=_Sess([]))
    finally:
        fi.configure(workers=None)

    assert seen.get("max_workers") == 8, "设置的并发数要传到 mll"


def test_configure_rejects_non_positive_workers():
    with pytest.raises(ValueError):
        fi.configure(workers=0)

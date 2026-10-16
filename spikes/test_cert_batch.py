"""T1.62 驱动器单测（离线：假 runner + 快时钟注入；不触网）。"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seedline import BlockEntry, Manifest, Scenario, Site  # noqa: E402


def make_manifest() -> Manifest:
    return Manifest(
        scenarios=tuple(Scenario(id=f"s{i}", title=f"场景{i}") for i in range(1, 11)),
        sites={"example.com": Site("example.com", "standard")},
        blocks=(
            BlockEntry(name="probe_a", site="example.com", scenario="s1", level="C2",
                       script="site_scripts.probe_a:browse", params={}, batch=1,
                       adapter="trace"),
            BlockEntry(name="excel_export", site=None, scenario="s8", level="C2",
                       script=None, params={}, batch=1, adapter="python"),
            BlockEntry(name="hn_search_probe", site="hn.algolia.com", scenario="s1",
                       level="C2", script="x:browse", params={}, batch=1,
                       adapter="trace", exists=True, legacy_state_key="c2"),
        ),
        path=Path("manifest.yaml"),
    )


class FastClock:
    """真实秒 ×1000 的快钟：5s 限频≈5ms，段内 45s≈45ms（单测不起真实等待）。"""

    def __init__(self):
        self._t0 = datetime(2026, 10, 16, 9, 0, 0)
        self._start = None

    def now(self):
        import time as _t

        if self._start is None:
            self._start = _t.monotonic()
        return self._t0 + timedelta(seconds=(_t.monotonic() - self._start) * 1000)


class FakeRunner:
    """包装裸函数为 RunnerPort 形态（C2Executor 经端口方法调用）。"""

    def __init__(self, fn):
        self._fn = fn

    def run_once(self, block_ref, params=None, *, mode="local", browser_factory=None):
        return self._fn(block_ref, params, mode=mode)


def make_fake_runner(ok=True):
    from forge_server.sandbox import RunOutcome

    calls = {"n": 0}

    def _run(block_ref, params=None, *, mode="local", browser_factory=None):
        calls["n"] += 1
        return RunOutcome(mode=mode, ok=ok)

    return _run, calls


@pytest.fixture
def store(tmp_path):
    d = tmp_path / "store"
    d.mkdir()
    return d


def _make_app(db_url, *, hook=None, clock=None):
    from forge_server.app import create_app

    return create_app(db_url, clock=clock or FastClock(), executor_hook=hook)


def test_submit_idempotent(store):
    from fastapi.testclient import TestClient

    from cert_batch import submit

    manifest = make_manifest()
    app = _make_app(f"sqlite:///{(store / 'server.db').as_posix()}")
    client = TestClient(app)
    ids1 = submit(store, manifest, batch=None, client=client)
    assert set(ids1) == {"probe_a", "excel_export"}  # exists 块不重复提交
    ids2 = submit(store, manifest, batch=None, client=client)
    assert ids1 == ids2
    with app.state.session_factory() as s:
        from forge_server.models import CertificationRun

        rows = s.query(CertificationRun).count()
        assert rows == 2  # 二次 submit 无新行


def test_drive_reaches_target_and_continues_on_failure(store):
    from forge_server.sandbox import RunOutcome, router_hook

    from cert_batch import drive, submit

    manifest = make_manifest()

    def boom(block_ref, params=None, *, mode="local", browser_factory=None):
        if block_ref == "excel_export":
            raise RuntimeError("站点持续不可达")
        return RunOutcome(mode=mode, ok=True)

    from fastapi.testclient import TestClient

    app = _make_app(f"sqlite:///{(store / 'server.db').as_posix()}")
    client = TestClient(app)
    run_ids = submit(store, manifest, batch=None, client=client)
    routes = {
        run_ids["probe_a"]: (FakeRunner(boom), "probe_a", {}),
        run_ids["excel_export"]: (FakeRunner(boom), "excel_export", {}),
    }
    result = drive(store, manifest, 1, app=app, routes=routes,
                   poll_s=0.0, timeout_s=20.0)
    good = result["blocks"]["probe_a"]
    bad = result["blocks"]["excel_export"]
    assert good["n"] == 10 and good["pass"] == 10
    assert bad["n"] == 10 and bad["pass"] < 10  # 单块故障：其余照常达 N，本块如实计数


def test_drive_reattaches_across_processes(store):
    """进程一 submit；进程二（无内存计划）drive 经 reattach 续跑。"""
    from forge_server.sandbox import RunOutcome, router_hook

    from cert_batch import drive, submit

    manifest = make_manifest()
    ok_runner = lambda block_ref, params=None, *, mode="local", browser_factory=None: RunOutcome(mode=mode, ok=True)  # noqa: E731

    app1 = _make_app(f"sqlite:///{(store / 'server.db').as_posix()}")
    from fastapi.testclient import TestClient

    run_ids = submit(store, manifest, batch=None, client=TestClient(app1))
    app1.state.engine.dispose()  # 进程一退出

    app2 = _make_app(f"sqlite:///{(store / 'server.db').as_posix()}")
    routes = {rid: (FakeRunner(ok_runner), name, {}) for name, rid in run_ids.items()}
    result = drive(store, manifest, 1, app=app2, routes=routes,
                   poll_s=0.0, timeout_s=20.0)
    assert result["blocks"]["probe_a"]["n"] == 10

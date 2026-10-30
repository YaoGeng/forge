"""T1.64c/T1.65e 驱动器离线单测（临时库 + 假 trace 执行器 + 真本地 python 块；不触网）。

注意：覆盖实验测试对真实 sample.json 的唯一链式样本执行一次链（纯本地块）——
这属于驱动器验证，不属实验判定（实验纪元在 ms1e_store，T1.65e 时另行恰一次执行）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
for rel in ("apps/backend", "spikes", "packages/trace/python",
            "packages/proto/python", "packages/block-sdk/python",
            "packages/certifier/python"):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient  # noqa: E402

from forge_server.chain import ChainRunner  # noqa: E402
from forge_server.models import CertificationRun  # noqa: E402
from forge_server.sandbox import AdapterRunner, RunOutcome  # noqa: E402

from product_path import SEEDS, build_server, runtime_kinds  # noqa: E402

KINDS = runtime_kinds()


class FakeTraceRunner:
    """离线替身：trace 块执行恒 ok（真实 TraceRunner 语义：output=None）。"""

    def run_once(self, ref, params=None, *, mode="local", **kw):
        return RunOutcome(mode=mode, ok=True)


def wire_test_chain(app, names):
    ar = AdapterRunner({n: SEEDS / n for n in names if KINDS.get(n) == "python"})
    routes = {}
    for n in names:
        if KINDS.get(n) == "trace":
            routes[n] = (FakeTraceRunner(), f"ref-{n}")
        else:
            routes[n] = (ar, n)
    app.state.chain_runner = ChainRunner(routes).execute


def seed_block(client, sf, name, level="C2"):
    now = datetime.now(timezone.utc)
    with sf() as s:
        row = CertificationRun(
            subject_type="block", subject_id=name, version="1.0.0", level=level,
            n=20, pass_count=20, live_pass_rate=1.0, regression_pass_rate=1.0,
            batch_id=f"seed-{name}", started_at=now - timedelta(hours=50),
            finished_at=now, verdict="pass")
        s.add(row)
        s.commit()
        rid = row.id
    r = client.post("/api/v1/registry/blocks", json={
        "name": name, "version": "1.0.0", "certification_run_id": rid,
        "side_effects": False, "domains": []})
    assert r.status_code in (200, 201), f"{name}: {r.status_code} {r.text}"
    return rid


@pytest.fixture()
def server(tmp_path):
    app = build_server(tmp_path / "store")
    client = TestClient(app)
    return app, client, tmp_path / "store"


APP_BLOCKS = {
    "hn_weekly": (["hn_search_probe", "excel_export"], "C2"),
    "books_export": (["books_list", "excel_export"], "C2"),
    "login_report": (["login_demo_probe", "excel_export"], "C1"),
    "baidu_snapshot": (["baidu_home_watch", "csv_export"], "C2"),
    "repo_digest": (["github_repo_read", "text_digest", "excel_export"], "C2"),
}


class TestAssembleApps:
    def test_five_apps_assembled_and_published(self, server):
        app, client, store = server
        for names, _lv in APP_BLOCKS.values():
            for n in names:
                seed_block(client, app.state.session_factory, n,
                           level="C1" if n == "login_demo_probe" else "C2")
        wire_test_chain(app, sorted({n for ns, _ in APP_BLOCKS.values() for n in ns}))

        from assemble_apps import run_all

        out = run_all(app, client, signer=lambda d: b"test-sig",
                      state_path=store / "t164c_state.json")
        assert out["published"] == 5
        login = next(r for r in out["apps"] if r["key"] == "login_report")
        # C8：服务端 422 证据 + 本机整链落库 + 设备签名
        assert login["c1_certify_422"], "C1 应用 certify 必须被服务端 422（M09 §3.3）"
        assert login["chain"]["verdict"] == "pass" and login["chain"]["reused"] is False
        with app.state.session_factory() as s:
            row = s.get(CertificationRun, login["chain"]["run_id"])
        assert row.level == "chain" and row.n == 1
        assert row.attestation_sig and row.subject_type == "app_version"
        # 报告读侧：C1 标注与非统计标注
        assert login["report"] is not None

    def test_rerun_idempotent_no_new_apps(self, server):
        app, client, store = server
        for names, _lv in APP_BLOCKS.values():
            for n in names:
                seed_block(client, app.state.session_factory, n,
                           level="C1" if n == "login_demo_probe" else "C2")
        wire_test_chain(app, sorted({n for ns, _ in APP_BLOCKS.values() for n in ns}))

        from assemble_apps import run_all

        sp = store / "t164c_state.json"
        run_all(app, client, signer=lambda d: b"test-sig", state_path=sp)
        before = len(client.get("/api/v1/apps").json())
        out2 = run_all(app, client, signer=lambda d: b"test-sig", state_path=sp)
        assert out2["published"] == 5
        assert all(r.get("skipped") for r in out2["apps"])
        assert len(client.get("/api/v1/apps").json()) == before

    def test_c1_chain_row_reused_not_reexecuted(self, server):
        app, client, store = server
        for names, _lv in APP_BLOCKS.values():
            for n in names:
                seed_block(client, app.state.session_factory, n,
                           level="C1" if n == "login_demo_probe" else "C2")
        wire_test_chain(app, sorted({n for ns, _ in APP_BLOCKS.values() for n in ns}))

        from assemble_apps import APPS, assemble, _load_state

        sp = store / "t164c_state.json"
        spec = next(a for a in APPS if a["key"] == "login_report")
        state = _load_state(sp)
        assemble(app, client, spec, state, sp, signer=lambda d: b"test-sig")
        runs_before = _count_chain_runs(app, "app-login_report")
        # 再次组装（state 未标 published 的中间态模拟：手动去掉 published 后重跑本机整链）
        state["apps"]["login_report"]["published"] = False
        state["apps"]["login_report"].pop("chain_run_id", None)
        assemble(app, client, spec, state, sp, signer=lambda d: b"test-sig")
        assert _count_chain_runs(app, "app-login_report") == runs_before  # 复用不重跑


def _count_chain_runs(app, app_name: str) -> int:
    from forge_server.models import App

    with app.state.session_factory() as s:
        a = s.query(App).filter_by(name=app_name).one_or_none()
        if a is None:
            return 0
        return (s.query(CertificationRun)
                .filter_by(subject_type="app_version", subject_id=str(a.id),
                           level="chain").count())


class TestRunCoverage:
    def test_experiment_offline_end_to_end(self, server):
        app, client, store = server
        # T1.78：R2 池/样本；注册 4 条链式尝试所需块（假执行器离线），26 条 uncoverable 不运行
        for n in ("text_clean", "markdown_export", "arxiv_search", "hn_search_probe"):
            seed_block(client, app.state.session_factory, n)
        wire_test_chain(app, ["text_clean", "markdown_export", "arxiv_search", "hn_search_probe"])

        from run_coverage import run_experiment

        runs_dir = store / "runs"
        report = store / "report.md"
        out = run_experiment(app, client,
                             pool_path=_ROOT / "spikes/coverage/pool_r2.json",
                             sample_path=_ROOT / "spikes/coverage/sample_r2.json",
                             runs_dir=runs_dir, report_path=report)
        assert out["denominator"] == 30 and out["executed"] == 30 and out["resumed"] == 0
        # 终审 I-1：三条 trace 链形状硬核验——假执行器零输出（entries/hits 缺）→ shape_mismatch
        # 如实不计覆盖；仅 text_clean→markdown_export（rows=5）covered。
        assert out["covered"] == 1
        assert out["categories"].get("shape_mismatch") == 3
        assert out["categories"].get("capability_missing") == 14
        assert out["categories"].get("needs_genericization") == 7
        assert out["categories"].get("site_not_covered") == 5
        rec = json.loads((runs_dir / "hn-44955461.json").read_text(encoding="utf-8"))
        assert rec["verdict"] == "covered" and rec["final_output"]["rows"] == 5
        assert rec["shape_digest"].startswith("sha256:")
        text = report.read_text(encoding="utf-8")
        assert "3.3%" in text  # 1/30（离线假执行器排练值——零输出链被形状核验拦下；真实复判见 T1.79）
        assert "人工复核" in text

    def test_resume_never_reexecutes_frozen_records(self, server):
        app, client, store = server
        seed_block(client, app.state.session_factory, "text_clean")
        seed_block(client, app.state.session_factory, "markdown_export")
        wire_test_chain(app, ["text_clean", "markdown_export"])

        from run_coverage import run_experiment

        kw = dict(pool_path=_ROOT / "spikes/coverage/pool_r2.json",
                  sample_path=_ROOT / "spikes/coverage/sample_r2.json",
                  runs_dir=store / "runs", report_path=store / "report.md")
        run_experiment(app, client, **kw)
        before = (store / "runs" / "hn-44955461.json").stat().st_mtime_ns
        out2 = run_experiment(app, client, **kw)
        assert out2["executed"] == 0 and out2["resumed"] == 30
        assert (store / "runs" / "hn-44955461.json").stat().st_mtime_ns == before

    def test_registry_gate_blocks_unregistered_chain(self, server):
        app, client, store = server
        seed_block(client, app.state.session_factory, "text_clean")
        # markdown_export 未注册
        wire_test_chain(app, ["text_clean", "markdown_export"])

        from run_coverage import execute_chain_via_dryrun, registry_names
        from coverage_runner import load_sample, run_one

        entries = load_sample(str(_ROOT / "spikes/coverage/sample_r2.json"),
                              str(_ROOT / "spikes/coverage/pool_r2.json"))
        chain_entry = next(e for e in entries
                           if e["attempt"]["kind"] == "chain" and "markdown_export"
                           in [st["block"] for st in e["attempt"]["steps"]])
        names = registry_names(client)
        assert "markdown_export" not in names
        rec = run_one(chain_entry, execute_chain_via_dryrun(client), registry=names)
        assert rec["verdict"] == "uncovered" and rec["category"] == "registry_missing"
        assert rec["ran"] is False


def test_real_signer_loads_key_from_client_keys_dir(tmp_path):
    """回归（2026-10-18 时钟日）：real_signer 应把 client_keys 目录交给 DeviceKey.load
    （load 自拼 device_key.pem）——首版误传文件路径，真实签名路径从未被彩排覆盖。"""
    from forge_certifier.device import DeviceKey

    DeviceKey.generate().save(tmp_path / "client_keys")
    from assemble_apps import real_signer

    sign = real_signer(tmp_path)
    sig = sign(b"digest-bytes")
    assert isinstance(sig, bytes) and len(sig) == 64  # ed25519


def test_wire_resolves_legacy_trace_ref_keys(tmp_path):
    """回归（2026-10-18 时钟日）：遗留块（hn_search_probe 等）的录制 ref 存在 state
    遗留键（c2/c1）下——wire 的 ref 解析须回退到 legacy_state_key，否则链执行
    KeyError「未知 trace_ref: ref-<name>」（彩排假执行器未覆盖此路径）。"""
    import json as _json

    store = tmp_path / "store"
    store.mkdir()
    (store / "state.json").write_text(_json.dumps(
        {"trace_refs": {"c2": "tr_legacy_c2", "c1": "tr_legacy_c1"}}), encoding="utf-8")

    from product_path import wire_chain_runner

    captured = {}

    def factory(trace_dirs):
        captured.update(trace_dirs)
        return object()

    class _App:
        state = type("S", (), {"chain_runner": None})()

    routes = wire_chain_runner(_App(), store, ["hn_search_probe", "login_demo_probe"],
                               trace_runner_factory=factory)
    assert routes["hn_search_probe"][1] == "tr_legacy_c2"
    assert routes["login_demo_probe"][1] == "tr_legacy_c1"
    assert set(captured) == {"tr_legacy_c2", "tr_legacy_c1"}


def test_wire_default_branch_uses_real_browser_factory(tmp_path):
    """回归（2026-10-18 时钟日第二枚）：wire 缺省分支不得把 browser_factory=None
    传给 TraceRunner——链执行时 NoneType 不可调用（假执行器/注入工厂均未覆盖缺省分支）。"""
    import json as _json

    store = tmp_path / "store"
    store.mkdir()
    (store / "state.json").write_text(_json.dumps(
        {"trace_refs": {"c2": "tr_legacy_c2"}}), encoding="utf-8")

    from product_path import wire_chain_runner

    class _App:
        state = type("S", (), {"chain_runner": None})()

    routes = wire_chain_runner(_App(), store, ["hn_search_probe"])
    tr = routes["hn_search_probe"][0]
    assert callable(getattr(tr, "_browser_factory", None))

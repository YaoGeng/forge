"""T1.31 用例矩阵：C2 本机执行器 + ResponseFixtures 最小版（M09 §3.1/M07 §3.4/§8.6；C2/C4/C5/C14）。"""
from pathlib import Path

from fake_browser import FakeBrowser
from forge_block_sdk.model import InteractionSpec
from forge_trace import Recorder, RecordingsStore, collect_golden

from forge_server import fixtures
from forge_server.fixtures import IdemVerdict, apply_default_response, verify_idempotency
from forge_server.scheduler import SegmentRunOutcome, best_effort, compute_verdict
from forge_server.sandbox import (
    UNDECLARED_CONFIRM,
    C2Executor,
    RunOutcome,
    TraceRunner,
    classify_failure,
    scheduler_hook,
)

START_STEPS = (
    {"seq": 1, "action": "nav", "ok": True, "anchor_matched": True, "snapshot_digest": "d1", "duration_ms": 1},
)


# --- 构造器 -------------------------------------------------------------------------


def make_block_dir(
    tmp_path: Path,
    *,
    name="probe",
    side_effects=False,
    with_tests=True,
    confirm_id=None,
    default_response=None,
) -> Path:
    """最小 block.yaml v2 目录；side_effects=true 时补 default_response 与幂等键钩子。"""
    d = tmp_path / name
    d.mkdir(parents=True)
    lines = [
        "schema_version: 2",
        "kind: block",
        f"name: {name}",
        "version: 1.0.0",
        "title: 测试探针",
        "site_change_tier: standard",
        f"side_effects: {'true' if side_effects else 'false'}",
        "capabilities: []",
        "permissions: []",
        "runtime:",
        "  adapter: python",
        "  entry: main.py",
        "  timeout_sec: 60",
    ]
    if default_response is not None:
        lines.append(f'default_response: "{default_response}"')
    lines.append("ai_description: 单测探针积木")
    (d / "block.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    interactions = []
    if confirm_id:
        interactions.append(
            f"- id: {confirm_id}\n  type: confirm\n  title: 确认\n  optional: false\n"
        )
    (d / "interactions.yaml").write_text("".join(interactions) or "[]\n", encoding="utf-8")

    entry = '"""单测探针入口：无能力调用。"""\n\n\ndef run(params: dict) -> dict:\n    return {"ok": True}\n'
    if side_effects:
        entry += (
            "\n\ndef idempotency_key(params: dict) -> str:\n"
            '    return "key:" + str(sorted(params.items()))\n'
        )
    (d / "main.py").write_text(entry, encoding="utf-8")
    (d / "requirements.txt").write_text("", encoding="utf-8")
    if with_tests:
        tests = d / "tests"
        tests.mkdir()
        (tests / "test.yaml").write_text(
            "assertion: schema\nexpect:\n  type: object\n", encoding="utf-8"
        )
    return d


def make_recording(root, *, url="https://example.com/search?q=hello"):
    """两步轨迹（nav+click）+ golden 采集；返回 (trace_ref, store)。"""
    browser = FakeBrowser()
    store = RecordingsStore(root)
    rec = Recorder(store, lambda: browser)
    rec.record.start("example.com")
    browser.emit_nav(url)
    browser.emit_click("#a", "a||/a")
    ref = rec.record.stop()
    return ref, store


def make_fake_runner(captcha_at=frozenset(), partial_at=frozenset(), golden_ok=True):
    """假 RunnerPort：live 第 i 次可注入 captcha/partial；golden 默认通过。"""
    state = {"live": 0}

    def _run(block_ref, params=None, *, mode="local"):
        if mode == "golden":
            return RunOutcome(mode=mode, ok=golden_ok)
        i = state["live"]
        state["live"] += 1
        if i in captcha_at:
            return RunOutcome(
                mode=mode,
                ok=False,
                failure_class="captcha_detected",
                markers=("page-captcha-flag",),
                step_results=START_STEPS,
            )
        if i in partial_at:
            return RunOutcome(mode=mode, ok=True, partial_flags=frozenset({UNDECLARED_CONFIRM}))
        return RunOutcome(mode=mode, ok=True, step_results=START_STEPS)

    class _Port:
        def run_once(self, block_ref, params=None, *, mode="local"):
            return _run(block_ref, params, mode=mode)

    return _Port()


# --- 执行器 -------------------------------------------------------------------------


def test_runner_closes_browser_after_run(tmp_path, root):
    """端口用后即闭：泄漏的 sync playwright 循环会毒化同线程后续浏览器创建（gate 实证）。"""
    ref, store = make_recording(root)
    collect_golden(ref, store=store, environment_fingerprint="fp-close")
    block = make_block_dir(tmp_path, with_tests=True)

    made = []

    class ClosingBrowser(FakeBrowser):
        def __init__(self):
            super().__init__()
            self.closed = False

        def close(self):
            self.closed = True

    def factory():
        b = ClosingBrowser()
        made.append(b)
        return b

    runner = TraceRunner(store, factory, block_dirs={ref: block})
    runner.run_once(ref, {}, mode="local")
    runner.run_once(ref, {}, mode="golden")

    assert len(made) == 2
    assert all(b.closed for b in made), "replay 端口未关闭"


def test_preflight_lint_gate(tmp_path, root):
    ref, store = make_recording(root)
    block = make_block_dir(tmp_path, with_tests=False)  # 缺 tests/test.yaml
    created = []

    def factory():
        created.append(1)
        return FakeBrowser()

    runner = TraceRunner(store, factory, block_dirs={ref: block})
    outcome = runner.run_once(ref)

    assert outcome.ok is False
    assert "preflight_rejected" in outcome.partial_flags
    assert outcome.failure_class is None
    assert created == []  # 前置拒绝不触浏览器
    assert compute_verdict("standard", 1.0, 1.0, outcome.partial_flags) == "rejected"


def test_run_once_live_and_regression(tmp_path, root):
    ref, store = make_recording(root)
    collect_golden(ref, store=store, environment_fingerprint="fp-t131")
    block = make_block_dir(tmp_path, with_tests=True)

    runner = TraceRunner(store, FakeBrowser, block_dirs={ref: block})
    live = runner.run_once(ref, {}, mode="local")
    reg = runner.run_once(ref, {}, mode="golden")

    assert live.ok and reg.ok
    assert live.mode == "local" and reg.mode == "golden"
    assert len(live.step_results) == 2 and all(r["ok"] for r in live.step_results)
    assert live.failure_class is None

    # C9 形状键格式（METHOD host path?排序查询键名，不含值）：FakeBrowser 回放面不产出
    # 网络事件，形状构造单独断言（真实适配器经 port.drain_network 供给）。
    from forge_proto.trace import NetworkEntry

    from forge_server.sandbox import _network_shape

    shape = _network_shape(
        [
            NetworkEntry(
                url="https://example.com/search?q=b&lang=en&page=9",
                method="GET",
                status=200,
                mime_type=None,
                request_body=None,
                response_body=None,
            )
        ]
    )
    assert shape == frozenset({"GET example.com /search?lang|page|q"})


def test_failure_classification(tmp_path, root):
    # 分类纯函数：C4 枚举主路径
    assert (
        classify_failure(
            ({"seq": 1, "action": "click", "ok": False, "anchor_matched": False},)
        )
        == "selector_missing"
    )
    assert (
        classify_failure(
            ({"seq": 1, "action": "click", "ok": False, "anchor_matched": True},)
        )
        == "anchor_mismatch"
    )
    assert classify_failure(START_STEPS, markers=("captcha",)) == "captcha_detected"
    assert classify_failure(START_STEPS, timed_out=True) == "component_timeout"
    assert classify_failure(START_STEPS) is None

    # TraceRunner 超时守卫走真实路径（预算 0s → 必超时）
    ref, store = make_recording(root)
    block = make_block_dir(tmp_path, with_tests=True)
    runner = TraceRunner(store, FakeBrowser, block_dirs={ref: block}, run_timeout_s=0.0)
    assert runner.run_once(ref).failure_class == "component_timeout"


def test_captcha_counts_as_fail(make_scheduler, clock, drain, get_row, tmp_path):
    runner = make_fake_runner(captcha_at={5, 12})
    sched = make_scheduler(
        hook=scheduler_hook(C2Executor(), runner, block_ref="probe", clock=clock)
    )
    run_id = sched.submit("block", "probe", "1.0.0", "C2")
    drain(sched, clock)

    row = get_row(sched, run_id)
    assert row.n == 20
    assert row.pass_count == 18
    fails = row.fail_json["failures"]
    assert len(fails) == 2 and all(f["failure_class"] == "captcha_detected" for f in fails)
    assert row.verdict == "pass"  # 18/20 达 standard 阈值；captcha 计入 N，不触发 partial


def test_undeclared_confirm_partial(make_scheduler, clock, drain, get_row):
    runner = make_fake_runner(partial_at=set(range(20)))
    sched = make_scheduler(
        hook=scheduler_hook(C2Executor(), runner, block_ref="probe", clock=clock)
    )
    run_id = sched.submit("block", "probe", "1.0.0", "C2")
    drain(sched, clock)

    row = get_row(sched, run_id)
    assert row.verdict == "partial"  # 未声明 confirm → 不可上架口径


def test_compute_verdict_matrix():
    at_threshold = {"standard": 0.90, "medium": 0.85, "high": 0.0}
    below = {"standard": 0.89, "medium": 0.84, "high": 0.0}
    for tier, rate in at_threshold.items():
        assert compute_verdict(tier, rate, 1.0, frozenset()) == "pass", tier
    for tier, rate in below.items():
        expected = "pass" if tier == "high" else "below_threshold"  # high 不设下限
        assert compute_verdict(tier, rate, 1.0, frozenset()) == expected, tier
    for tier in ("standard", "medium", "high"):
        assert compute_verdict(tier, 1.0, 1.0, frozenset({"captcha_shortfall"})) == "partial", tier
    # protected（受防护）与 high 同档：不设下限 + best-effort 标注
    assert compute_verdict("protected", 0.3, 0.3, frozenset()) == "pass"
    assert best_effort("protected") is True


def test_live_never_uses_golden_runs(clock):
    modes = []

    class _Port:
        def __init__(self, local_ok, golden_ok):
            self.local_ok = local_ok
            self.golden_ok = golden_ok

        def run_once(self, block_ref, params=None, *, mode="local"):
            modes.append(mode)
            return RunOutcome(
                mode=mode,
                ok=self.local_ok if mode == "local" else self.golden_ok,
                failure_class=None if (mode == "local") == bool(self.local_ok) else "anchor_mismatch",
            )

    summary = C2Executor().run(1, "probe", {}, runner=_Port(local_ok=True, golden_ok=False), clock=clock)
    assert modes == ["local", "golden"]  # 同批双通道
    assert summary.live_ok is True  # live 聚合只含 mode=local 结果
    assert summary.regression_ok is False  # golden 只进回归口径
    assert summary.failure_class is None  # live 失败归因不取 golden

    summary2 = C2Executor().run(2, "probe", {}, runner=_Port(local_ok=False, golden_ok=True), clock=clock)
    assert summary2.live_ok is False and summary2.regression_ok is True


# --- ResponseFixtures 最小版 -----------------------------------------------------------


CONFIRM_INTERACTIONS = (
    InteractionSpec(id="confirm_publish", type="confirm", title="确认发布", schema=None, optional=False, site=None),
)


def test_fixture_default_response():
    ans = apply_default_response(
        CONFIRM_INTERACTIONS, lambda: "confirm_publish", default_response="yes"
    )
    assert ans.declared is True
    assert ans.value == "yes"  # 自动应答值逐字

    assert apply_default_response(CONFIRM_INTERACTIONS, lambda: None) is None  # 无 confirm 触发

    undeclared = apply_default_response(
        CONFIRM_INTERACTIONS, lambda: "confirm_other", default_response="yes"
    )
    assert undeclared.declared is False  # 未声明 → 调用方置 partial 标记
    assert undeclared.value is None


def test_fixture_idempotency_two_pass(tmp_path):
    block = make_block_dir(tmp_path, name="side_effect_probe", side_effects=True, default_response="ok")
    params = {"q": "hello", "page": "2"}
    seen = []

    def invoke(key):
        seen.append(key)
        return {"echo": key}

    verdict = verify_idempotency(block, params, invoke)
    assert isinstance(verdict, IdemVerdict)
    assert verdict.ok is True
    assert verdict.passes == 2
    assert seen[0] == seen[1] == verdict.key  # 两遍执行且 key 一致

    # key 漂移：第一遍执行改写 params → 第二遍 key 不同 → 失败
    mutable = {"q": "hello"}

    def drifting(key):
        mutable["q"] = mutable["q"] + "!"
        return key

    drift = verify_idempotency(block, mutable, drifting)
    assert drift.ok is False

    # 只读积木：不适用幂等两遍
    ro_block = make_block_dir(tmp_path, name="ro_probe", side_effects=False)
    ro = verify_idempotency(ro_block, params, invoke)
    assert ro.ok is True and ro.passes == 0

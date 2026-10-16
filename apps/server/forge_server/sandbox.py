"""C2 本机执行器（docs/12 C2 裁定）：RunnerPort（validate+lint 前置门 + forge_trace replay 双通道）
+ C2Executor 单 run 聚合 + classify_failure（C4 枚举）。两时段编排归 CertScheduler。
"""
import logging
import time
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import parse_qsl, urlsplit

from forge_block_sdk import lint, validate_block_dir
from forge_block_sdk.validate import ValidationError as BlockValidationError
from forge_trace import replay

from .scheduler import best_effort, compute_verdict  # noqa: F401  （C5 判定单一来源，经此再出口）

_LOG = logging.getLogger(__name__)

PREFLIGHT_REJECTED = "preflight_rejected"
UNDECLARED_CONFIRM = "undeclared_confirm"


@dataclass(frozen=True)
class RunOutcome:
    """单次运行（单通道）结果：步骤结果 + 归因 + 网络行为形状（C9 比对消费）。"""

    mode: str  # local / golden
    ok: bool
    step_results: tuple[dict, ...] = ()
    failure_class: str | None = None
    markers: tuple[str, ...] = ()
    network_shape: frozenset[str] = frozenset()
    timed_out: bool = False
    partial_flags: frozenset[str] = frozenset()


class RunnerPort(Protocol):
    def run_once(
        self, block_ref: str, params: dict[str, str] | None = None, *, mode: str = "local"
    ) -> RunOutcome: ...


def classify_failure(
    step_results, *, markers: tuple[str, ...] = (), timed_out: bool = False
) -> str | None:
    """C4：component_timeout > captcha_detected > selector_missing / anchor_mismatch。"""
    if timed_out:
        return "component_timeout"
    if any("captcha" in str(m).lower() for m in markers):
        return "captcha_detected"
    failed = [r for r in step_results if not r.get("ok")]
    if not failed:
        return None
    if any(not r.get("anchor_matched") for r in failed):
        return "selector_missing"
    return "anchor_mismatch"


def _network_shape(entries) -> frozenset[str]:
    """C9 形状键 v1：METHOD host path?排序查询键名（不含值，与 C8 占位符边界一致）。"""
    shape = set()
    for e in entries:
        parts = urlsplit(e.url)
        keys = "|".join(sorted(k for k, _ in parse_qsl(parts.query, keep_blank_values=True)))
        shape.add(f"{e.method} {parts.netloc} {parts.path}?{keys}")
    return frozenset(shape)


class TraceRunner:
    """真实 RunnerPort：提交前置 validate_block_dir + lint 门（拒绝即 rejected 不排期、
    不触浏览器）；执行 = forge_trace replay.run（local=live / golden=regression）。"""

    def __init__(self, store, browser_factory, *, block_dirs=None, run_timeout_s: float = 120.0):
        self._store = store
        self._browser_factory = browser_factory
        self._block_dirs = dict(block_dirs or {})
        self._timeout_s = run_timeout_s
        self._last_port = None

    def _wrapped_factory(self):
        def make():
            port = self._browser_factory()
            self._last_port = port
            return port

        return make

    def run_once(self, block_ref: str, params: dict[str, str] | None = None, *, mode: str = "local") -> RunOutcome:
        block_dir = self._block_dirs.get(block_ref)
        if block_dir is None:
            return RunOutcome(
                mode=mode, ok=False, partial_flags=frozenset({PREFLIGHT_REJECTED})
            )
        try:
            validate_block_dir(block_dir)
        except BlockValidationError as exc:
            return RunOutcome(
                mode=mode, ok=False, partial_flags=frozenset({PREFLIGHT_REJECTED}),
                markers=(f"validate: {exc}",),
            )
        lint_result = lint(block_dir)
        if not lint_result.ok:
            rule_ids = tuple(v["rule_id"] for v in lint_result.violations if v["severity"] == "error")
            return RunOutcome(
                mode=mode, ok=False, partial_flags=frozenset({PREFLIGHT_REJECTED}),
                markers=(f"lint: {','.join(rule_ids)}",),
            )

        self._last_port = None
        t0 = time.perf_counter()
        result = replay.run(
            block_ref, dict(params or {}), mode=mode, store=self._store,
            browser_factory=self._wrapped_factory(),
        )
        timed_out = (time.perf_counter() - t0) > self._timeout_s
        shape = frozenset()
        port = self._last_port
        if port is not None and hasattr(port, "drain_network"):
            shape = _network_shape(port.drain_network())
        failure = classify_failure(result.step_results, timed_out=timed_out)
        return RunOutcome(
            mode=mode,
            ok=failure is None,
            step_results=tuple(result.step_results),
            failure_class=failure,
            network_shape=shape,
            timed_out=timed_out,
        )


@dataclass(frozen=True)
class C2Summary:
    """单 run 聚合：live/regression 双通道各自成立，不混算（G6）。"""

    cert_run_id: int
    live_ok: bool
    regression_ok: bool
    failure_class: str | None
    partial_flags: frozenset[str]
    live_outcome: RunOutcome
    regression_outcome: RunOutcome
    finished_at: object | None = None


class C2Executor:
    def run(
        self,
        cert_run_id: int,
        block_ref: str,
        params: dict[str, str] | None = None,
        *,
        runner: RunnerPort,
        clock=None,
    ) -> C2Summary:
        live = runner.run_once(block_ref, params, mode="local")
        regression = runner.run_once(block_ref, params, mode="golden")
        flags = set(live.partial_flags) | set(regression.partial_flags)
        return C2Summary(
            cert_run_id=cert_run_id,
            live_ok=live.ok,
            regression_ok=regression.ok,
            failure_class=live.failure_class,
            partial_flags=frozenset(flags),
            live_outcome=live,
            regression_outcome=regression,
            finished_at=clock.now() if clock is not None else None,
        )


def scheduler_hook(
    executor: C2Executor,
    runner: RunnerPort,
    *,
    block_ref: str,
    params: dict[str, str] | None = None,
    clock=None,
) -> Callable[[int, int, int], "object"]:
    """桥接 CertScheduler.executor_hook：单 run 聚合 → SegmentRunOutcome。

    执行器崩溃如实归因 env_error；该次不计数会导致 N 不足，走 partial（C5）。
    """
    from .scheduler import SegmentRunOutcome

    def hook(run_id: int, segment: int, index: int) -> SegmentRunOutcome:
        try:
            summary = executor.run(run_id, block_ref, params, runner=runner, clock=clock)
        except Exception:
            _LOG.warning("C2 执行器异常 run_id=%s block=%s", run_id, block_ref, exc_info=True)
            return SegmentRunOutcome(
                live_ok=False,
                regression_ok=False,
                failure_class="env_error",
                partial_flags=frozenset({"captcha_shortfall"}),
            )
        return SegmentRunOutcome(
            live_ok=summary.live_ok,
            regression_ok=summary.regression_ok,
            failure_class=summary.failure_class,
            partial_flags=summary.partial_flags,
        )

    return hook

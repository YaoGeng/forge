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
    output: dict | None = None  # python 适配块产物（ChainRunner 上下文传递消费）


class RunnerPort(Protocol):
    def run_once(
        self,
        block_ref: str,
        params: dict[str, str] | None = None,
        *,
        mode: str = "local",
        browser_factory=None,  # C11：certify 每轮注入一次性 profile 工厂；缺省用构造时工厂
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

    def __init__(self, store, browser_factory, *, block_dirs=None, run_timeout_s: float = 120.0,
                 scripts: dict[str, object] | None = None):
        self._store = store
        self._browser_factory = browser_factory
        self._block_dirs = dict(block_dirs or {})
        self._timeout_s = run_timeout_s
        self._scripts = dict(scripts or {})  # T1.71：block_ref → browse(port)，回放后执行取输出
        self._last_port = None

    def _capture_factory(self, base):
        """包装工厂捕获端口：replay 自身不关端口，泄漏的 sync playwright 循环会
        毒化同线程后续浏览器创建（gate 实证），故 Runner 用后即闭。"""

        def make():
            port = base()
            self._last_port = port
            return port

        return make

    def run_once(
        self,
        block_ref: str,
        params: dict[str, str] | None = None,
        *,
        mode: str = "local",
        browser_factory=None,
    ) -> RunOutcome:
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
        port = None
        try:
            result = replay.run(
                block_ref, dict(params or {}), mode=mode, store=self._store,
                browser_factory=self._capture_factory(browser_factory or self._browser_factory),
                script=self._scripts.get(block_ref),
            )
        finally:
            port, self._last_port = self._last_port, None
            if port is not None and hasattr(port, "drain_network"):
                try:
                    shape_drained = _network_shape(port.drain_network())
                except Exception:
                    shape_drained = frozenset()
            else:
                shape_drained = frozenset()
            if port is not None and hasattr(port, "close"):
                try:
                    port.close()
                except Exception:
                    pass
        timed_out = (time.perf_counter() - t0) > self._timeout_s
        shape = shape_drained
        failure = classify_failure(result.step_results, timed_out=timed_out)
        # T1.71 口径（Review Focus 3）：output 仅透传（trace 块与 python 块同语义），
        # 不进 golden 对拍/相似度判定——步结果才判 ok，脚本抽取值只随 RunOutcome 下行。
        return RunOutcome(
            mode=mode,
            ok=failure is None,
            step_results=tuple(result.step_results),
            failure_class=failure,
            network_shape=shape,
            timed_out=timed_out,
            output=result.script_output,
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


def router_hook(
    routes: dict[int, tuple[RunnerPort, str, dict[str, str] | None]],
    *,
    clock=None,
) -> Callable[[int, int, int], "object"]:
    """多积木并发认证分发（docs/13 T1.62）：run_id → (runner, block_ref, params)。

    未登记 run_id 如实计 env_error（该次不计数 → N 不足走 partial）。
    """
    executors: dict[int, Callable] = {}

    def hook(run_id: int, segment: int, index: int):
        bridge = executors.get(run_id)
        if bridge is None:
            try:
                runner, block_ref, params = routes[run_id]
            except KeyError:
                _LOG.warning("router 未登记 run_id=%s", run_id)
                from .scheduler import SegmentRunOutcome

                return SegmentRunOutcome(
                    live_ok=False, regression_ok=False, failure_class="env_error",
                    partial_flags=frozenset({"captcha_shortfall"}),  # 缓办#11：与执行器异常路径同 flag（verdict 走 partial）
                )
            bridge = scheduler_hook(C2Executor(), runner, block_ref=block_ref,
                                    params=params, clock=clock)
            executors[run_id] = bridge
        return bridge(run_id, segment, index)

    return hook


class AdapterRunner:
    """python 适配块执行器（docs/13 C5）：local=真执行；golden=重执行+输出对拍快照。

    block_dirs: block_ref → 积木目录；expected_output.json 由产线 snapshot 首跑生成。
    """

    def __init__(self, block_dirs: dict[str, object]):
        self._block_dirs = dict(block_dirs)

    def _execute(self, block_ref: str, params: dict | None) -> dict:
        import importlib.util

        d = self._block_dirs.get(block_ref)
        if d is None:
            raise KeyError(f"AdapterRunner 未登记 block_ref={block_ref!r}")
        spec = importlib.util.spec_from_file_location(f"adapter_{block_ref}", d / "main.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return dict(mod.run(dict(params or {})))

    @staticmethod
    def _canonical(output: dict) -> str:
        import json

        return json.dumps(output, ensure_ascii=False, sort_keys=True)

    def run_once(
        self,
        block_ref: str,
        params: dict[str, str] | None = None,
        *,
        mode: str = "local",
        browser_factory=None,
    ) -> RunOutcome:
        d = self._block_dirs.get(block_ref)
        try:
            output = self._execute(block_ref, params)
        except Exception as exc:
            _LOG.warning("python 块执行异常 block=%s: %s", block_ref, exc, exc_info=True)
            return RunOutcome(mode=mode, ok=False, failure_class="env_error")
        if mode == "local":
            return RunOutcome(mode=mode, ok=True, output=output)
        import json

        golden = d / "tests" / "golden" / "expected_output.json"
        try:
            expected = json.loads(golden.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return RunOutcome(mode=mode, ok=False, failure_class="env_error")
        if self._canonical(expected) == self._canonical(output):
            return RunOutcome(mode=mode, ok=True, output=output)
        return RunOutcome(mode=mode, ok=False, failure_class="anchor_mismatch")

"""ChainRunner（docs/17 T2.10 移植）：与 apps/server/forge_server/chain.py 同契约。

一致性由 apps/runner/tests/test_chain.py 对照测试钉死——两处改动必须同步
（docs/17 A4 会签制）。执行语义：线性管线、字面量 params + "块名.出参键" 绑定、
单步失败即停并如实归因。RunOutcome 为本地同构定义（不依赖 forge_server）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunOutcome:
    """单次块运行结果（与 forge_server.sandbox.RunOutcome 同构）。"""

    mode: str
    ok: bool
    step_results: tuple[dict, ...] = ()
    failure_class: str | None = None
    markers: tuple[str, ...] = ()
    network_shape: frozenset[str] = frozenset()
    timed_out: bool = False
    partial_flags: frozenset[str] = frozenset()
    output: dict | None = None


class BindingError(KeyError):
    """绑定键在上下文中不存在（画布兼容性校验的运行时兜底）。"""


class ChainRunner:
    """routes: {block_name: (RunnerPort, block_ref)}；执行 composition 一次。"""

    def __init__(self, routes: dict[str, tuple[object, str]]):
        self._routes = dict(routes)

    def execute(self, composition: list[dict], params: dict | None = None) -> dict:
        context: dict[str, dict] = {}
        steps: list[dict] = []
        ok_all = True
        merged = dict(params or {})
        for i, step in enumerate(composition):
            name = step.get("block")
            entry = self._routes.get(name)
            step_view = {"index": i, "block": name}
            if entry is None:
                step_view.update(ok=False, failure_class="env_error",
                                 error=f"未登记块 {name!r}")
                steps.append(step_view)
                ok_all = False
                break
            runner, ref = entry
            call_params = dict(step.get("params") or {})
            for arg, source in (step.get("bindings") or {}).items():
                src_block, _, src_key = source.partition(".")
                try:
                    call_params[arg] = context[src_block][src_key]
                except (KeyError, TypeError):
                    raise BindingError(
                        f"步骤 {i}（{name}）绑定 {arg}←{source} 在上下文中不存在")
            try:
                outcome: RunOutcome = runner.run_once(ref, call_params, mode="local")
            except Exception as exc:  # noqa: BLE001 —— 单步失败如实归因，不静默
                step_view.update(ok=False, failure_class="env_error",
                                 error=f"{type(exc).__name__}: {exc}")
                steps.append(step_view)
                ok_all = False
                break
            step_view.update(ok=bool(outcome.ok),
                             failure_class=outcome.failure_class)
            steps.append(step_view)
            if not outcome.ok:
                ok_all = False
                break
            if outcome.output is not None:
                context[name] = dict(outcome.output)
        return {"ok": ok_all, "steps": steps, "context": context}

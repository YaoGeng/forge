"""ChainRunner：应用管线执行（docs/13 C7）——线性管线、上下文绑定传递。

⚠ 锚定声明（docs/17 T2.10）：本文件存在 runner 侧移植副本
apps/runner/forge_runner/chain.py，一致性由 runner tests/test_chain.py
对照测试钉死——两侧任何改动必须同步（A4 会签制）。

执行语义：composition 每步 {block, params{字面量}|bindings{"入参": "上游块.出参键"}}；
站点块经注入的 (runner, ref) 以 mode=local 真实执行；上一步输出并入上下文
（以块名命名空间），绑定键按 "块名.键" 解析。ChainRunner 是端口注入的编排器，
不自带运行时。
"""
from __future__ import annotations

from .sandbox import RunOutcome


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

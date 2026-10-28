"""块执行适配（docs/17 T2.12）：解包目录 → ChainRunner 路由。

判定：块目录含 trace/manifest.yaml → 站点块（replay 回放 + script.py 抽取输出）；
否则 python 适配块（main.py run(params)）。锚：docs/17 块包增补裁定——
trace/ 与 script.py 随块包分发（spikes/upload_bundles.py 负责灌库侧打包）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from .chain import RunOutcome


class BlockExecutionError(Exception):
    """块装配失败（缺文件/脚本不可导入）——中文可读。"""


def load_script(block_dir: Path):
    """trace 块的输出抽取脚本：<block>/script.py 的 browse(port) -> dict。"""
    script = block_dir / "script.py"
    if not script.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"forgescript_{block_dir.name}", script)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 —— 装配失败如实抛出
        raise BlockExecutionError(f"块 {block_dir.name} 的 script.py 导入失败：{exc}")
    browse = getattr(mod, "browse", None)
    return browse if callable(browse) else None


class StaticTraceStore:
    """replay.run 的只读静态 store：包内 trace 目录直读；无 sqlite 登记。

    mark_fragile 为 no-op（fragile 标记是录制侧能力，买家运行只读）。"""

    def __init__(self, app_dir: Path):
        self._app_dir = app_dir

    def get(self, trace_ref: str):
        d = self._app_dir / trace_ref / "trace"
        if not (d / "manifest.yaml").exists():
            raise KeyError(f"包内无该块的 trace：{trace_ref}")
        return SimpleNamespace(trace_dir=d, fragile_steps=(), annotations=())

    def mark_fragile(self, trace_ref, seqs) -> None:  # noqa: ARG002
        pass


class PythonBlockPort:
    """python 适配块：import main.py 调 run(params)（与 server AdapterRunner 同语义）。"""

    def __init__(self, block_dirs: dict[str, Path]):
        self._dirs = dict(block_dirs)

    def run_once(self, ref, params=None, *, mode="local", browser_factory=None):
        d = self._dirs.get(ref)
        if d is None:
            return RunOutcome(mode=mode, ok=False, failure_class="env_error")
        spec = importlib.util.spec_from_file_location(f"forgeblock_{ref}", d / "main.py")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            output = dict(mod.run(dict(params or {})))
        except Exception as exc:  # noqa: BLE001 —— 执行异常如实归因
            return RunOutcome(mode=mode, ok=False, failure_class="env_error",
                              markers=(f"{type(exc).__name__}: {exc}",))
        return RunOutcome(mode=mode, ok=True, output=output)


class TraceBlockPort:
    """站点块：forge_trace replay.run（local=live 真实执行）+ script 抽取输出。"""

    def __init__(self, app_dir: Path, browser_factory, block_dirs: dict[str, Path]):
        self._store = StaticTraceStore(app_dir)
        self._factory = browser_factory
        self._dirs = dict(block_dirs)

    def run_once(self, ref, params=None, *, mode="local", browser_factory=None):
        from forge_trace import replay

        browse = load_script(self._dirs[ref])
        port = None
        try:
            result = replay.run(
                str(ref), dict(params or {}), mode="local",
                store=self._store,
                browser_factory=browser_factory or self._factory,
                script=browse,
            )
            steps = tuple(dict(s) for s in result.step_results)
            ok_all = all(s["ok"] for s in steps)
            failure = None
            if not ok_all:
                failed = [s for s in steps if not s["ok"]]
                failure = ("selector_missing"
                           if any(not s["anchor_matched"] for s in failed) else None)
            output = dict(result.script_output) if result.script_output else None
            return RunOutcome(mode="local", ok=ok_all, step_results=steps,
                              failure_class=failure, output=output)
        except Exception as exc:  # noqa: BLE001 —— 端口/回放异常如实归因并留痕
            import logging

            logging.getLogger(__name__).warning(
                "站点块执行异常 block=%s: %s", ref, exc, exc_info=True)
            return RunOutcome(mode="local", ok=False, failure_class="env_error",
                              markers=(f"{type(exc).__name__}: {exc}",))
        finally:
            # replay 不关端口（与 server TraceRunner 同款纪律：用后即闭防泄漏）
            if port is not None and hasattr(port, "close"):
                try:
                    port.close()
                except Exception:  # noqa: BLE001
                    pass


def build_routes(app_dir: Path, browser_factory=None) -> dict[str, tuple[object, str]]:
    """app.json composition → {block_name: (port, block_name)}。

    browser_factory 仅在存在站点块时必需（python-only 应用不起浏览器）。"""
    import json

    composition = json.loads(
        (app_dir / "app.json").read_text(encoding="utf-8"))["composition"]
    names = [s["block"] for s in composition if s.get("block")]
    trace_dirs, py_dirs = {}, {}
    for name in names:
        d = app_dir / name
        if not d.is_dir():
            raise BlockExecutionError(f"应用包缺块目录：{name}")
        if (d / "trace" / "manifest.yaml").exists():
            trace_dirs[name] = d
        else:
            py_dirs[name] = d
    routes: dict[str, tuple[object, str]] = {}
    if trace_dirs:
        if browser_factory is None:
            from .browser import make_factory

            browser_factory = make_factory()
        port = TraceBlockPort(app_dir, browser_factory, trace_dirs)
        for name in trace_dirs:
            routes[name] = (port, name)
    if py_dirs:
        port = PythonBlockPort(py_dirs)
        for name in py_dirs:
            routes[name] = (port, name)
    return routes

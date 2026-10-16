"""T1.64c/T1.65e 共享装配：forge_server 应用 + 按块名 ChainRunner 路由（产品路径）。

- build_server(store_dir)：create_app 指向 store 的 server.db（与 MS-1E/1F 同库）。
- wire_chain_runner(app, store_dir, names, ...)：trace 块→TraceRunner（ref 取 state.trace_refs），
  python 块→AdapterRunner；app.state.chain_runner = ChainRunner(routes).execute。
  dryrun/chain-cert 走的就是这个执行器（C5 产品路径唯一通道）。本模块只装配，不触网
  （browser_factory 可注入假件；TraceRunner 造出来不等于起浏览器）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for rel in (
    "packages/trace/python",
    "packages/proto/python",
    "packages/block-sdk/python",
    "packages/certifier/python",
    "apps/server",
    "spikes",
):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from forge_server.chain import ChainRunner  # noqa: E402
from forge_server.sandbox import AdapterRunner, TraceRunner  # noqa: E402
from forge_server.scheduler import WallClock  # noqa: E402

SEEDS = _ROOT / "spikes" / "seed_blocks"


def adapter_kinds() -> dict[str, str]:
    from seedline import load_manifest

    manifest = load_manifest(SEEDS / "manifest.yaml")
    return {b.name: b.adapter for b in manifest.blocks}


def build_server(store_dir: Path):
    from forge_server.app import create_app

    Path(store_dir).mkdir(parents=True, exist_ok=True)
    app = create_app(f"sqlite:///{(Path(store_dir) / 'server.db').as_posix()}",
                     clock=WallClock())
    return app


def wire_chain_runner(app, store_dir: Path, names, *, browser_factory=None,
                      adapters: dict[str, str] | None = None,
                      trace_runner_factory=None) -> dict[str, tuple[object, str]]:
    """按块名装配路由并挂到 app.state.chain_runner；返回 routes（测试可复用）。

    adapters: {name: "trace"|"python"}（缺省从 manifest 推导）。
    trace_runner_factory: callable(trace_dirs) → RunnerPort——离线彩排/单测注入假件；
    缺省用真实 TraceRunner（构造不触网，执行才起浏览器）。
    """
    state_path = Path(store_dir) / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    refs = state.get("trace_refs", {})
    kinds = adapters if adapters is not None else adapter_kinds()

    trace_dirs: dict[str, Path] = {}
    py_dirs: dict[str, Path] = {}
    name_to_ref: dict[str, str] = {}
    for name in names:
        if kinds.get(name) == "trace":
            ref = refs.get(name, f"ref-{name}")
            name_to_ref[name] = ref
            trace_dirs[ref] = SEEDS / name
        else:
            py_dirs[name] = SEEDS / name

    routes: dict[str, tuple[object, str]] = {}
    if trace_dirs:
        if trace_runner_factory is not None:
            tr = trace_runner_factory(trace_dirs)
        else:
            from forge_trace import RecordingsStore

            tr = TraceRunner(RecordingsStore(Path(store_dir)), browser_factory,
                             block_dirs=trace_dirs)
        for name, ref in name_to_ref.items():
            routes[name] = (tr, ref)
    if py_dirs:
        ar = AdapterRunner(py_dirs)
        for name in py_dirs:
            routes[name] = (ar, name)
    app.state.chain_runner = ChainRunner(routes).execute
    return routes

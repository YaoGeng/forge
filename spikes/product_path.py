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
    "apps/backend",
    "spikes",
):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from forge_server.chain import ChainRunner  # noqa: E402
from forge_server.sandbox import AdapterRunner, TraceRunner  # noqa: E402
from forge_server.scheduler import WallClock  # noqa: E402

SEEDS = _ROOT / "spikes" / "seed_blocks"

# 保留清单（A.9 R2 ⑤）运行时镜像：s2/s10 原块移出 manifest blocks[]（文件尾注释为正本），
# 但注册/认证留存——装配仍须按原 adapter 接线、遗留 ref 键仍须可解析（五应用不动）。
# 两处登记须同步改：manifest.yaml 文件尾 + 本常量。
RETAINED_BLOCKS = {
    "login_demo_probe": {"adapter": "trace", "legacy_state_key": "c1"},
    "price_calc": {"adapter": "python", "legacy_state_key": None},
    "stats_summary": {"adapter": "python", "legacy_state_key": None},
    "unit_convert": {"adapter": "python", "legacy_state_key": None},
}


def adapter_kinds() -> dict[str, str]:
    from seedline import load_manifest

    manifest = load_manifest(SEEDS / "manifest.yaml")
    return {b.name: b.adapter for b in manifest.blocks}


def runtime_kinds() -> dict[str, str]:
    """装配用 adapter 全集 = manifest v2 blocks[] ⊕ 保留清单（wire_chain_runner 缺省同款）。"""
    kinds = {k: v["adapter"] for k, v in RETAINED_BLOCKS.items()}
    kinds.update(adapter_kinds())
    return kinds


def load_trace_scripts(name_to_ref: dict[str, str]) -> dict[str, object]:
    """T1.71：trace 块 manifest script 引用 → {block_ref: browse 可调用}。

    python 块与无 script 引用的块不装载；ref 缺失（未录制）不装载（回放本就找不到 ref）。
    脚本导入失败如实跳过 + 告警（终审 I-1：块退化为无输出须可观测，不得静默）。
    """
    import importlib
    import logging

    from seedline import load_manifest

    log = logging.getLogger(__name__)
    out: dict[str, object] = {}
    for b in load_manifest(SEEDS / "manifest.yaml").blocks:
        ref = name_to_ref.get(b.name)
        if b.adapter != "trace" or not b.script or ref is None:
            continue
        module, _, fn = b.script.partition(":")
        try:
            out[ref] = getattr(importlib.import_module(module), fn)
        except (ImportError, AttributeError):
            log.warning("trace 脚本装载失败（该块退化为无输出）：%s", b.script)
    return out


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
    kinds = dict(adapters) if adapters is not None else runtime_kinds()
    from seedline import load_manifest

    legacy_keys = {b.name: b.legacy_state_key for b in load_manifest(SEEDS / "manifest.yaml").blocks
                   if getattr(b, "legacy_state_key", None)}
    legacy_keys.update({k: v["legacy_state_key"] for k, v in RETAINED_BLOCKS.items()
                        if v["legacy_state_key"]})

    def _ref_of(name: str) -> str:
        # 遗留块（hn_search_probe/login_demo_probe）的录制 ref 存在 state 遗留键下（c2/c1）
        return refs.get(name) or refs.get(legacy_keys.get(name, "")) or f"ref-{name}"

    trace_dirs: dict[str, Path] = {}
    py_dirs: dict[str, Path] = {}
    name_to_ref: dict[str, str] = {}
    for name in names:
        if kinds.get(name) == "trace":
            ref = _ref_of(name)
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
            from forge_trace.patchright_browser import PatchrightBrowser

            # 缺省浏览器工厂必须落到 PatchrightBrowser——传 None 会在链执行时
            # TypeError（NoneType 不可调用）；cert_batch.build_routes 同款兜底
            tr = TraceRunner(RecordingsStore(Path(store_dir)),
                             browser_factory or PatchrightBrowser,
                             block_dirs=trace_dirs,
                             scripts=load_trace_scripts(name_to_ref))
        for name, ref in name_to_ref.items():
            routes[name] = (tr, ref)
    if py_dirs:
        ar = AdapterRunner(py_dirs)
        for name in py_dirs:
            routes[name] = (ar, name)
    app.state.chain_runner = ChainRunner(routes).execute
    return routes

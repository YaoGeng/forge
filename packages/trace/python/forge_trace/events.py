"""事件流 → steps 聚合纯函数（docs/11 §3 C4）。

输入适配器产生的浏览器事件流，输出满足 proto 冻结约束的 Step 序列：
seq 从 1 连续递增、ts_offset 非递减、空串归一为 null。
聚合常量按 C4 钉死，均为模块级（不可配置绕过与测试可重入参数并存——
签名上的默认值仅服务测试，Recorder 生产路径使用默认）。
"""
from __future__ import annotations

from dataclasses import dataclass

from forge_proto.trace import Step

INPUT_FLUSH_MS = 800
SCROLL_FLUSH_MS = 800
IDLE_WAIT_MS = 2000

_Actions = ("click", "input", "scroll", "wait", "nav")


@dataclass(frozen=True)
class BrowserEvent:
    """适配器上报的原始事件；anchor 为该元素的 dom_anchor（selectors 锻造产物）。"""

    kind: str  # click | input | scroll | nav | keystroke | blur
    selector: str | None = None
    anchor: str | None = None
    value: str | None = None  # keystroke 文本块 / input 终值
    delta: int | None = None  # scroll 增量
    url: str | None = None  # nav 目标
    ts_ms: int = 0


@dataclass
class _Atom:
    action: str
    selector: str | None
    anchor: str | None
    value: str | None
    start_ts: int
    end_ts: int
    wait_condition: str | None = None


def aggregate(
    events, *, flush_ms: int = INPUT_FLUSH_MS, idle_ms: int = IDLE_WAIT_MS
) -> tuple[Step, ...]:
    events = list(events)
    if not events:
        return ()
    base_ts = events[0].ts_ms
    atoms: list[_Atom] = []
    pending_input: dict | None = None  # {selector, anchor, chars, start_ts, last_ts}
    open_scroll: dict | None = None  # {selector, anchor, delta, start_ts, last_ts}

    def flush_input() -> None:
        nonlocal pending_input
        if pending_input is None:
            return
        atoms.append(_Atom(
            action="input",
            selector=pending_input["selector"],
            anchor=pending_input["anchor"],
            value=pending_input["chars"],
            start_ts=pending_input["start_ts"],
            end_ts=pending_input["last_ts"],
        ))
        pending_input = None

    def close_scroll() -> None:
        nonlocal open_scroll
        if open_scroll is None:
            return
        atoms.append(_Atom(
            action="scroll",
            selector=open_scroll["selector"],
            anchor=open_scroll["anchor"],
            value=str(open_scroll["delta"]),
            start_ts=open_scroll["start_ts"],
            end_ts=open_scroll["last_ts"],
        ))
        open_scroll = None

    for ev in events:
        kind = ev.kind
        if kind == "blur":
            flush_input()
            continue
        if kind == "keystroke":
            if pending_input is not None and (
                ev.selector != pending_input["selector"]
                or ev.ts_ms - pending_input["last_ts"] > flush_ms
            ):
                flush_input()
            if pending_input is None:
                pending_input = {
                    "selector": _nz(ev.selector),
                    "anchor": _nz(ev.anchor),
                    "chars": ev.value or "",
                    "start_ts": ev.ts_ms,
                    "last_ts": ev.ts_ms,
                }
            else:
                pending_input["chars"] += ev.value or ""
                pending_input["last_ts"] = ev.ts_ms
            if (ev.value or "").endswith("\n"):
                flush_input()
            continue
        # click / input / scroll / nav：异元素操作先冲刷 input 缓冲
        if pending_input is not None and _nz(ev.selector) != pending_input["selector"]:
            flush_input()
        if kind == "input":
            flush_input()
            atoms.append(_Atom(
                action="input", selector=_nz(ev.selector), anchor=_nz(ev.anchor),
                value=ev.value, start_ts=ev.ts_ms, end_ts=ev.ts_ms,
            ))
        elif kind == "click":
            atoms.append(_Atom(
                action="click", selector=_nz(ev.selector), anchor=_nz(ev.anchor),
                value=None, start_ts=ev.ts_ms, end_ts=ev.ts_ms,
            ))
        elif kind == "scroll":
            if open_scroll is not None and ev.ts_ms - open_scroll["last_ts"] > flush_ms:
                close_scroll()
            if open_scroll is None:
                open_scroll = {
                    "selector": _nz(ev.selector), "anchor": _nz(ev.anchor),
                    "delta": int(ev.delta or 0), "start_ts": ev.ts_ms, "last_ts": ev.ts_ms,
                }
            else:
                open_scroll["delta"] += int(ev.delta or 0)
                open_scroll["last_ts"] = ev.ts_ms
        elif kind == "nav":
            close_scroll()
            atoms.append(_Atom(
                action="nav", selector=None, anchor=None,
                value=ev.url, start_ts=ev.ts_ms, end_ts=ev.ts_ms,
            ))
        else:
            raise ValueError(f"未知事件 kind: {kind!r}")
    flush_input()
    close_scroll()

    return _to_steps(atoms, base_ts, idle_ms)


def _to_steps(atoms: list[_Atom], base_ts: int, idle_ms: int) -> tuple[Step, ...]:
    spaced: list[_Atom] = []
    for i, atom in enumerate(atoms):
        if i > 0:
            prev = atoms[i - 1]
            if atom.start_ts - prev.end_ts >= idle_ms:
                anchor_target = prev.selector or atom.selector
                spaced.append(_Atom(
                    action="wait", selector=None, anchor=None, value=None,
                    start_ts=prev.end_ts, end_ts=prev.end_ts,
                    wait_condition=f"anchor:{anchor_target}" if anchor_target else None,
                ))
        spaced.append(atom)
    steps: list[Step] = []
    for seq, atom in enumerate(spaced, start=1):
        steps.append(Step(
            seq=seq,
            action=atom.action,
            target_selector=atom.selector,
            dom_anchor=atom.anchor,
            value=atom.value,
            wait_condition=atom.wait_condition,
            ts_offset=atom.start_ts - base_ts,
        ))
    return tuple(steps)


def _nz(value: str | None) -> str | None:
    return value if value else None

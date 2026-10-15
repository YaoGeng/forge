"""Replayer：确定性回放唯一入口 + 一致性比较器（docs/11 §3 C6/C9/C11）。

M07 §5：`replay.run(trace_ref, params, {mode})` 是确定性回放的唯一入口；
mode ∈ {local, golden, structured}——v1 实现 local/golden（T1.23），
structured 显式 NotImplementedError（M06 StructuredRunner 后续卡）。
一致性判据编码 M07 §8.3：字段逐等 → exact；声明时间敏感 → tolerant；
digest 不等且有快照 → 结构相似度通道；否则 mismatch。duration 永不进判据。
"""
from __future__ import annotations

import hashlib
import time
import typing as t
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from forge_proto.trace import Manifest, Step, load_manifest, load_steps

from .port import BrowserPort
from .similarity import SIMILARITY_THRESHOLD, structural_similarity
from .store import RecordingsStore

MODES = ("local", "golden", "structured")
# 回放锚定等待超时（v1 常量；FakeBrowser 即时返回，真实适配器消费）
WAIT_TIMEOUT_MS = 5000
_ANCHOR_PREFIX = "anchor:"


class StepResult(t.TypedDict):
    seq: int
    action: str
    ok: bool
    anchor_matched: bool
    snapshot_digest: str
    duration_ms: int


@dataclass(frozen=True)
class ReplayResult:
    trace_ref: str
    mode: str
    step_results: tuple[StepResult, ...]


@dataclass(frozen=True)
class ConsistencyReport:
    kind: str  # exact | tolerant | similarity | mismatch
    diff: tuple[dict, ...]


def _digest(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8")).hexdigest()[:16]


def _override_query(url: str, overrides: dict[str, str]) -> str:
    """C9：q:<name> 覆盖 nav URL 的同名 query 值（仅替换既有键，不新增）。"""
    if not overrides:
        return url
    parts = urlsplit(url)
    rebuilt: list[tuple[str, str]] = []
    changed = False
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k in overrides:
            rebuilt.append((k, overrides[k]))
            changed = True
        else:
            rebuilt.append((k, v))
    if not changed:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(rebuilt), parts.fragment))


def _execute(port: BrowserPort, step: Step, params: dict[str, str]) -> tuple[bool, bool]:
    """执行单步 → (ok, anchor_matched)。目标元素缺失时不执行动作（fail-fast）。"""
    if step.action == "wait":
        anchor = step.wait_condition or ""
        if anchor.startswith(_ANCHOR_PREFIX):
            matched = port.wait_selector(anchor[len(_ANCHOR_PREFIX):], WAIT_TIMEOUT_MS)
            return matched, matched
        return True, True
    if step.target_selector and not port.wait_selector(step.target_selector, WAIT_TIMEOUT_MS):
        return False, False
    if step.action == "nav":
        url = step.value or ""
        query_overrides = {
            k[2:]: v for k, v in params.items() if k.startswith("q:") and len(k) > 2
        }
        port.goto(_override_query(url, query_overrides))
        return True, True
    if step.action == "click":
        port.click(step.target_selector or "")
        return True, True
    if step.action == "input":
        value = params.get(str(step.seq), step.value or "")
        port.fill(step.target_selector or "", value)
        return True, True
    if step.action == "scroll":
        try:
            delta = int(step.value or "0")
        except ValueError:
            delta = 0
        port.scroll_by(delta)
        return True, True
    raise ValueError(f"未知 action: {step.action!r}")


def run(
    trace_ref: str,
    params: dict[str, str] | None = None,
    mode: str = "local",
    *,
    store: RecordingsStore,
    browser_factory,
) -> ReplayResult:
    if mode not in MODES:
        raise ValueError(f"mode 必须属于 {MODES}，得到 {mode!r}")
    if mode == "structured":
        raise NotImplementedError("mode=structured 归 M06 StructuredRunner（后续卡）")
    params = dict(params or {})
    rec = store.get(trace_ref)
    manifest = load_manifest(rec.trace_dir / "manifest.yaml")
    steps = load_steps(rec.trace_dir / "steps.ndjson")
    port = browser_factory()
    if mode == "golden":
        from .golden import apply_routes  # 延迟导入避免 T1.22 未建模块时的循环

        apply_routes(port, rec.trace_dir.parent.parent, trace_ref)
    results: list[StepResult] = []
    for step in steps:
        t0 = time.perf_counter()
        try:
            ok, anchor_matched = _execute(port, step, params)
        except Exception:
            ok, anchor_matched = False, False
        duration_ms = int((time.perf_counter() - t0) * 1000)
        results.append(StepResult(
            seq=step.seq,
            action=step.action,
            ok=ok,
            anchor_matched=anchor_matched,
            snapshot_digest=_digest(port.snapshot_html()),
            duration_ms=duration_ms,
        ))
    if mode == "local":
        fragile = [r["seq"] for r in results if not r["anchor_matched"]]
        if fragile:
            store.mark_fragile(trace_ref, fragile)
    return ReplayResult(trace_ref=trace_ref, mode=mode, step_results=tuple(results))


def assert_consistent(
    runs: t.Sequence[ReplayResult],
    manifest: Manifest,
    htmls: dict[int, tuple[str, ...]] | None = None,
) -> ConsistencyReport:
    """M07 §8.3 一致判据：基准=首跑，逐 seq 比对（duration 永不进判据）。"""
    if len(runs) < 2:
        raise ValueError("assert_consistent 需要至少两次回放结果")
    base = runs[0]
    declared = {t.seq for t in manifest.time_sensitive_steps}
    htmls = htmls or {}
    diff: list[dict] = []
    for i, base_step in enumerate(base.step_results):
        kind = "exact"
        for other in runs[1:]:
            other_step = other.step_results[i]
            detail = _first_diff(base_step, other_step)
            if detail is None:
                continue
            if base_step["seq"] in declared:
                kind = max(kind, "tolerant", key=_kind_rank)
                diff.append({"seq": base_step["seq"], "kind": "tolerant",
                             "detail": f"时间敏感步容差: {detail}"})
                continue
            pair = htmls.get(base_step["seq"])
            if (
                detail.startswith("snapshot_digest")
                and pair is not None
                and len(pair) >= 2
                and structural_similarity(pair[0], pair[1]) >= SIMILARITY_THRESHOLD
            ):
                kind = max(kind, "similarity", key=_kind_rank)
                diff.append({"seq": base_step["seq"], "kind": "similarity",
                             "detail": f"结构相似（digest 异）: {detail}"})
                continue
            kind = "mismatch"
            diff.append({"seq": base_step["seq"], "kind": "mismatch", "detail": detail})
    overall = "exact"
    for d in diff:
        overall = max(overall, d["kind"], key=_kind_rank)
    return ConsistencyReport(kind=overall, diff=tuple(diff))


_KIND_RANK = {"exact": 0, "tolerant": 1, "similarity": 2, "mismatch": 3}


def _kind_rank(kind: str) -> int:
    return _KIND_RANK[kind]
_COMPARE_FIELDS = ("action", "ok", "anchor_matched", "snapshot_digest")


def _first_diff(a: StepResult, b: StepResult) -> str | None:
    for field in _COMPARE_FIELDS:
        if a[field] != b[field]:
            return f"{field}: {a[field]!r} != {b[field]!r}"
    return None


class _ReplayFacade:
    """M07 §5 消费面：replay.run(trace_ref, params, {mode})。"""

    def run(self, *args, **kwargs) -> ReplayResult:
        return run(*args, **kwargs)


replay = _ReplayFacade()

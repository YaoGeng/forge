"""Replayer：确定性回放唯一入口 + 一致性比较器（docs/11 §3 C6/C9/C11）。

M07 §5：`replay.run(trace_ref, params, {mode})` 是确定性回放的唯一入口；
mode ∈ {local, golden, structured}——v1 实现 local/golden（T1.23），
structured 显式 NotImplementedError（M06 StructuredRunner 后续卡）。
一致性判据编码 M07 §8.3：字段逐等 → exact；声明时间敏感 → tolerant；
digest 不等且有快照 → 结构相似度通道；否则 mismatch。duration 永不进判据。
"""
from __future__ import annotations

import hashlib
import logging
import time
import typing as t
from dataclasses import dataclass
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit

from forge_proto.trace import Manifest, Step, load_manifest, load_steps

from .port import BrowserPort
from .similarity import SIMILARITY_THRESHOLD, structural_similarity
from .store import RecordingsStore

_LOG = logging.getLogger(__name__)

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
    """C9：q:<name> 覆盖 nav URL 的同名 query 值（仅替换既有键，不新增）。

    未命中的键值对按原文保留（不做整体重编码，避免改动录制字面量的编码形态）。
    """
    if not overrides:
        return url
    parts = urlsplit(url)
    if not parts.query:
        return url
    out: list[str] = []
    changed = False
    for pair in parts.query.split("&"):
        key_raw, _, value_raw = pair.partition("=")
        if unquote_plus(key_raw) in overrides:
            out.append(f"{key_raw}={quote(overrides[unquote_plus(key_raw)], safe='')}")
            changed = True
        else:
            out.append(pair)
    if not changed:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(out), parts.fragment))


def _execute(port: BrowserPort, step: Step, params: dict[str, str]) -> tuple[bool, bool, str | None]:
    """执行单步 → (ok, anchor_matched, error)。

    目标元素缺失时不执行动作（fail-fast，anchor_matched=False）；
    动作执行异常与 anchor 缺失分列——异常时 anchor 保持等待结果，
    不写入 fragile（重录提示只对真实脆弱步骤，评审 Important-2）。
    """
    if step.action == "wait":
        anchor = step.wait_condition or ""
        if anchor.startswith(_ANCHOR_PREFIX):
            matched = port.wait_selector(anchor[len(_ANCHOR_PREFIX):], WAIT_TIMEOUT_MS)
            return matched, matched, None
        return True, True, None
    anchor_matched = True
    if step.target_selector:
        anchor_matched = port.wait_selector(step.target_selector, WAIT_TIMEOUT_MS)
        if not anchor_matched:
            return False, False, None
    try:
        if step.action == "nav":
            url = step.value or ""
            query_overrides = {
                k[2:]: v for k, v in params.items() if k.startswith("q:") and len(k) > 2
            }
            port.goto(_override_query(url, query_overrides))
        elif step.action == "click":
            port.click(step.target_selector or "")
        elif step.action == "input":
            value = params.get(str(step.seq), step.value or "")
            port.fill(step.target_selector or "", value)
        elif step.action == "scroll":
            port.scroll_by(int(step.value or "0"))
        else:
            raise ValueError(f"未知 action: {step.action!r}")
    except Exception as exc:
        return False, anchor_matched, f"{type(exc).__name__}: {exc}"
    return True, anchor_matched, None


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
        from .golden import apply_routes

        apply_routes(port, rec.trace_dir.parent.parent, trace_ref)
    results: list[StepResult] = []
    for step in steps:
        t0 = time.perf_counter()
        try:
            ok, anchor_matched, error = _execute(port, step, params)
        except Exception as exc:  # 端口实现缺陷兜底：不误标 fragile，保留诊断
            ok, anchor_matched, error = False, True, f"{type(exc).__name__}: {exc}"
        if error:
            _LOG.warning("回放步执行失败 trace=%s seq=%s: %s", trace_ref, step.seq, error)
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
    """M07 §8.3 一致判据：基准=首跑，逐 seq 比对（duration 永不进判据）。

    前置校验：同 trace_ref（不同轨迹是调用方错误）；步数不齐产出 mismatch
    而非越界（评审 Important-1）。
    """
    if len(runs) < 2:
        raise ValueError("assert_consistent 需要至少两次回放结果")
    refs = {r.trace_ref for r in runs}
    if len(refs) > 1:
        raise ValueError(f"assert_consistent 仅比对同一 trace_ref，得到 {sorted(refs)}")
    base = runs[0]
    for other in runs[1:]:
        if len(other.step_results) != len(base.step_results):
            return ConsistencyReport(
                kind="mismatch",
                diff=({
                    "seq": 0,
                    "kind": "mismatch",
                    "detail": f"步数不一致: {len(base.step_results)} != {len(other.step_results)}",
                },),
            )
    declared = {t.seq for t in manifest.time_sensitive_steps}
    htmls = htmls or {}
    diff: list[dict] = []
    for i, base_step in enumerate(base.step_results):
        for ri, other in enumerate(runs[1:], start=1):
            other_step = other.step_results[i]
            detail = _first_diff(base_step, other_step)
            if detail is None:
                continue
            if base_step["seq"] in declared:
                diff.append({"seq": base_step["seq"], "kind": "tolerant",
                             "detail": f"时间敏感步容差: {detail}"})
                continue
            pair = htmls.get(base_step["seq"])
            if (
                detail.startswith("snapshot_digest")
                and pair is not None
                and len(pair) > ri
                and structural_similarity(pair[0], pair[ri]) >= SIMILARITY_THRESHOLD
            ):
                diff.append({"seq": base_step["seq"], "kind": "similarity",
                             "detail": f"结构相似（digest 异）: {detail}"})
                continue
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

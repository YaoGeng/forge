"""批次礼仪：模块级常量 + enforce 纯函数（M09 不变量 2 / G10：不可配置绕过）。

常量只有本模块这一处定义，无 setter、无环境变量、无配置文件入口；
消费方（scheduler/app）以导入期值绑定使用——运行期重绑模块属性不改变行为。
"""
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Protocol

# C3 六常量（钉死）
MAX_VISITS_PER_SITE_PER_BATCH = 20  # ≤20 次真实访问/站点/批次
SEGMENTS = 2  # N=20 = 2 时段 × 10 次
SEGMENT_RUNS = 10
MIN_BATCH_SPAN_H = 48  # 跨 ≥48h
MIN_REQUEST_INTERVAL_S = 5  # 同站点相邻请求限频
EPHEMERAL_SESSION_PER_RUN = True  # 单会话：每 run 独立一次性浏览器会话

# verdict 阈值按站点等级（PRD §9.3 逐字：标准 ≥90% / 中等变更 ≥85% / 高变更·受防护不设下限）
THRESHOLD_BY_TIER = MappingProxyType({"standard": 0.90, "medium": 0.85, "high": None})


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class PlannedRequest:
    """批次内一次计划请求；index 为批次内全局序号，requests 按 ts 升序。"""

    ts: datetime
    segment: int
    index: int


@dataclass(frozen=True)
class BatchPlan:
    batch_id: str
    site: str  # 同站点限频/上限的归组键
    requests: tuple[PlannedRequest, ...]
    segment_starts: tuple[datetime, ...]  # 每时段最早开始时刻


@dataclass(frozen=True)
class AuditEntry:
    ts: datetime
    batch_id: str
    kind: str  # accept / reject
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EtiquetteDecision:
    allowed: bool
    reasons: tuple[str, ...]
    audit_entry: AuditEntry


def enforce(
    plan: BatchPlan,
    *,
    clock: Clock,
    _cap: int = MAX_VISITS_PER_SITE_PER_BATCH,
    _segments: int = SEGMENTS,
    _runs: int = SEGMENT_RUNS,
    _span_h: int = MIN_BATCH_SPAN_H,
    _interval_s: int = MIN_REQUEST_INTERVAL_S,
) -> EtiquetteDecision:
    """计划级礼仪校验（纯函数）：上限/时段结构/限频/跨度。默认参数即导入期值绑定。"""
    reasons: list[str] = []
    requests = sorted(plan.requests, key=lambda r: r.ts)

    if len(requests) > _cap:
        reasons.append(f"visit cap exceeded: {len(requests)} > {_cap}")

    by_segment: dict[int, int] = {}
    for r in requests:
        by_segment[r.segment] = by_segment.get(r.segment, 0) + 1
    for seg, count in sorted(by_segment.items()):
        if count > _runs:
            reasons.append(f"segment {seg} runs {count} > {_runs}")
    if len(plan.segment_starts) > _segments:
        reasons.append(f"segments {len(plan.segment_starts)} > {_segments}")

    for a, b in zip(requests, requests[1:]):
        if (b.ts - a.ts).total_seconds() < _interval_s:
            reasons.append(
                f"request interval {(b.ts - a.ts).total_seconds()}s < {_interval_s}s at index {b.index}"
            )

    if len(plan.segment_starts) >= 2:
        span_h = (plan.segment_starts[-1] - plan.segment_starts[0]).total_seconds() / 3600
        if span_h < _span_h:
            reasons.append(f"batch span {span_h}h < {_span_h}h")

    kind = "accept" if not reasons else "reject"
    entry = AuditEntry(ts=clock.now(), batch_id=plan.batch_id, kind=kind, reasons=tuple(reasons))
    return EtiquetteDecision(allowed=not reasons, reasons=tuple(reasons), audit_entry=entry)

"""CertScheduler：提交排期 + tick 到点执行（M09 §3.1）。

礼仪强制走 etiquette.enforce（计划入口唯一通道）；执行节奏 = 每 tick 至多一 run，
且与上一 run 间隔 ≥ MIN_REQUEST_INTERVAL_S——限频在调度器层成立，不依赖调用方自律。
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from .etiquette import (
    MIN_BATCH_SPAN_H,
    MIN_REQUEST_INTERVAL_S,
    SEGMENTS,
    SEGMENT_RUNS,
    THRESHOLD_BY_TIER,
    AuditEntry,
    BatchPlan,
    Clock,
    EtiquetteDecision,
    PlannedRequest,
    enforce,
)
from .models import CertificationRun


@dataclass(frozen=True)
class SegmentRunOutcome:
    """一次真实运行的结果（执行器适配层；T1.31 C2Executor 桥接 RunnerPort）。"""

    live_ok: bool
    regression_ok: bool
    failure_class: str | None = None
    partial_flags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RunExecution:
    run_id: int
    segment: int
    index: int
    ts: datetime
    outcome: SegmentRunOutcome


@dataclass(frozen=True)
class AdvanceReport:
    executed: tuple[RunExecution, ...]
    completed: tuple[int, ...]  # 本次 tick 内跑满 N、verdict 落档的 certification run


SegRunHook = Callable[[int, int, int], SegmentRunOutcome]


def compute_verdict(
    tier: str,
    live_pass_rate: float,
    regression_pass_rate: float,
    partial_flags: frozenset[str] | set[str],
    *,
    _thresholds=THRESHOLD_BY_TIER,
) -> str:
    """C5：verdict 只由 live 口径决定；regression_pass_rate 入参仅为契约显式，不参与判定（G6 分列）。"""
    if "preflight_rejected" in partial_flags or "report_invalid" in partial_flags:
        return "rejected"
    if partial_flags:
        return "partial"
    threshold = _thresholds.get(tier)
    if threshold is None:  # 高变更/受防护：不设下限，best-effort 标注由 best_effort() 派生
        return "pass"
    return "pass" if live_pass_rate >= threshold else "below_threshold"


def best_effort(tier: str, *, _thresholds=THRESHOLD_BY_TIER) -> bool:
    return _thresholds.get(tier) is None


def WallClock() -> Clock:
    """生产时钟：naive UTC（与测试 FrozenClock 同口径）。"""

    class _Wall:
        def now(self) -> datetime:
            return datetime.now(timezone.utc).replace(tzinfo=None)

    return _Wall()


class CertScheduler:
    def __init__(
        self,
        session_factory,
        *,
        clock: Clock,
        executor_hook: SegRunHook | None = None,
    ):
        self.session_factory = session_factory
        self.clock = clock
        self.executor_hook = executor_hook
        self.audit: list[AuditEntry] = []
        self._plans: dict[int, BatchPlan] = {}
        self._tiers: dict[int, str] = {}
        self._pending: dict[int, set[int]] = {}
        self._partials: dict[int, set[str]] = {}
        self._live_fail_rows: dict[int, list[dict]] = {}
        self._reg_ok: dict[int, int] = {}
        self._last_exec: dict[int, datetime] = {}

    # --- 排期入口 ---------------------------------------------------------------

    def submit(
        self, subject_type: str, subject_id: str, version: str, level: str, *, site_tier: str = "standard"
    ) -> int:
        now = self.clock.now()
        batch_id = uuid.uuid4().hex
        seg1_start = now + timedelta(hours=MIN_BATCH_SPAN_H)
        requests = []
        for seg_start, seg in ((now, 0), (seg1_start, 1)):
            for i in range(SEGMENT_RUNS):
                requests.append(
                    PlannedRequest(
                        ts=seg_start + timedelta(seconds=i * MIN_REQUEST_INTERVAL_S),
                        segment=seg,
                        index=seg * SEGMENT_RUNS + i,
                    )
                )
        plan = BatchPlan(
            batch_id=batch_id,
            site=f"{subject_type}:{subject_id}",
            requests=tuple(requests),
            segment_starts=(now, seg1_start),
        )
        decision = self.submit_plan(plan)
        if not decision.allowed:  # 构造即合规，防御性断言
            raise RuntimeError(f"compliant plan rejected: {decision.reasons}")

        with self.session_factory() as s:
            row = CertificationRun(
                subject_type=subject_type,
                subject_id=subject_id,
                version=version,
                level=level,
                batch_id=batch_id,
            )
            s.add(row)
            s.commit()
            run_id = row.id
        self._plans[run_id] = plan
        self._tiers[run_id] = site_tier
        self._pending[run_id] = set(range(len(requests)))
        return run_id

    def submit_plan(self, plan: BatchPlan) -> EtiquetteDecision:
        """外部计划唯一入册通道：强制礼仪 + 留审计行；拒绝则不排期不落库。"""
        decision = enforce(plan, clock=self.clock)
        self.audit.append(decision.audit_entry)
        return decision

    # --- 执行推进 ---------------------------------------------------------------

    def tick(self) -> AdvanceReport:
        now = self.clock.now()
        executed: list[RunExecution] = []
        completed: list[int] = []
        if self.executor_hook is not None:
            for run_id, plan in self._plans.items():
                pending = self._pending.get(run_id, set())
                if not pending:
                    continue
                nxt = min(pending, key=lambda i: plan.requests[i].ts)
                req = plan.requests[nxt]
                if req.ts > now:
                    continue
                last = self._last_exec.get(run_id)
                if last is not None and (now - last).total_seconds() < MIN_REQUEST_INTERVAL_S:
                    continue  # 限频：同站点相邻 run 不足间隔，等下一 tick
                outcome = self.executor_hook(run_id, req.segment, req.index)
                self._apply(run_id, plan, nxt, outcome, now)
                self._last_exec[run_id] = now
                executed.append(RunExecution(run_id, req.segment, req.index, ts=now, outcome=outcome))
                if not self._pending[run_id]:
                    completed.append(run_id)
        return AdvanceReport(executed=tuple(executed), completed=tuple(completed))

    def next_due(self) -> datetime | None:
        due = []
        for run_id, pending in self._pending.items():
            if pending:
                plan = self._plans[run_id]
                due.append(min(plan.requests[i].ts for i in pending))
        return min(due) if due else None

    # --- 查询面 -----------------------------------------------------------------

    def plan_for(self, run_id: int) -> BatchPlan | None:
        return self._plans.get(run_id)

    def status_of(self, run_id: int) -> str:
        with self.session_factory() as s:
            row = s.get(CertificationRun, run_id)
            if row is None:
                raise KeyError(run_id)
            if row.verdict is not None:
                return "done"
            return "in_progress" if row.n > 0 else "scheduled"

    def tier_of(self, run_id: int) -> str:
        return self._tiers.get(run_id, "standard")

    def segments_view(self, run_id: int) -> list[dict]:
        plan = self._plans.get(run_id)
        if plan is None:
            return []
        pending = self._pending.get(run_id, set())
        view = []
        for seg, start in enumerate(plan.segment_starts):
            planned = [r for r in plan.requests if r.segment == seg]
            view.append(
                {
                    "segment": seg,
                    "earliest_start": start.isoformat(),
                    "runs_planned": len(planned),
                    "runs_done": sum(1 for r in planned if r.index not in pending),
                }
            )
        return view

    # --- 内部 -------------------------------------------------------------------

    def _apply(self, run_id: int, plan: BatchPlan, index: int, outcome: SegmentRunOutcome, now: datetime) -> None:
        self._pending[run_id].discard(index)
        self._partials.setdefault(run_id, set()).update(outcome.partial_flags)
        if not outcome.live_ok:
            self._live_fail_rows.setdefault(run_id, []).append(
                {"index": index, "segment": plan.requests[index].segment, "failure_class": outcome.failure_class}
            )
        if outcome.regression_ok:
            self._reg_ok[run_id] = self._reg_ok.get(run_id, 0) + 1
        with self.session_factory() as s:
            row = s.get(CertificationRun, run_id)
            row.n += 1
            row.pass_count += 1 if outcome.live_ok else 0
            row.live_pass_rate = row.pass_count / row.n
            row.regression_pass_rate = self._reg_ok.get(run_id, 0) / row.n
            if row.started_at is None:
                row.started_at = now
            row.fail_json = {"failures": self._live_fail_rows.get(run_id, [])}
            if row.n >= len(plan.requests):
                row.verdict = compute_verdict(
                    self.tier_of(run_id),
                    row.live_pass_rate,
                    row.regression_pass_rate,
                    frozenset(self._partials.get(run_id, set())),
                )
                row.finished_at = now
            s.commit()

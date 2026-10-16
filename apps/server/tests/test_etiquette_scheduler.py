"""T1.30 用例矩阵：certification_runs 落库 + CertScheduler 批次礼仪强制（M09 §3.1/§4/§8.4/§8.5；C1/C3/C5/C6）。"""
import inspect
import json
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import forge_server.etiquette as etiquette
import forge_server.scheduler as scheduler_mod
import forge_server.app as app_mod
import forge_server.models as models_mod
from forge_server.etiquette import (
    MAX_VISITS_PER_SITE_PER_BATCH,
    MIN_BATCH_SPAN_H,
    MIN_REQUEST_INTERVAL_S,
    SEGMENTS,
    SEGMENT_RUNS,
    BatchPlan,
    PlannedRequest,
    enforce,
)
from forge_server.models import CertificationRun
from forge_server.scheduler import SegmentRunOutcome, best_effort, compute_verdict

START = datetime(2026, 10, 16, 9, 0, 0)  # 与 conftest.FrozenClock 默认起点一致（naive UTC）


def make_all_ok_hook(live_fails=(), failure_class="anchor_mismatch"):
    def hook(run_id, segment, index):
        ok = index not in live_fails
        return SegmentRunOutcome(
            live_ok=ok,
            regression_ok=True,
            failure_class=None if ok else failure_class,
        )

    return hook


def plan_of_n(requests_n, *, batch_id="b1", site="example.com", interval_s=None):
    """构造 n 个同站点请求的计划；interval_s 覆盖默认礼仪间隔。"""
    step = interval_s if interval_s is not None else MIN_REQUEST_INTERVAL_S
    seg0 = START + timedelta(days=365)  # 远离默认 submit 时刻，避免语义混淆
    requests = tuple(
        PlannedRequest(ts=seg0 + timedelta(seconds=i * step), segment=i // SEGMENT_RUNS, index=i)
        for i in range(requests_n)
    )
    starts = [seg0]
    for i in range(1, SEGMENTS):
        starts.append(seg0 + timedelta(hours=MIN_BATCH_SPAN_H * i))
    return BatchPlan(batch_id=batch_id, site=site, requests=requests, segment_starts=tuple(starts))


# --- 排期与礼仪 -------------------------------------------------------------------


def test_submit_creates_two_segments(make_scheduler, get_row):
    sched = make_scheduler()
    run_id = sched.submit("block", "baidu_search", "1.0.0", "C2")

    plan = sched.plan_for(run_id)
    assert plan is not None
    assert len(plan.requests) == SEGMENTS * SEGMENT_RUNS == 20
    seg0 = [r for r in plan.requests if r.segment == 0]
    seg1 = [r for r in plan.requests if r.segment == 1]
    assert len(seg0) == SEGMENT_RUNS and len(seg1) == SEGMENT_RUNS
    assert plan.batch_id, "batch_id 非空"

    row = get_row(sched, run_id)
    assert row.batch_id == plan.batch_id
    assert sched.status_of(run_id) == "scheduled"


def test_etiquette_caps_visits(make_scheduler, clock):
    # 纯函数层：同站点第 21 次请求 → 拒绝 + 审计行
    decision = enforce(plan_of_n(MAX_VISITS_PER_SITE_PER_BATCH + 1), clock=clock)
    assert not decision.allowed
    assert any(str(MAX_VISITS_PER_SITE_PER_BATCH) in r for r in decision.reasons)
    assert decision.audit_entry.kind == "reject"
    assert decision.audit_entry.batch_id == "b1"

    # 调度器层：外部计划入口同样强制，拒绝入册且留审计行、不落库
    sched = make_scheduler()
    d2 = sched.submit_plan(plan_of_n(MAX_VISITS_PER_SITE_PER_BATCH + 1, batch_id="b2"))
    assert not d2.allowed
    assert any(e.kind == "reject" and e.batch_id == "b2" for e in sched.audit)
    with sched.session_factory() as s:
        assert s.query(CertificationRun).count() == 0

    # 合规 20 次计划放行
    d3 = sched.submit_plan(plan_of_n(MAX_VISITS_PER_SITE_PER_BATCH, batch_id="b3"))
    assert d3.allowed


def test_etiquette_span_enforced(make_scheduler, clock, get_row, drain):
    sched = make_scheduler(hook=make_all_ok_hook())
    run_id = sched.submit("block", "probe", "1.0.0", "C2")

    drain(sched, clock, until=START + timedelta(hours=MIN_BATCH_SPAN_H - 1))
    assert get_row(sched, run_id).n == SEGMENT_RUNS  # 时段一完成

    # 计划层：47h 间隔的两时段计划被 enforce 拒绝
    early = BatchPlan(
        batch_id="early",
        site="s",
        requests=plan_of_n(20).requests,
        segment_starts=(START, START + timedelta(hours=MIN_BATCH_SPAN_H - 1)),
    )
    assert not enforce(early, clock=clock).allowed

    clock.advance_to(START + timedelta(hours=MIN_BATCH_SPAN_H - 1))  # t0+47h
    report = sched.tick()
    assert len(report.executed) == 0  # 拒绝推进
    assert sched.next_due() == START + timedelta(hours=MIN_BATCH_SPAN_H)

    clock.advance_to(START + timedelta(hours=MIN_BATCH_SPAN_H))  # t0+48h
    report = sched.tick()
    assert len(report.executed) == 1  # ≥48h 放行


def test_rate_limit_interval(make_scheduler, clock):
    sched = make_scheduler(hook=make_all_ok_hook())
    run_id = sched.submit("block", "probe", "1.0.0", "C2")

    plan = sched.plan_for(run_id)
    spacings = [
        (b.ts - a.ts).total_seconds()
        for a, b in zip(plan.requests, plan.requests[1:])
        if a.segment == b.segment
    ]
    assert all(s >= MIN_REQUEST_INTERVAL_S for s in spacings)  # 计划层断言，不真睡

    r0 = sched.tick()
    assert len(r0.executed) == 1
    clock.advance(seconds=4)
    assert len(sched.tick().executed) == 0  # 4s < 5s：第二次不执行
    clock.advance(seconds=1)
    r2 = sched.tick()
    assert len(r2.executed) == 1
    gap = r2.executed[0].ts - r0.executed[0].ts
    assert gap.total_seconds() >= MIN_REQUEST_INTERVAL_S


def test_etiquette_no_bypass_surface(monkeypatch, make_scheduler, clock):
    # 反射：无 setter/配置入口
    banned = [
        n
        for n in dir(etiquette)
        if n.lower().startswith(("set_", "configure", "override", "update_", "register_"))
    ]
    assert banned == []
    # 源码：不读环境变量
    for mod in (etiquette, scheduler_mod):
        src = inspect.getsource(mod)
        assert "environ" not in src and "getenv" not in src

    # env 覆盖尝试不改变行为
    monkeypatch.setenv("MAX_VISITS_PER_SITE_PER_BATCH", "100")
    monkeypatch.setenv("FORGE_ETIQUETTE_MAX_VISITS", "100")
    decision = enforce(plan_of_n(MAX_VISITS_PER_SITE_PER_BATCH + 1), clock=clock)
    assert not decision.allowed

    # 映射本体不可变写
    with pytest.raises(TypeError):
        etiquette.THRESHOLD_BY_TIER["standard"] = 0.0

    # 常量重绑尝试不改变行为（调度器/纯函数以导入期值绑定消费）
    etiquette.MAX_VISITS_PER_SITE_PER_BATCH = 100
    etiquette.SEGMENT_RUNS = 99
    etiquette.THRESHOLD_BY_TIER = {"standard": 0.0}
    assert enforce(plan_of_n(MAX_VISITS_PER_SITE_PER_BATCH + 1), clock=clock).allowed is False
    assert compute_verdict("standard", 0.5, 0.0, frozenset()) == "below_threshold"
    # 调度器仍以 20 为上限
    sched = make_scheduler()
    assert not sched.submit_plan(plan_of_n(21, batch_id="b4")).allowed


# --- verdict 与分列 ----------------------------------------------------------------


def test_verdict_by_tier():
    assert compute_verdict("standard", 0.90, 1.0, frozenset()) == "pass"
    assert compute_verdict("medium", 0.85, 0.9, frozenset()) == "pass"
    assert compute_verdict("high", 0.5, 0.5, frozenset()) == "pass"  # 不设下限
    assert best_effort("high") is True
    assert best_effort("standard") is False

    assert compute_verdict("standard", 0.89, 1.0, frozenset()) == "below_threshold"
    assert compute_verdict("standard", 0.95, 1.0, frozenset({"undeclared_confirm"})) == "partial"
    assert compute_verdict("standard", 1.0, 1.0, frozenset({"report_invalid"})) == "rejected"

    # regression 口径不影响 verdict（G6：verdict 只由 live 决定）
    assert compute_verdict("standard", 0.89, 0.0, frozenset()) == "below_threshold"


def test_storage_never_conflates(make_app, clock, drain):
    hook = make_all_ok_hook(live_fails=(18, 19))
    app = make_app(hook=hook)
    sched = app.state.scheduler
    run_id = sched.submit("block", "probe", "1.0.0", "C2")
    drain(sched, clock)

    data = TestClient(app).get(f"/api/v1/certifications/{run_id}").json()

    assert data["n"] == 20
    assert data["pass"] == 18
    assert data["live_pass_rate"] == 0.9
    assert data["regression_pass_rate"] == 1.0
    flat = json.dumps(data)
    assert "combined" not in flat and "overall" not in flat and "total_pass_rate" not in flat
    assert len(data["fail_json"]["failures"]) == 2
    # 模块层不存在任何「合计」辅助出口
    for mod in (scheduler_mod, app_mod, models_mod):
        for name in dir(mod):
            assert not re.search(r"combin|overall|total_pass|merged|union_pass", name, re.I), name


def test_rate_fields_carry_n_and_window(make_app, clock, drain):
    app = make_app(hook=make_all_ok_hook())
    sched = app.state.scheduler
    run_id = sched.submit("block", "probe", "1.0.0", "C2")
    drain(sched, clock)

    data = TestClient(app).get(f"/api/v1/certifications/{run_id}").json()

    assert data["n"] == 20
    assert data["started_at"] == START.isoformat()
    assert data["finished_at"] == (
        START + timedelta(hours=MIN_BATCH_SPAN_H) + timedelta(seconds=(SEGMENT_RUNS - 1) * MIN_REQUEST_INTERVAL_S)
    ).isoformat()


def test_submit_api_roundtrip(api):
    resp = api.client.post(
        "/api/v1/certifications",
        json={"subject_type": "block", "subject_id": "probe", "version": "1.0.0", "level": "C2"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    sched = api.app.state.scheduler
    assert sched.plan_for(run_id) is not None

    data = api.client.get(f"/api/v1/certifications/{run_id}").json()
    for key in (
        "id",
        "subject_type",
        "subject_id",
        "version",
        "level",
        "n",
        "pass",
        "live_pass_rate",
        "regression_pass_rate",
        "verdict",
        "batch_id",
        "best_effort",
        "status",
    ):
        assert key in data, key
    assert data["live_pass_rate"] is None and data["regression_pass_rate"] is None
    assert api.client.get("/api/v1/certifications/99999").status_code == 404


def test_tick_executes_segments(make_scheduler, clock, get_row, drain):
    calls = []

    def hook(run_id, segment, index):
        calls.append((segment, index))
        return SegmentRunOutcome(live_ok=True, regression_ok=True)

    sched = make_scheduler(hook=hook)
    run_id = sched.submit("block", "probe", "1.0.0", "C2")
    drain(sched, clock)

    assert len(calls) == 20
    row = get_row(sched, run_id)
    assert row.n == 20
    assert row.pass_count == 20
    assert row.live_pass_rate == 1.0 and row.regression_pass_rate == 1.0
    assert row.verdict == "pass"
    assert sched.status_of(run_id) == "done"


# --- T1.62 补：计划跨进程持久化与重建（MS-1E seg2 换进程驱动的前置修复）---


def test_reattach_restores_plan_across_instances(make_scheduler, clock, drain, get_row):
    """新进程（内存计划为空）reattach 后可续跑到 N=20 且口径不漂移。"""
    sched_a = make_scheduler(make_all_ok_hook())
    run_id = sched_a.submit("block", "reblock", "1.0.0", "C2", site_tier="standard")
    drain(sched_a, clock, until=START + timedelta(seconds=60))
    assert get_row(sched_a, run_id).n == 10  # 时段一完成

    sched_b = make_scheduler(make_all_ok_hook())  # 模拟旧进程死亡后的新进程
    assert sched_b.plan_for(run_id) is None
    assert sched_b.reattach(run_id) is True
    assert sched_b.plan_for(run_id) is not None

    clock.advance_to(START + timedelta(hours=48) - timedelta(seconds=1))  # 停在时段二开始前 1s：drain 需单调时钟
    drain(sched_b, clock)
    row = get_row(sched_b, run_id)
    assert row.n == 20 and row.verdict == "pass"
    assert row.live_pass_rate == 1.0 and row.regression_pass_rate == 1.0


def test_reattach_legacy_row_without_plan_json(make_scheduler, clock, drain, get_row):
    """旧版本行（无 plan_json，n=10）：按 started_at+n 确定性重建第二时段。"""
    sched = make_scheduler(make_all_ok_hook())
    run_id = sched.submit("block", "legacyblock", "1.0.0", "C2", site_tier="standard")
    drain(sched, clock, until=START + timedelta(seconds=60))
    with sched.session_factory() as s:
        row = s.get(CertificationRun, run_id)
        row.plan_json = None  # 模拟 T1.30 旧版本写入的行
        s.commit()

    sched2 = make_scheduler(make_all_ok_hook())
    assert sched2.reattach(run_id) is True
    clock.advance_to(START + timedelta(hours=48) - timedelta(seconds=1))  # 同上：drain 需单调时钟
    drain(sched2, clock)
    row = get_row(sched2, run_id)
    assert row.n == 20 and row.verdict == "pass"


def test_create_app_migrates_legacy_db_adds_plan_json(tmp_path):
    """旧库（T1.30 版本建的表，无 plan_json 列）：create_app 幂等补列。"""
    from sqlalchemy import create_engine, inspect, text

    from forge_server.app import create_app
    from forge_server.models import Base, CertificationRun

    db = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(engine)  # 全新表
    with engine.connect() as c:  # 手工删列 = 模拟旧版本库（SQLite 无 DROP COLUMN 旧版兼容：重建表）
        c.execute(text("ALTER TABLE certification_runs RENAME TO certification_runs_new"))
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(certification_runs_new)"))]
        keep = ", ".join(x for x in cols if x != "plan_json")
        c.execute(text(
            f"CREATE TABLE certification_runs AS SELECT {keep} FROM certification_runs_new"))
        c.execute(text("DROP TABLE certification_runs_new"))
        c.commit()
    engine.dispose()

    app = create_app(f"sqlite:///{db.as_posix()}")
    check = create_engine(f"sqlite:///{db.as_posix()}")
    names = {r[1] for r in check.connect().execute(text("PRAGMA table_info(certification_runs)"))}
    assert "plan_json" in names
    # 二次启动幂等
    create_app(f"sqlite:///{db.as_posix()}")

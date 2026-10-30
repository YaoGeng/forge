"""T1.34 用例矩阵：抽查重测链路——抽样/生命周期/WS 位图续传/三维比对/处置（M09 §3.4/§8.3；C9/C10）。
"""
import json
import random

from fastapi.testclient import TestClient

from forge_certifier import accept_spotcheck
from forge_server.spotcheck import (
    SPOTCHECK_TIMEOUT_D,
    CompareResult,
    compare_reports,
    create_spotcheck_tasks,
    pick_spotcheck,
    sweep_timeouts,
)

from test_report_upload import (
    GOOD_GOLDEN,
    get_nonce,
    make_report,
    register_key,
    signed_payload,
    submit_c1_run,
    upload,
)

STEPS_20 = [
    {"index": i, "ok": True, "failure_class": None,
     "action": "nav" if i == 0 else "click", "anchor": f"a||/{i}", "duration_ms": 100}
    for i in range(20)
]
SHAPE_20 = ["GET example.com /search?q"]


def original_report():
    return {
        "runs": [dict(r) for r in STEPS_20],
        "env_fingerprint": "0123456789abcdef",
        "fail_json": {"failures": []},
        "durations": [100] * 20,
        "network_shape": list(SHAPE_20),
    }


def store_c1_report(app):
    """走真实上传链落一份可抽查的 C1 报告（报告细节随受理落盘 report_root）。"""
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)
    payload = signed_payload(key, get_nonce(client, key), make_report(n=20))
    payload["golden"] = GOOD_GOLDEN
    r = upload(client, run_id, payload)
    assert r.json()["verdict"] == "pass"
    return run_id


def make_task(app, clock, *, count=1, seed=7):
    created = []
    for _ in range(count):
        created.extend(
            create_spotcheck_tasks(
                app.state.session_factory, clock=clock, rng=random.Random(seed),
                report_root=app.state.report_root,
            )
        )
    return created


def stream_steps(ws, *, seqs=None, action_override=None, duration_ms=100, shape=None):
    """按原报告序逐 step 上送（C10 行协议 + action/anchor 扩展位）。"""
    for i in (seqs if seqs is not None else range(20)):
        r = STEPS_20[i]
        ws.send_json({
            "seq": i, "ok": True, "duration_ms": duration_ms,
            "action": action_override or r["action"], "anchor": r["anchor"],
        })
    if shape is not False:
        ws.send_json({"type": "network_shape", "shape": list(SHAPE_20)})


# --- 抽样与比对纯函数 -----------------------------------------------------------------


def test_pick_ratio():
    ids = list(range(25))
    picked = pick_spotcheck(ids, rng=random.Random(7))
    assert len(picked) >= 3  # 每 10 份 ≥1（25 → ≥3）
    assert set(picked) <= set(ids)
    assert len(picked) == len(set(picked))  # 不重复抽
    assert len(pick_spotcheck(list(range(10)), rng=random.Random(1))) == 1
    assert pick_spotcheck([], rng=random.Random(1)) == []


def test_compare_all_three_dimensions():
    base = original_report()

    # ①步骤序列：action 变化 → mismatch
    seq_changed = original_report()
    seq_changed["runs"][5] = dict(seq_changed["runs"][5], action="input")
    r1 = compare_reports(base, seq_changed)
    assert isinstance(r1, CompareResult) and not r1.ok and "steps" in r1.mismatches

    # ②时序分布：步时长超出原报告 P25-P75 带 → mismatch
    timing_out = original_report()
    timing_out["runs"][3] = dict(timing_out["runs"][3], duration_ms=10_000)
    r2 = compare_reports(base, timing_out)
    assert not r2.ok and "timing" in r2.mismatches

    # ③网络行为形状：Jaccard 0.5 < 0.7 → mismatch
    shape_off = original_report()
    shape_off["network_shape"] = SHAPE_20 + [f"GET example.com /p{i}" for i in range(20)]
    r3 = compare_reports(base, shape_off)
    assert not r3.ok and "network" in r3.mismatches

    same = compare_reports(base, original_report())
    assert same.ok and same.mismatches == ()


# --- 任务生命周期与 WS 流式 ------------------------------------------------------------


def test_task_lifecycle_happy(make_app, clock):
    app = make_app()
    run_id = store_c1_report(app)
    client = TestClient(app)

    task_id = make_task(app, clock)[0]
    tasks = client.get("/api/v1/certifications/spotcheck/tasks").json()["tasks"]
    assert any(t["id"] == task_id and t["status"] == "pending" for t in tasks)

    r = client.post(f"/api/v1/certifications/spotcheck/tasks/{task_id}/accept")
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert client.post(f"/api/v1/certifications/spotcheck/tasks/{task_id}/accept").status_code == 409

    with client.websocket_connect(f"/api/v1/certifications/{run_id}/stream?task_id={task_id}") as ws:
        greeting = ws.receive_json()
        assert greeting["received_seqs"] == []
        stream_steps(ws)
        result = ws.receive_json()
    assert result["type"] == "done" and result["ok"] is True

    row = _task(app, task_id)
    assert row["status"] == "done"  # pending→accepted→streaming→done
    assert row["compare_json"]["result"] == "match"


def test_stream_resume_with_seq_bitmap(make_app, clock):
    app = make_app()
    run_id = store_c1_report(app)
    client = TestClient(app)
    task_id = make_task(app, clock)[0]
    client.post(f"/api/v1/certifications/spotcheck/tasks/{task_id}/accept")

    with client.websocket_connect(f"/api/v1/certifications/{run_id}/stream?task_id={task_id}") as ws:
        assert ws.receive_json()["received_seqs"] == []
        stream_steps(ws, seqs=range(7), shape=False)
    # 连接中断于 seq=6（已收 0..6）

    with client.websocket_connect(f"/api/v1/certifications/{run_id}/stream?task_id={task_id}") as ws:
        assert ws.receive_json()["received_seqs"] == list(range(7))
        stream_steps(ws, seqs=list(range(6, 20)))  # 重连续传：seq6 重复不双计
        result = ws.receive_json()

    assert result["type"] == "done"
    row = _task(app, task_id)
    assert len(row["compare_json"]["retest"]["runs"]) == 20  # 幂等续传不重复计数


def test_ws_requires_accepted_task(make_app, clock):
    app = make_app()
    run_id = store_c1_report(app)
    client = TestClient(app)
    task_id = make_task(app, clock)[0]

    with client.websocket_connect(f"/api/v1/certifications/{run_id}/stream?task_id={task_id}") as ws:
        greeting = ws.receive_json()
        assert greeting.get("error") == "task_not_accepted"  # 未 accept 直连被拒

    with client.websocket_connect(f"/api/v1/certifications/{run_id}/stream?task_id=99999") as ws:
        assert ws.receive_json().get("error") is not None  # 未知任务同样拒绝


def test_mismatch_triggers_invalid(make_app, clock):
    app = make_app()
    run_id = store_c1_report(app)
    client = TestClient(app)
    task_id = make_task(app, clock)[0]
    client.post(f"/api/v1/certifications/spotcheck/tasks/{task_id}/accept")

    with client.websocket_connect(f"/api/v1/certifications/{run_id}/stream?task_id={task_id}") as ws:
        ws.receive_json()
        stream_steps(ws, action_override="input")  # 序列维度不符
        result = ws.receive_json()

    assert result["type"] == "done" and result["ok"] is False
    row = _task(app, task_id)
    assert row["status"] == "mismatch"
    assert row["compare_json"]["disposition"] == "attestation_invalid"  # 处置记录（M09 §3.4）
    assert row["compare_json"]["mismatches"] == ["steps"]
    data = client.get(f"/api/v1/certifications/{run_id}").json()
    assert data["verdict"] == "rejected"  # 原报告 run 判 rejected（delisted 联动 M10 登记缓办）


def test_timeout_14d(make_app, clock):
    app = make_app()
    run_id = store_c1_report(app)
    client = TestClient(app)
    task_id = make_task(app, clock)[0]

    clock.advance(days=SPOTCHECK_TIMEOUT_D - 1)
    sweep_timeouts(app.state.session_factory, clock=clock)
    assert _task(app, task_id)["status"] == "pending"

    clock.advance(days=2)  # 累计 +15 天未 accept
    sweep_timeouts(app.state.session_factory, clock=clock)
    assert _task(app, task_id)["status"] == "timeout"


def test_retest_params_from_server(make_app, clock):
    app = make_app()
    run_id = store_c1_report(app)
    client = TestClient(app)
    task_id = make_task(app, clock)[0]

    r = client.post(f"/api/v1/certifications/spotcheck/tasks/{task_id}/accept")
    task = r.json()
    assert task["params_json"]  # 服务端生成并下发

    sent = []
    seen_params = []

    def sender(step):
        sent.append(step)

    class FakeRunner:
        def run_once(self, block_ref, params=None, *, mode="local", browser_factory=None):
            seen_params.append(dict(params or {}))
            from forge_server.sandbox import RunOutcome

            return RunOutcome(
                mode=mode, ok=True,
                step_results=tuple(
                    {"seq": r["index"], "action": r["action"], "anchor": r["anchor"],
                     "ok": True, "anchor_matched": True, "duration_ms": r["duration_ms"],
                     "snapshot_digest": "d"}
                    for r in STEPS_20
                ),
                network_shape=frozenset(SHAPE_20),
            )

    accept_spotcheck(
        task, block_ref="probe", runner=FakeRunner(), sender=sender
    )
    assert seen_params == [task["params_json"]]  # 客户端执行参数 = 服务端随机生成（M09 §6）
    assert len(sent) >= 20  # 逐 step 结果（含 network_shape 控制行）


def _task(app, task_id):
    with app.state.session_factory() as s:
        from forge_server.models import SpotcheckTask

        row = s.get(SpotcheckTask, task_id)
        return {
            "id": row.id,
            "status": row.status,
            "compare_json": row.compare_json,
            "params_json": row.params_json,
        }

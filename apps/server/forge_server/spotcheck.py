"""抽查重测链路（M09 §3.4/§8.3）：抽样、任务生命周期、C9 三维比对、C10 流式行协议 + 处置。

C10 行协议：客户端逐 step 发 JSON 行 {seq, ok, duration_ms, ts}；v1 扩展位 = action/anchor/
network_shape 控制行（比对三维所需；服务端容忍未知键）。断线重连先推已收 seq 位图（幂等续传）。
"""
import json
import math
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from .models import CertificationRun, SpotcheckTask

SPOTCHECK_RATIO = 10  # 每 10 份 C1 报告至少抽 1（滚动）
SPOTCHECK_TIMEOUT_D = 14  # 超期未响应 → timeout（同「创作者超期未响应」归因档）
NETWORK_JACCARD_MIN = 0.7  # C9 ③ 网络行为形状下限
WINDOW_D = 7  # 重测时间窗


@dataclass(frozen=True)
class CompareResult:
    ok: bool
    mismatches: tuple[str, ...]
    detail: dict


def pick_spotcheck(report_ids, *, rng) -> list[int]:
    """每 10 份 ≥1 抽样（ceil），不重复。"""
    ids = sorted(set(report_ids))
    count = math.ceil(len(ids) / SPOTCHECK_RATIO)
    return sorted(rng.sample(ids, count)) if count else []


def _band(durations) -> tuple[int, int]:
    ds = sorted(int(d) for d in durations)
    if not ds:
        return (0, 0)
    return (ds[int(0.25 * (len(ds) - 1))], ds[int(0.75 * (len(ds) - 1))])


def _jaccard(a, b) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def compare_reports(original: dict, retest: dict) -> CompareResult:
    """C9 三维：①步骤序列（v1 按 action+步数逐等；replay StepResult 不含 dom_anchor，
    锚身份维度归 RunnerPort 扩展，登记缓办）②时序逐步落原报告 P25-P75 带内
    ③网络行为形状 Jaccard ≥0.7。任一维不符 → mismatch。"""
    mismatches: list[str] = []
    o_runs = original.get("runs", [])
    r_runs = retest.get("runs", [])

    o_seq = [r.get("action") for r in o_runs]
    r_seq = [r.get("action") for r in r_runs]
    if o_seq != r_seq:
        mismatches.append("steps")

    if len(o_runs) == len(r_runs) and o_runs:
        lo, hi = _band([r.get("duration_ms", 0) for r in o_runs])
        if any(not (lo <= int(r.get("duration_ms", 0)) <= hi) for r in r_runs):
            mismatches.append("timing")

    j = _jaccard(original.get("network_shape", []), retest.get("network_shape", []))
    if j < NETWORK_JACCARD_MIN:
        mismatches.append("network")

    return CompareResult(ok=not mismatches, mismatches=tuple(mismatches), detail={"network_jaccard": j})


def create_spotcheck_tasks(session_factory, *, clock, rng, report_root=None) -> list[int]:
    """滚动抽样建任务：未抽过的 C1 报告中按比例抽，参数服务端随机生成（M09 §6）。"""
    now = clock.now()
    out: list[int] = []
    with session_factory() as s:
        tasked = set(s.execute(select(SpotcheckTask.report_id)).scalars())
        c1_ids = s.execute(
            select(CertificationRun.id).where(
                CertificationRun.level == "C1",
                CertificationRun.verdict.is_not(None),
                CertificationRun.verdict != "rejected",
            )
        ).scalars().all()
        for rid in pick_spotcheck([i for i in c1_ids if i not in tasked], rng=rng):
            task = SpotcheckTask(
                report_id=rid,
                params_json={"q": str(rng.getrandbits(32))},
                window_start=now,
                window_end=now + timedelta(days=WINDOW_D),
                status="pending",
                compare_json={"received_seqs": [], "retest": None},
                created_at=now,
            )
            s.add(task)
            s.commit()
            out.append(task.id)
    return out


def sweep_timeouts(session_factory, *, clock) -> int:
    cutoff = clock.now() - timedelta(days=SPOTCHECK_TIMEOUT_D)
    with session_factory() as s:
        rows = s.execute(
            select(SpotcheckTask).where(
                SpotcheckTask.status == "pending",
                SpotcheckTask.created_at < cutoff,
            )
        ).scalars().all()
        for t in rows:
            t.status = "timeout"
            t.compare_json = {**(t.compare_json or {}), "disposition": "creator_timeout"}
        s.commit()
        return len(rows)


def register_spotcheck_routes(app):
    session_factory = app.state.session_factory

    def _iso(dt):
        return dt.isoformat() if dt is not None else None

    @app.get("/api/v1/certifications/spotcheck/tasks")
    def list_tasks():
        sweep_timeouts(session_factory, clock=app.state.clock)
        with session_factory() as s:
            rows = s.execute(select(SpotcheckTask).order_by(SpotcheckTask.id)).scalars().all()
            return {
                "tasks": [
                    {
                        "id": t.id,
                        "report_id": t.report_id,
                        "status": t.status,
                        "params_json": t.params_json,
                        "window_start": _iso(t.window_start),
                        "window_end": _iso(t.window_end),
                    }
                    for t in rows
                ]
            }

    @app.post("/api/v1/certifications/spotcheck/tasks/{task_id}/accept")
    def accept_task(task_id: int):
        with session_factory() as s:
            t = s.get(SpotcheckTask, task_id)
            if t is None:
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="task not found")
            if t.status != "pending":
                from fastapi import HTTPException

                raise HTTPException(status_code=409, detail=f"task not pending: {t.status}")
            t.status = "accepted"
            s.commit()
            return {
                "task_id": t.id,
                "status": "accepted",
                "report_id": t.report_id,
                "params_json": t.params_json,
                "window_start": _iso(t.window_start),
                "window_end": _iso(t.window_end),
            }

    @app.websocket("/api/v1/certifications/{run_id}/stream")
    async def stream(ws: WebSocket, run_id: int, task_id: int):
        await ws.accept()
        with session_factory() as s:
            t = s.get(SpotcheckTask, task_id)
        if t is None or t.report_id != run_id:
            await ws.send_json({"error": "task_not_found"})
            await ws.close()
            return
        if t.status not in ("accepted", "streaming"):  # streaming = 断线续传重入（C10）
            await ws.send_json({"error": "task_not_accepted"})
            await ws.close()
            return

        compare = dict(t.compare_json or {})
        with session_factory() as s:
            run = s.get(CertificationRun, run_id)
        expected_n = run.n if run else 0

        seen: set[int] = set(compare.get("received_seqs", []))
        steps: dict[str, dict] = dict((compare.get("retest") or {}).get("runs", {}))
        shape = (compare.get("retest") or {}).get("network_shape")

        def _persist(status=None):
            with session_factory() as s:
                row = s.get(SpotcheckTask, task_id)
                row.status = status or row.status
                row.compare_json = {
                    "received_seqs": sorted(seen),
                    "retest": {"runs": steps, "network_shape": shape},
                    **({"result": row.compare_json.get("result")} if row.compare_json else {}),
                }
                s.commit()

        await ws.send_json({"type": "resume", "received_seqs": sorted(seen)})
        try:
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "network_shape":
                    shape = list(msg.get("shape", []))
                else:
                    seq = msg.get("seq")
                    if seq not in seen:  # 幂等续传：重复 seq 不双计（C10）
                        seen.add(seq)
                        steps[str(seq)] = {
                            "seq": seq,
                            "ok": msg.get("ok"),
                            "duration_ms": msg.get("duration_ms"),
                            "action": msg.get("action"),
                        }
                    _persist(status="streaming")
                if seen and len(seen) >= expected_n and shape is not None:
                    result = _finish(task_id, run_id, seen, steps, shape)
                    await ws.send_json(result)
                    return
        except WebSocketDisconnect:
            _persist()  # 断线保状态，重连带位图续传（C10）
            return
        except Exception:
            _persist()
            raise

    def _load_original(report_id: int) -> dict:
        p = Path(app.state.report_root) / f"run-{report_id}.json"
        return json.loads(p.read_text(encoding="utf-8"))

    def _finish(task_id: int, run_id: int, seen, steps, shape) -> dict:
        original = _load_original(run_id)
        retest = {
            "runs": [steps[str(i)] for i in sorted(seen)],
            "network_shape": list(shape),
        }
        verdict = compare_reports(original, retest)
        with session_factory() as s:
            task = s.get(SpotcheckTask, task_id)
            task.status = "done" if verdict.ok else "mismatch"
            task.compare_json = {
                "received_seqs": sorted(seen),
                "retest": retest,
                "result": "match" if verdict.ok else "mismatch",
                "mismatches": list(verdict.mismatches),
                "detail": verdict.detail,
                **({} if verdict.ok else {"disposition": "attestation_invalid"}),
            }
            if not verdict.ok:  # 处置（M09 §3.4）：mismatch → 判 rejected；delisted 联动 M10 登记缓办
                run_row = s.get(CertificationRun, run_id)
                run_row.verdict = "rejected"
            s.commit()
        return {
            "type": "done",
            "ok": verdict.ok,
            "mismatches": list(verdict.mismatches),
        }

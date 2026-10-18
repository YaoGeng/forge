"""REST /api/v1/certifications*（M09 §5）：提交、报告查询、nonce、C1 报告上传、reliability。"""
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from . import attestation, golden_gate
from .api_devices import NonceRequest
from .models import CertificationRun, ClientDevice, run_to_dict
from .scheduler import best_effort, compute_verdict

C1_LABEL = "创作者环境实测，平台抽查复核"


class CertificationSubmit(BaseModel):
    subject_type: Literal["block", "app_version"]
    subject_id: str
    version: str
    level: Literal["C1", "C2", "chain"]
    site_tier: Literal["standard", "medium", "high", "protected"] = "standard"
    site_host: str | None = None  # 同站点跨 run 限频归组键（终审 Important#2）


class ReportUpload(BaseModel):
    device_fp: str
    report: dict
    attestation: dict
    signature: str
    golden: dict | None = None


def _iso(dt):
    return dt.isoformat() if dt is not None else None


def register_certification_routes(app):
    scheduler = app.state.scheduler
    session_factory = app.state.session_factory

    @app.post("/api/v1/certifications", status_code=201)
    def submit_certification(body: CertificationSubmit):
        run_id = scheduler.submit(
            body.subject_type, body.subject_id, body.version, body.level,
            site_tier=body.site_tier, site_host=body.site_host
        )
        return {"run_id": run_id}

    @app.get("/api/v1/certifications/{run_id}")
    def get_certification(run_id: int):
        with session_factory() as s:
            row = s.get(CertificationRun, run_id)
            if row is None:
                raise HTTPException(status_code=404, detail="certification run not found")
            data = run_to_dict(row)
        data["best_effort"] = best_effort(scheduler.tier_of(run_id))
        data["status"] = scheduler.status_of(run_id)
        data["segments"] = scheduler.segments_view(run_id)
        return data

    @app.post("/api/v1/certifications/nonce", status_code=201)
    def issue_nonce(body: NonceRequest):
        with session_factory() as s:
            dev = s.execute(
                select(ClientDevice).where(ClientDevice.device_fp == body.device_fp)
            ).scalar_one_or_none()
        if dev is None:
            raise HTTPException(status_code=404, detail="device not registered")
        nonce, expires_at = app.state.nonces.issue(body.device_fp)
        return {"nonce": nonce, "expires_at": expires_at, "device_id": dev.id}

    @app.post("/api/v1/certifications/{run_id}/report")
    def upload_report(run_id: int, body: ReportUpload):
        """初验链（M09 §3.2）：验签 → nonce 消费 → 时长下限 → golden 拒收 → 落库 → verdict。

        幂等：同 (report_hash, nonce) 已成功受理 → 原样返回，不重复计数。
        """
        reasons: list[str] = []
        with session_factory() as s:
            row = s.get(CertificationRun, run_id)
            if row is None:
                raise HTTPException(status_code=404, detail="certification run not found")

        nonce = str(body.attestation.get("nonce", ""))
        r_hash = attestation.report_hash(body.report)
        cached = app.state.report_results.get((run_id, r_hash, nonce))
        if cached is not None:
            return cached

        runs = body.report.get("runs", [])
        n = len(runs)
        if row.level != "C1":
            reasons.append("上传通道仅限 C1 run（M09 §5）；C2/chain 由调度器与执行器落库")
        if body.attestation.get("report_hash") != attestation.report_hash(body.report):
            reasons.append("report_hash 与报告不符（签名未覆盖该报告内容，C7 绑定失败）")
        if r_hash in (row.accepted_report_hashes or []):
            reasons.append("同报告哈希已受理（换 nonce 重传不重复计数）")

        dev = None
        with session_factory() as s:
            dev = s.execute(
                select(ClientDevice).where(ClientDevice.device_fp == body.device_fp)
            ).scalar_one_or_none()
        if dev is None:
            reasons.append("device 未注册")
        else:
            if not attestation.verify(body.attestation, body.signature, dev.public_key):
                reasons.append("签名验证失败（attestation 与注册公钥不符）")
            nonce_owner = app.state.nonces.consume(nonce)
            if nonce_owner is None:
                reasons.append("nonce 无效/已消费/已过期")
            elif nonce_owner != body.device_fp:
                reasons.append("nonce 属主与报告设备不符")
            if not attestation.duration_floor_ok(body.report.get("durations"), n):
                reasons.append(
                    f"时长低于下限（{attestation.MIN_RUN_SECONDS}s/run，N={n}）"
                )
            if body.golden is None:
                reasons.append("golden 缺失")
            else:
                reasons.extend(_inspect_golden(run_id, body.golden))

        response = _finalize_report(row, body, runs, reasons, r_hash)
        if not reasons:  # 仅成功受理入幂等缓存；拒绝后换新 nonce 重传可重试
            app.state.report_results[(run_id, r_hash, nonce)] = response
        return response

    def _inspect_golden(run_id: int, golden: dict) -> list[str]:
        golden_dir = Path(app.state.golden_root) / f"run-{run_id}"
        golden_dir.mkdir(parents=True, exist_ok=True)
        (golden_dir / "expected_steps.ndjson").write_text(
            "".join(json.dumps(step, ensure_ascii=False) + "\n" for step in golden.get("expected_steps", [])),
            encoding="utf-8",
        )
        (golden_dir / "network_stubs.json").write_text(
            json.dumps(golden.get("network_stubs", {"entries": []}), ensure_ascii=False),
            encoding="utf-8",
        )
        return golden_gate.inspect(golden_dir)

    def _finalize_report(row: CertificationRun, body: ReportUpload, runs, reasons,
                         r_hash: str) -> dict:
        n = len(runs)
        if reasons:
            with session_factory() as s:
                attached = s.get(CertificationRun, row.id)
                if attached.verdict is None and attached.attestation_sig is None:
                    attached.verdict = "rejected"  # 仅首判落 rejected；既判不被失败重传降级
                s.commit()
            return {"verdict": "rejected", "reasons": reasons,
                    "live_pass_rate": None, "regression_pass_rate": None}

        pass_count = sum(1 for r in runs if r.get("ok"))
        with session_factory() as s:
            attached = s.get(CertificationRun, row.id)
            # C1 累计口径（docs/12 T1.35）：多时段分批上传按 N/pass 累计，
            # 通过率与 verdict 按累计重算——末批替换语义是时钟日偏差（EVIDENCE 2026-10-18）。
            attached.n = (attached.n or 0) + n
            attached.pass_count = (attached.pass_count or 0) + pass_count
            live_rate = attached.pass_count / attached.n
            attached.live_pass_rate = live_rate
            attached.regression_pass_rate = None  # C1 上传通道无 golden 回放，分列不混算
            attached.attestation_sig = body.signature
            attached.accepted_report_hashes = list(attached.accepted_report_hashes or []) + [r_hash]
            now = app.state.clock.now()
            if attached.started_at is None:
                attached.started_at = now
            attached.finished_at = now
            attached.verdict = compute_verdict(
                scheduler.tier_of(row.id), live_rate, 0.0, frozenset()
            )
            s.commit()
            # 报告细节落盘（仅存认证服务端，M09 §3.2 存储边界；抽查比对基准源）
            report_path = Path(app.state.report_root) / f"run-{row.id}.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(body.report, ensure_ascii=False), encoding="utf-8"
            )
            response = {
                "verdict": attached.verdict,
                "reasons": [],
                "live_pass_rate": attached.live_pass_rate,
                "regression_pass_rate": attached.regression_pass_rate,
            }
        return response

    @app.get("/api/v1/blocks/{name}/versions/{version}/reliability")
    def reliability(name: str, version: str):
        """详情页初始分：仅 live 口径（M09 §5 逐字，regression 不出此门）。"""
        with session_factory() as s:
            rows = (
                s.execute(
                    select(CertificationRun)
                    .where(
                        CertificationRun.subject_type == "block",
                        CertificationRun.subject_id == name,
                        CertificationRun.version == version,
                        CertificationRun.verdict.is_not(None),
                        CertificationRun.verdict != "rejected",
                    )
                    .order_by(CertificationRun.id.desc())
                )
                .scalars()
                .all()
            )
        latest = rows[0] if rows else None
        if latest is None:
            return {
                "status": "insufficient",
                "message": "数据不足",
                "pass_rate": None,
                "n": 0,
                "window_start": None,
                "window_end": None,
                "c1_label": None,
            }
        return {
            "status": "ok",
            "pass_rate": latest.live_pass_rate,
            "n": latest.n,
            "window_start": _iso(latest.started_at),
            "window_end": _iso(latest.finished_at),
            "c1_label": C1_LABEL if latest.level == "C1" else None,
        }

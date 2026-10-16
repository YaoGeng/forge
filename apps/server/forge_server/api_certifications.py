"""REST /api/v1/certifications*（M09 §5）：提交、报告查询、nonce。T1.33 增 report 上传与 reliability。"""
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .api_devices import NonceRequest
from .models import CertificationRun, ClientDevice, run_to_dict
from .scheduler import best_effort


class CertificationSubmit(BaseModel):
    subject_type: Literal["block", "app_version"]
    subject_id: str
    version: str
    level: Literal["C1", "C2", "chain"]
    site_tier: Literal["standard", "medium", "high", "protected"] = "standard"


def register_certification_routes(app):
    scheduler = app.state.scheduler
    session_factory = app.state.session_factory

    @app.post("/api/v1/certifications", status_code=201)
    def submit_certification(body: CertificationSubmit):
        run_id = scheduler.submit(
            body.subject_type, body.subject_id, body.version, body.level, site_tier=body.site_tier
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

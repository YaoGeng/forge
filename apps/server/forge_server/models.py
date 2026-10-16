"""ORM 三表（M09 §4 逐字：字段不得新增/改名/删除，G6）。

注：`pass` 为 Python 关键字，ORM 属性名 pass_count，列名/JSON 出口键保持 `pass`。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CertificationRun(Base):
    __tablename__ = "certification_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(32))  # block / app_version
    subject_id: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(16))  # C1 / C2 / chain
    n: Mapped[int] = mapped_column(Integer, default=0)
    pass_count: Mapped[int] = mapped_column("pass", Integer, default=0)
    live_pass_rate: Mapped[float | None] = mapped_column(default=None)
    regression_pass_rate: Mapped[float | None] = mapped_column(default=None)
    env_fingerprint_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    fail_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    attestation_sig: Mapped[str | None] = mapped_column(Text, default=None)  # C1 时非空
    batch_id: Mapped[str] = mapped_column(String(64))  # 批次礼仪审计
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    verdict: Mapped[str | None] = mapped_column(String(32), default=None)


class SpotcheckTask(Base):
    __tablename__ = "spotcheck_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(Integer, index=True)
    params_json: Mapped[dict] = mapped_column(JSON)
    window_start: Mapped[datetime] = mapped_column(DateTime)
    window_end: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16))  # pending/accepted/streaming/done/mismatch/timeout
    compare_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ClientDevice(Base):
    __tablename__ = "client_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[str] = mapped_column(String(255), index=True)
    public_key: Mapped[str] = mapped_column(Text)
    device_fp: Mapped[str] = mapped_column(String(64))
    registered_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


def run_to_dict(row: CertificationRun) -> dict:
    """API 出口（live/regression 分列原样，不做任何合计派生）。"""

    def _iso(dt):
        return dt.isoformat() if dt is not None else None

    return {
        "id": row.id,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "version": row.version,
        "level": row.level,
        "n": row.n,
        "pass": row.pass_count,
        "live_pass_rate": row.live_pass_rate,
        "regression_pass_rate": row.regression_pass_rate,
        "env_fingerprint_json": row.env_fingerprint_json,
        "fail_json": row.fail_json,
        "attestation_sig": row.attestation_sig,
        "batch_id": row.batch_id,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "verdict": row.verdict,
    }

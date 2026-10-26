"""ORM 三表（M09 §4 逐字：字段不得新增/改名/删除，G6）。

注：`pass` 为 Python 关键字，ORM 属性名 pass_count，列名/JSON 出口键保持 `pass`。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
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
    accepted_report_hashes: Mapped[list | None] = mapped_column(JSON, default=None)  # 已受理报告哈希（C1 累计口径防重放）
    batch_id: Mapped[str] = mapped_column(String(64))  # 批次礼仪审计
    plan_json: Mapped[dict | None] = mapped_column(JSON, default=None)  # 批次计划+进度（审计伴生：跨进程重建调度态；不进 API 读出口）
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


class Block(Base):
    """M10 §4 blocks 子集（阶段 1 内部注册；distribution=public 自营）。"""

    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    distribution: Mapped[str] = mapped_column(String(32), default="public")
    owner_id: Mapped[str] = mapped_column(String(255), default="platform")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BlockVersion(Base):
    """M10 §4 block_versions 子集；reliability_json = 注册时刻认证快照（C13）。

    side_effects/domains_json 为阶段 1 内部元数据（画布副作用规则与合规声明消费；
    M10-a 正式化时对齐 permissions_max 口径——台账登记）。
    """

    __tablename__ = "block_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[str] = mapped_column(String(64))
    change_kind: Mapped[str] = mapped_column(String(32), default="code")
    certification_level: Mapped[str] = mapped_column(String(16))
    reliability_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    side_effects: Mapped[bool] = mapped_column(default=False)
    domains_json: Mapped[list | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class App(Base):
    __tablename__ = "apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[str] = mapped_column(String(255), default="platform")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AppVersion(Base):
    """M10 §4 app_versions 子集：status 仅 draft/published（完整状态机阶段 2，C11）。"""

    __tablename__ = "app_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    composition_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    user_input_schema_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AppBlockRef(Base):
    """M10 §4 block_refs 子集：应用对积木版本的引用（发布时基准）。"""

    __tablename__ = "block_refs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(Integer, index=True)
    block_name: Mapped[str] = mapped_column(String(255))
    base_version: Mapped[str] = mapped_column(String(64))
    patch_window: Mapped[str | None] = mapped_column(JSON, default=None)


class CreationSession(Base):
    """M02 §4 creation_sessions 投影（阶段 1 服务端会话，D-M1F.1）。"""

    __tablename__ = "creation_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_text: Mapped[str] = mapped_column(Text, default="")
    step: Mapped[int] = mapped_column(Integer, default=1)
    draft_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    autosave_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class User(Base):
    """MS-2 买家账号（docs/17 T2.01）：密码只存 scrypt 摘要，绝无明文。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AuthSession(Base):
    """MS-2 会话（docs/17 T2.01）：token 服务端持有（可吊销），30 天过期。"""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


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

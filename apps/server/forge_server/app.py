"""FastAPI 装配：路由注册 + lifespan（进程内 asyncio 调度循环；建表在 create_app 即完成，
便于 ASGITransport/TestClient 无 lifespan 测试路径）。REST 契约见 M09 §5。
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api_certifications import register_certification_routes
from .api_devices import NonceStore, register_device_routes
from .auth import register_auth_routes, register_me_routes
from .db import make_engine
from .etiquette import Clock
from .models import Base
from .creator import register_creator_routes
from .packages import register_package_routes
from .registry import register_registry_routes
from .scheduler import CertScheduler, SegRunHook, WallClock
from .spotcheck import register_spotcheck_routes
from .store import register_report_routes, register_store_routes


def _ensure_plan_json_column(engine) -> None:
    """旧库补列（幂等）：certification_runs.plan_json——批次计划跨进程重建所需；
    accepted_report_hashes——C1 上传累计口径防重放（时钟日偏差修复）。"""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    have = {c["name"] for c in inspector.get_columns("certification_runs")}
    for col in ("plan_json", "accepted_report_hashes"):
        if col in have:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE certification_runs ADD COLUMN {col} JSON"))


def _ensure_new_columns(engine) -> None:
    """旧库补列（幂等，v0.1.3 → v0.2 增量）：block_versions.code_digest/code_bundle。"""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    have = {c["name"] for c in inspector.get_columns("block_versions")}
    for col, ddl in (("code_digest", "VARCHAR(128)"),
                     ("code_bundle", "VARCHAR(512)")):
        if col not in have:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE block_versions ADD COLUMN {col} {ddl}"))


def create_app(
    db_url: str,
    *,
    clock: Clock | None = None,
    executor_hook: SegRunHook | None = None,
    golden_root=None,
    report_root=None,
    bundles_root=None,
    signing_key: bytes | None = None,
    docs: bool = False,
) -> FastAPI:
    import base64
    import logging
    import os
    import secrets
    import tempfile
    from pathlib import Path

    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    _ensure_plan_json_column(engine)  # v1 载体迁移：T1.30 旧库无此列（Alembic 后置，D-M1E.1）
    _ensure_new_columns(engine)  # MS-2 T2.04：v0.1.3 旧库补 code_digest/code_bundle
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    clock = clock or WallClock()
    scheduler = CertScheduler(session_factory, clock=clock, executor_hook=executor_hook)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(_scheduler_loop(_app))
        yield
        task.cancel()

    # 生产默认关交互文档（docs/16 决策 2：v0 全站 Basic 前不额外暴露 API 面）
    fastapi_kwargs = {} if docs else {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }
    app = FastAPI(title="forge-server", lifespan=lifespan, **fastapi_kwargs)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.clock = clock
    app.state.scheduler = scheduler
    app.state.nonces = NonceStore(clock)
    app.state.golden_root = Path(golden_root) if golden_root else Path(
        tempfile.mkdtemp(prefix="forge-server-golden-")
    )
    app.state.report_root = Path(report_root) if report_root else Path(
        tempfile.mkdtemp(prefix="forge-server-reports-")
    )
    app.state.bundles_root = Path(bundles_root) if bundles_root else Path(
        tempfile.mkdtemp(prefix="forge-server-bundles-")
    )
    # 运行器分发（T2.13）：dist_root 指向 exe 存放目录（生产 = FORGE_DIST_DIR，
    # __main__ 缺省 data_dir/dist）；runner_version 来自 FORGE_RUNNER_VERSION
    app.state.dist_root = Path(os.environ.get("FORGE_DIST_DIR") or "") if \
        os.environ.get("FORGE_DIST_DIR") else None
    app.state.runner_version = os.environ.get("FORGE_RUNNER_VERSION", "")
    # 签名钥（T2.04）：FORGE_SIGNING_KEY（base64 32B）注入；缺省生成临时钥+告警（开发态，
    # 重启即换、TOFU 客户端拒连）。"无钥 503" 语义经 state.forge_signing_key=None 表达（测试用）。
    env_key = os.environ.get("FORGE_SIGNING_KEY", "").strip()
    if signing_key is not None:
        app.state.forge_signing_key = signing_key
    elif env_key:
        app.state.forge_signing_key = base64.b64decode(env_key)
    else:
        app.state.forge_signing_key = secrets.token_bytes(32)
        logging.getLogger(__name__).warning(
            "FORGE_SIGNING_KEY 未注入——已生成临时签名钥（重启即换，TOFU 客户端将拒连；"
            "仅限开发/测试，生产必须注入）")
    app.state.report_results = {}  # 幂等缓存：(run_id, report_hash, nonce) → 响应（v1 载体内存态）
    app.state.chain_runner = None  # T1.64a：chain 认证执行器（驱动器/工具装配；None → 503）

    register_certification_routes(app)
    register_device_routes(app)
    register_spotcheck_routes(app)
    register_registry_routes(app)
    register_creator_routes(app)
    register_auth_routes(app)
    register_me_routes(app)
    register_store_routes(app)
    register_report_routes(app)
    register_package_routes(app)

    from fastapi.responses import FileResponse

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        """部署契约探活（docs/16 接入契约 3）：进程活着即 200，不查库。"""
        return {"status": "ok"}

    @app.get("/creator", include_in_schema=False)
    def creator_index():
        return FileResponse(Path(__file__).parent / "creator_index.html", media_type="text/html")

    return app


async def _scheduler_loop(app: FastAPI) -> None:
    """进程内调度循环（D-M1E.1）：周期 tick，节奏由礼仪常量约束。"""
    while True:
        app.state.scheduler.tick()
        await asyncio.sleep(1.0)

"""FastAPI 装配：路由注册 + lifespan（进程内 asyncio 调度循环；建表在 create_app 即完成，
便于 ASGITransport/TestClient 无 lifespan 测试路径）。REST 契约见 M09 §5。
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api_certifications import register_certification_routes
from .api_devices import NonceStore, register_device_routes
from .db import make_engine
from .etiquette import Clock
from .models import Base
from .registry import register_registry_routes
from .scheduler import CertScheduler, SegRunHook, WallClock
from .spotcheck import register_spotcheck_routes


def _ensure_plan_json_column(engine) -> None:
    """旧库补列（幂等）：certification_runs.plan_json——批次计划跨进程重建所需。"""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "plan_json" in {c["name"] for c in inspector.get_columns("certification_runs")}:
        return
    with engine.begin() as c:
        c.execute(text("ALTER TABLE certification_runs ADD COLUMN plan_json JSON"))


def create_app(
    db_url: str,
    *,
    clock: Clock | None = None,
    executor_hook: SegRunHook | None = None,
    golden_root=None,
    report_root=None,
) -> FastAPI:
    import tempfile
    from pathlib import Path

    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    _ensure_plan_json_column(engine)  # v1 载体迁移：T1.30 旧库无此列（Alembic 后置，D-M1E.1）
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    clock = clock or WallClock()
    scheduler = CertScheduler(session_factory, clock=clock, executor_hook=executor_hook)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(_scheduler_loop(_app))
        yield
        task.cancel()

    app = FastAPI(title="forge-server", lifespan=lifespan)
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
    app.state.report_results = {}  # 幂等缓存：(run_id, report_hash, nonce) → 响应（v1 载体内存态）
    app.state.chain_runner = None  # T1.64a：chain 认证执行器（驱动器/工具装配；None → 503）

    register_certification_routes(app)
    register_device_routes(app)
    register_spotcheck_routes(app)
    register_registry_routes(app)
    return app


async def _scheduler_loop(app: FastAPI) -> None:
    """进程内调度循环（D-M1E.1）：周期 tick，节奏由礼仪常量约束。"""
    while True:
        app.state.scheduler.tick()
        await asyncio.sleep(1.0)

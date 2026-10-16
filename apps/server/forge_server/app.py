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
from .scheduler import CertScheduler, SegRunHook, WallClock


def create_app(
    db_url: str,
    *,
    clock: Clock | None = None,
    executor_hook: SegRunHook | None = None,
    golden_root=None,
) -> FastAPI:
    import tempfile
    from pathlib import Path

    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
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
    app.state.report_results = {}  # 幂等缓存：(run_id, report_hash, nonce) → 响应（v1 载体内存态）

    register_certification_routes(app)
    register_device_routes(app)
    return app


async def _scheduler_loop(app: FastAPI) -> None:
    """进程内调度循环（D-M1E.1）：周期 tick，节奏由礼仪常量约束。"""
    while True:
        app.state.scheduler.tick()
        await asyncio.sleep(1.0)

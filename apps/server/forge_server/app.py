"""FastAPI 装配：路由注册 + lifespan（进程内 asyncio 调度循环；建表在 create_app 即完成，
便于 ASGITransport 无 lifespan 测试路径）。REST 契约见 M09 §5。
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .db import make_engine
from .etiquette import Clock
from .models import Base, CertificationRun, run_to_dict
from .scheduler import CertScheduler, SegRunHook, WallClock, best_effort


class CertificationSubmit(BaseModel):
    subject_type: Literal["block", "app_version"]
    subject_id: str
    version: str
    level: Literal["C1", "C2", "chain"]
    site_tier: Literal["standard", "medium", "high"] = "standard"


def create_app(db_url: str, *, clock: Clock | None = None, executor_hook: SegRunHook | None = None) -> FastAPI:
    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    scheduler = CertScheduler(session_factory, clock=clock or WallClock(), executor_hook=executor_hook)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(_scheduler_loop(_app))
        yield
        task.cancel()

    app = FastAPI(title="forge-server", lifespan=lifespan)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.scheduler = scheduler

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

    return app


async def _scheduler_loop(app: FastAPI) -> None:
    """进程内调度循环（D-M1E.1）：周期 tick，节奏由礼仪常量约束。"""
    while True:
        app.state.scheduler.tick()
        await asyncio.sleep(1.0)

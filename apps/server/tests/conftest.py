"""apps/server 测试路径引导与公共夹具：forge_server 与各包均未安装为发行包。"""
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for rel in (
    "..",  # apps/server（forge_server 包根）
    "../../packages/trace/python",
    "../../packages/block-sdk/python",
    "../../packages/proto/python",
):
    p = (_HERE / rel).resolve()
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import httpx  # noqa: F401  （后续卡片 WS/上传链路复用）
import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from forge_server.app import create_app
from forge_server.etiquette import Clock
from forge_server.scheduler import CertScheduler
from forge_server.db import make_engine

START = datetime(2026, 10, 16, 9, 0, 0)  # naive UTC，与 Clock 协议口径一致


class FrozenClock:
    """测试注入时钟（C1：单测不真实等待；批次跨度 gate 不用假钟，仅单测用）。"""

    def __init__(self, start: datetime = START):
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta) -> None:
        self._now += timedelta(**delta)

    def advance_to(self, dt: datetime) -> None:
        self._now = dt


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def db_url(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'cert.db').as_posix()}"


@pytest.fixture
def make_scheduler(db_url, clock):
    def _make(hook=None) -> CertScheduler:
        from sqlalchemy.orm import sessionmaker

        from forge_server.models import Base

        engine = make_engine(db_url)
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        return CertScheduler(factory, clock=clock, executor_hook=hook)

    return _make


@pytest.fixture
def make_app(db_url, clock):
    def _make(hook=None):
        return create_app(db_url, clock=clock, executor_hook=hook)

    return _make


@pytest.fixture
def api(make_app) -> SimpleNamespace:
    app = make_app()
    client = TestClient(app)
    try:
        yield SimpleNamespace(app=app, client=client)
    finally:
        client.close()

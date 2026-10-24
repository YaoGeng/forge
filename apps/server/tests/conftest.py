"""apps/server 测试路径引导与公共夹具：forge_server 与各包均未安装为发行包。"""
import itertools
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for rel in (
    "..",  # apps/server（forge_server 包根）
    "../../../packages/trace/python",
    "../../../packages/trace/tests",  # FakeBrowser 假体（T1.31 起复用）
    "../../../packages/block-sdk/python",
    "../../../packages/proto/python",
    "../../../packages/certifier/python",  # T1.33 起复用 DeviceKey/canonical 语义
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


_PG_TEST_DB_COUNTER = itertools.count()


@pytest.fixture
def db_url(tmp_path):
    """缺省 sqlite 临时库（本地载体不变）；FORGE_TEST_DB_URL 指向 PG 时
    逐测试建独立库、测毕强删（docs/16 T1.81——PG 兼容验证入口，CI job3 消费；
    要求该连接串具备建库权限，CI service 默认 postgres 超户满足）。"""
    override = os.environ.get("FORGE_TEST_DB_URL")
    if not override:
        yield f"sqlite:///{(tmp_path / 'cert.db').as_posix()}"
        return

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    base = make_url(override)
    test_db = f"forge_test_{os.getpid()}_{next(_PG_TEST_DB_COUNTER)}"
    admin = create_engine(base.set(database="postgres"))
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    yield str(base.set(database=test_db))
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE "{test_db}" WITH (FORCE)'))
    admin.dispose()


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


@pytest.fixture
def root(tmp_path):
    """RecordingsStore 根目录（与 packages/trace 测试同名夹具同语义）。"""
    return tmp_path


@pytest.fixture
def drain():
    """推时钟逐 tick 执行全部到期 run：到点执行，不做真实等待。"""

    def _drain(sched, clock, until=None, limit=200):
        # limit 防护必须接线：同站限频挡执行时 next_due 恒返过去时刻、时钟不再前进，
        # 无防护即纯死循环（2026-10-23 SPAN=0 修订时实测卡死）
        for _ in range(limit):
            sched.tick()
            nxt = sched.next_due()
            if nxt is None or (until is not None and nxt > until):
                return
            clock.advance_to(nxt)
        raise AssertionError(f"drain exceeded {limit} ticks without converging")

    return _drain


@pytest.fixture
def get_row():
    from forge_server.models import CertificationRun

    def _get(sched, run_id) -> CertificationRun:
        with sched.session_factory() as s:
            return s.get(CertificationRun, run_id)

    return _get

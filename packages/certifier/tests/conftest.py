"""packages/certifier 测试路径引导：certifier/python 与 forge_server 均未安装为发行包。"""
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for rel in (
    "../../certifier/python",
    "../../../apps/backend",
    "../../../packages/trace/python",
    "../../../packages/trace/tests",
    "../../../packages/block-sdk/python",
    "../../../packages/proto/python",
):
    p = (_HERE / rel).resolve()
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pytest
from fastapi.testclient import TestClient

from forge_server.app import create_app

START = datetime(2026, 10, 16, 9, 0, 0)  # naive UTC


class FrozenClock:
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
def make_app(db_url, clock):
    def _make(hook=None):
        return create_app(db_url, clock=clock, executor_hook=hook)

    return _make

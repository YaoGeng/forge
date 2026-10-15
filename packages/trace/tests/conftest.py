"""packages/trace 测试路径引导：trace/python 与 proto/python 均未安装为发行包。"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for rel in ("../python", "../../proto/python"):
    p = (_HERE / rel).resolve()
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pytest


@pytest.fixture
def root(tmp_path):
    """RecordingsStore 根目录（C2：sqlite + traces/ + redaction_maps/）。"""
    return tmp_path

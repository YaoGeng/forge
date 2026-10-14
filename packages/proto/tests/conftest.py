"""packages/proto 测试路径引导：把 ../python 加入 sys.path（proto 尚未安装为发行包）。"""
import sys
from pathlib import Path

_PY = Path(__file__).resolve().parent.parent / "python"
if str(_PY) not in sys.path:
    sys.path.insert(0, str(_PY))

"""apps/runner 测试路径引导：runner 包 + server（一致性对照）+ 依赖包。"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for rel in (
    "..",  # apps/runner（forge_runner 包根）
    "../../server",  # forge_server（ChainRunner 对照）
    "../../../packages/trace/python",
    "../../../packages/trace/tests",
    "../../../packages/block-sdk/python",
    "../../../packages/proto/python",
    "../../../packages/certifier/python",
):
    p = (_HERE / rel).resolve()
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

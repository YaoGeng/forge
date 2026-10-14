"""sidecar 角色的代理进程入口（由 run_t101_windows.py 以 venv pythonw.exe 启动）。

用法：pythonw proxy_worker.py <endpoint_file> [connect_log_file]
- 启动 EgressProxy → 原子写 endpoint 文件 → 运行至被终止；
- connect_log_file 给定时每秒把 connect_log 快照写为 JSON 数组；
- 退出（含被 taskkill/terminate）前尽力清理 endpoint 文件并停止代理。
"""
import json
import sys
import time
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent  # spikes/
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from egress_fw.proxy import EgressProxy  # noqa: E402


def write_endpoint_file(path: Path, endpoint: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(endpoint, encoding="utf-8")
    tmp.replace(path)


def remove_endpoint_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: proxy_worker.py <endpoint_file> [connect_log_file]", file=sys.stderr)
        return 2
    endpoint_file = Path(argv[1])
    log_file = Path(argv[2]) if len(argv) > 2 else None
    proxy = EgressProxy()
    try:
        proxy.start()
        write_endpoint_file(endpoint_file, proxy.endpoint)
        while True:
            time.sleep(1)
            if log_file is not None:
                log_file.write_text(json.dumps(proxy.connect_log), encoding="utf-8")
    except KeyboardInterrupt:
        return 0
    finally:
        remove_endpoint_file(endpoint_file)
        proxy.stop()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

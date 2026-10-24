"""进程入口：python -m forge_server。环境变量契约 = 部署标准 §6（docs/16 T1.80）：
FORGE_DB_URL（默认本地 sqlite）/FORGE_HOST/FORGE_PORT/FORGE_DATA_DIR/FORGE_DOCS。"""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServeConfig:
    db_url: str
    host: str
    port: int
    docs: bool
    golden_root: Path | None
    report_root: Path | None


def _serve_config() -> ServeConfig:
    data_dir = os.environ.get("FORGE_DATA_DIR")
    golden_root = report_root = None
    if data_dir:
        base = Path(data_dir)
        golden_root = base / "golden"
        report_root = base / "reports"
    return ServeConfig(
        db_url=os.environ.get("FORGE_DB_URL", "sqlite:///./forge.db"),
        host=os.environ.get("FORGE_HOST", "127.0.0.1"),
        port=int(os.environ.get("FORGE_PORT", "8041")),
        docs=os.environ.get("FORGE_DOCS", "") == "1",
        golden_root=golden_root,
        report_root=report_root,
    )


def main() -> None:
    import uvicorn

    from .app import create_app

    cfg = _serve_config()
    if cfg.golden_root is not None:
        cfg.golden_root.mkdir(parents=True, exist_ok=True)
    if cfg.report_root is not None:
        cfg.report_root.mkdir(parents=True, exist_ok=True)
    app = create_app(
        cfg.db_url,
        golden_root=cfg.golden_root,
        report_root=cfg.report_root,
        docs=cfg.docs,
    )
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()

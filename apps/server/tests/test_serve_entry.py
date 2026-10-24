"""T1.80 服务入口契约：/healthz、生产关 docs、__main__ 环境变量解析（docs/16 部署标准契约 3/2）。"""
import importlib

import pytest


def test_healthz_returns_ok(api):
    resp = api.client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_docs_disabled_by_default(api):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert api.client.get(path).status_code == 404, path


def test_docs_enabled_with_flag(db_url):
    from forge_server.app import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app(db_url, docs=True))
    try:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200
    finally:
        client.close()


@pytest.fixture
def main_mod():
    return importlib.import_module("forge_server.__main__")


def test_serve_config_defaults(main_mod, monkeypatch):
    for var in ("FORGE_DB_URL", "FORGE_HOST", "FORGE_PORT", "FORGE_DATA_DIR", "FORGE_DOCS"):
        monkeypatch.delenv(var, raising=False)
    cfg = main_mod._serve_config()
    assert cfg.db_url == "sqlite:///./forge.db"
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8041
    assert cfg.docs is False
    assert cfg.golden_root is None and cfg.report_root is None


def test_serve_config_env_overrides(main_mod, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("FORGE_DB_URL", "postgresql://forge_app:pw@aim-pg:5432/forge")
    monkeypatch.setenv("FORGE_HOST", "0.0.0.0")
    monkeypatch.setenv("FORGE_PORT", "9000")
    monkeypatch.setenv("FORGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FORGE_DOCS", "1")
    cfg = main_mod._serve_config()
    assert cfg.db_url == "postgresql://forge_app:pw@aim-pg:5432/forge"
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000
    assert cfg.docs is True
    assert cfg.golden_root == data_dir / "golden"
    assert cfg.report_root == data_dir / "reports"

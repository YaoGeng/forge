"""MS-3 T1 E2 客户端分发 feed（docs/18）：GET /api/v1/store/client JSON 与
GET /api/v1/store/client/latest.yml（electron-updater generic）。

sha512 口径钉死（风险 R5，非 runner 的 sha256）：
- JSON 出 sha512:<hex>（仿 runner_info_data 的 sha256:<hex> 房式）；
- latest.yml 出 base64 摘要（electron-updater 校验约定——hex 串会被按 base64
  解码，下载校验必败）；files[0].url 绝对路径 /download/...（updater 按
  feed 域 /api/v1/store/client/ 解析到站点根）。
未发布（无版本号 / dist 未落文件）→ 404 中文 detail。
"""
import base64
import hashlib

import yaml
from fastapi.testclient import TestClient

EXE_BYTES = b"fake-client-exe-bytes-0.2.0"
RELEASE_DATE = "2026-10-16T09:00:00Z"  # FrozenClock 缺省起点（conftest.START）+ Z


def _publish(api, tmp_path, version="0.2.0"):
    """仿 TestRunnerEndpoint：发布物落 dist、版本号注 state。"""
    (tmp_path / f"forge-client-{version}-win.exe").write_bytes(EXE_BYTES)
    api.app.state.dist_root = tmp_path
    api.app.state.client_version = version


class TestClientInfoJson:
    def test_shape_and_sha512_hex(self, api, tmp_path):
        _publish(api, tmp_path)
        r = api.client.get("/api/v1/store/client")
        assert r.status_code == 200
        assert r.json() == {
            "version": "0.2.0",
            "url": "/download/forge-client-0.2.0-win.exe",
            "sha512": "sha512:" + hashlib.sha512(EXE_BYTES).hexdigest(),
        }

    def test_unpublished_404_chinese(self, api):
        api.app.state.client_version = ""
        api.app.state.dist_root = None
        r = api.client.get("/api/v1/store/client")
        assert r.status_code == 404
        assert r.json()["detail"] == "客户端尚未发布"

    def test_version_set_but_file_missing_404(self, api, tmp_path):
        api.app.state.dist_root = tmp_path  # 空目录：dist 无该 exe
        api.app.state.client_version = "0.2.0"
        assert api.client.get("/api/v1/store/client").status_code == 404


class TestLatestYml:
    def test_electron_updater_schema(self, api, tmp_path):
        _publish(api, tmp_path)
        r = api.client.get("/api/v1/store/client/latest.yml")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/yaml")
        data = yaml.safe_load(r.text)
        digest = base64.b64encode(hashlib.sha512(EXE_BYTES).digest()).decode()
        assert data["version"] == "0.2.0"
        assert data["files"][0]["url"] == "/download/forge-client-0.2.0-win.exe"
        assert data["files"][0]["sha512"] == digest
        assert data["files"][0]["size"] == len(EXE_BYTES)
        assert data["path"] == "/download/forge-client-0.2.0-win.exe"
        assert data["sha512"] == digest
        assert data["releaseDate"] == RELEASE_DATE  # clock 冻结在 START

    def test_sha512_base64_decodes_to_file_digest(self, api, tmp_path):
        _publish(api, tmp_path, version="0.3.0")
        data = yaml.safe_load(
            api.client.get("/api/v1/store/client/latest.yml").text)
        assert base64.b64decode(data["files"][0]["sha512"]) == \
            hashlib.sha512(EXE_BYTES).digest()

    def test_unpublished_404_chinese(self, api):
        api.app.state.client_version = ""
        api.app.state.dist_root = None
        r = api.client.get("/api/v1/store/client/latest.yml")
        assert r.status_code == 404
        assert r.json()["detail"] == "客户端尚未发布"


def test_env_plumbing_client_version_and_dist(make_app, monkeypatch, tmp_path):
    """发布流 env 契约（docs/18 T5：.env 追加 FORGE_CLIENT_VERSION 仿
    FORGE_RUNNER_VERSION）：FORGE_CLIENT_VERSION/FORGE_DIST_DIR → state → 端点。"""
    (tmp_path / "forge-client-0.4.0-win.exe").write_bytes(EXE_BYTES)
    monkeypatch.setenv("FORGE_DIST_DIR", str(tmp_path))
    monkeypatch.setenv("FORGE_CLIENT_VERSION", "0.4.0")
    client = TestClient(make_app())
    r = client.get("/api/v1/store/client")
    assert r.status_code == 200
    assert r.json()["version"] == "0.4.0"
    assert r.json()["url"] == "/download/forge-client-0.4.0-win.exe"

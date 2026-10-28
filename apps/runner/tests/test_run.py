"""T2.12 执行流离线假件测试（docs/17）：acquire→验签→激活→执行→上报 + outbox 兜底。

真浏览器链路由本地 E2E 冒烟覆盖（证据 t2.12-smoke，CI deselect 惯例）。
"""
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from forge_runner import pkg, run as run_mod, state as state_mod
from forge_runner.client import ClientError

SITE_MAIN = (
    "def run(params):\n"
    "    return {'rows': 'a;b', 'q': params.get('q', '')}\n"
)
EXPORT_MAIN = (
    "def run(params):\n"
    "    return {'file': params.get('out', 'x.xlsx'), 'rows': params.get('rows')}\n"
)


def build_aapkg(key, *, composition=None, include_trace=False) -> tuple[bytes, str, str]:
    composition = composition or [
        {"block": "site_stub", "params": {"q": "python"}},
        {"block": "export", "params": {"out": "r.xlsx"},
         "bindings": {"rows": "site_stub.rows"}},
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("app.json", json.dumps(
            {"name": "demo_app", "version": "0.1.0", "composition": composition}))
        z.writestr("site_stub/block.yaml", "name: site_stub\nversion: 1.0.0")
        z.writestr("site_stub/main.py", SITE_MAIN)
        z.writestr("export/block.yaml", "name: export\nversion: 1.0.0")
        z.writestr("export/main.py", EXPORT_MAIN)
        if include_trace:
            z.writestr("site_stub/trace/manifest.yaml", "site: example.com\n")
            z.writestr("site_stub/script.py",
                       "def browse(port):\n    return {'rows': 'x;y'}\n")
    payload = buf.getvalue()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    sig = base64.b64encode(key.sign(digest.encode())).decode()
    return payload, digest, sig


class FlowClient:
    """脚本化假 client：按路径返回预设响应，记录全部调用。"""

    def __init__(self, key, *, report_error=False, entitlements=None):
        payload, digest, sig = build_aapkg(key, include_trace=False)
        self.aapkg = (payload, digest, sig)
        self.pubkey = base64.b64encode(
            key.public_key().public_bytes_raw()).decode()
        self.report_error = report_error
        self.entitlements = entitlements if entitlements is not None else []
        self.calls = []
        self.reports = []

    def get(self, path, token=None):
        self.calls.append(("GET", path))
        if path == "/api/v1/pubkey":
            return 200, {"pubkey": self.pubkey}
        if path == "/api/v1/me/entitlements":
            return 200, self.entitlements
        return 404, {"detail": "未脚本化"}

    def get_bytes(self, path, token=None):
        self.calls.append(("GET", path))
        payload, digest, sig = self.aapkg
        return 200, payload, {"x-forge-digest": digest, "x-forge-sig": sig}

    def post_json(self, path, body, token=None):
        self.calls.append(("POST", path, body))
        if path == "/api/v1/store/apps/demo_app/acquire":
            return 201, {"entitlement_id": 9}
        if path.startswith("/api/v1/entitlements/"):
            return 200, {"activated_at": "2026-10-26T12:00:00"}
        if path == "/api/v1/run-reports":
            if self.report_error:
                raise ClientError("无法连接服务器")
            self.reports.append(body)
            return 201, {"first_run": len(self.reports) == 1}
        return 404, {"detail": "未脚本化"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "fh"))
    return tmp_path / "fh"


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


class TestAppRun:
    def test_full_flow_offline(self, home, key):
        client = FlowClient(key)
        result = run_mod.app_run("demo_app", client, token="tok")
        assert result["ok"] is True
        assert result["first_run"] is True and result["report_queued"] is False
        assert result["context"]["export"]["rows"] == "a;b"  # 绑定传递真实生效
        # 全链调用次序：entitlements → (无既有) acquire → pubkey/package → activate → report
        posts = [c for c in client.calls if c[0] == "POST"]
        assert [p[1] for p in posts] == [
            "/api/v1/store/apps/demo_app/acquire",
            "/api/v1/entitlements/9/activate",
            "/api/v1/run-reports",
        ]
        assert client.reports[0]["entitlement_id"] == 9
        assert client.reports[0]["ok"] is True
        assert client.reports[0]["env_class"]  # 环境类如实上报
        assert client.reports[0]["failure_class"] is None

    def test_existing_entitlement_skips_acquire(self, home, key):
        client = FlowClient(key, entitlements=[
            {"entitlement_id": 5, "app": "demo_app", "version": "0.1.0",
             "activated_at": None, "source": "free_ms2",
             "acquired_at": "2026-10-26T00:00:00"}])
        run_mod.app_run("demo_app", client, token="tok")
        posts = [c[1] for c in client.calls if c[0] == "POST"]
        assert "/api/v1/store/apps/demo_app/acquire" not in posts
        assert "/api/v1/entitlements/5/activate" in posts

    def test_report_failure_queues_outbox_then_resends(self, home, key):
        client = FlowClient(key, report_error=True)
        result = run_mod.app_run("demo_app", client, token="tok")
        assert result["report_queued"] is True
        outbox = state_mod.home_dir() / "outbox"
        assert len(list(outbox.glob("*.json"))) == 1
        # 下一次运行（网络恢复）：先重发旧报告，再上报新报告
        client.report_error = False
        run_mod.app_run("demo_app", client, token="tok")
        assert len(list(outbox.glob("*.json"))) == 0
        assert len(client.reports) == 2  # 补报 1 + 新报 1

    def test_acquire_failure_raises_flow_error(self, home, key):
        client = FlowClient(key)
        client.post_json = lambda path, body, token=None: (403, {"detail": "应用不存在或未上架"}) \
            if "acquire" in path else FlowClient.post_json(client, path, body, token)
        with pytest.raises(run_mod.RunFlowError, match="应用不存在"):
            run_mod.app_run("demo_app", client, token="tok")

    def test_step_failure_reported_with_failure_class(self, home, key):
        payload_orig = build_aapkg  # 构造 export 块抛错的包
        key2 = key
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("app.json", json.dumps(
                {"name": "demo_app", "version": "0.1.0",
                 "composition": [{"block": "boom", "params": {}}]}))
            z.writestr("boom/block.yaml", "name: boom")
            z.writestr("boom/main.py", "def run(params):\n    raise ValueError('炸了')\n")
        payload = buf.getvalue()
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        sig = base64.b64encode(key2.sign(digest.encode())).decode()
        client = FlowClient(key2)
        client.aapkg = (payload, digest, sig)
        result = run_mod.app_run("demo_app", client, token="tok")
        assert result["ok"] is False
        assert client.reports[0]["ok"] is False
        assert client.reports[0]["failure_class"] == "env_error"


class TestBuildRoutes:
    def test_trace_block_detected_and_script_loaded(self, home, key, tmp_path):
        # 复用 include_trace 包验证：trace/manifest.yaml 存在 → 走 TraceBlockPort
        payload, digest, sig = build_aapkg(key, include_trace=True)
        import forge_runner.blocks as blocks_mod

        app_dir = state_mod.apps_dir() / "demo_app"
        # 手工解包（不经网络）
        app_dir.mkdir(parents=True)
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            z.extractall(app_dir)
        routes = blocks_mod.build_routes(app_dir, browser_factory=lambda: None)
        assert isinstance(routes["site_stub"][0], blocks_mod.TraceBlockPort)
        assert isinstance(routes["export"][0], blocks_mod.PythonBlockPort)
        browse = blocks_mod.load_script(app_dir / "site_stub")
        assert callable(browse)

    def test_missing_block_dir_raises(self, home, tmp_path):
        import forge_runner.blocks as blocks_mod

        d = tmp_path / "app"
        d.mkdir()
        (d / "app.json").write_text(json.dumps(
            {"composition": [{"block": "ghost", "params": {}}]}), encoding="utf-8")
        with pytest.raises(blocks_mod.BlockExecutionError, match="缺块目录"):
            blocks_mod.build_routes(d)

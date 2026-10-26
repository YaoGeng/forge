"""T2.04 积木代码包入库与 .aapkg 组装分发（docs/17，S-5 TOFU 签名）。

篡改必拒：摘要或签名不过即 403/拒收；无签名私钥 → 签名端点 503。
"""
import base64
import io
import json
import zipfile
from datetime import datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from forge_server.models import App, AppVersion, Block, BlockVersion

NOW = datetime(2026, 10, 26, 12, 0, 0)
PASSWORD = "correct-horse-42"


def _seed_block(s, name, version="1.0.0", level="C2"):
    block = Block(name=name, created_at=NOW)
    s.add(block)
    s.flush()
    s.add(BlockVersion(
        block_id=block.id, version=version, certification_level=level,
        reliability_json={"level": level, "n": 20, "live_pass_rate": 1.0,
                          "best_effort": False, "window_end": NOW.isoformat()},
        created_at=NOW,
    ))


def _seed_published_app(s, name="hn_weekly", blocks=("hn_search_probe", "excel_export")):
    app = App(name=name, title="HN 周报", created_at=NOW)
    s.add(app)
    s.flush()
    s.add(AppVersion(app_id=app.id, version="0.1.0", status="published",
                     composition_json=[{"block": b, "params": {}} for b in blocks],
                     created_at=NOW))
    return app


@pytest.fixture
def seeded(api):
    with api.app.state.session_factory() as s:
        _seed_block(s, "hn_search_probe")
        _seed_block(s, "excel_export")
        _seed_published_app(s)
        s.commit()
    return api


def _block_zip(name="hn_search_probe", version="1.0.0", entry="main.py",
               yaml_name=None, yaml_version=None, include_entry=True):
    yaml_name = yaml_name or name
    yaml_version = yaml_version or version
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{name}/block.yaml",
                   f"name: {yaml_name}\nversion: {yaml_version}\nruntime:\n"
                   f"  adapter: python\n  entry: {entry}\ntimeout_sec: 60\n")
        if include_entry:
            z.writestr(f"{name}/{entry}", "print('block')\n")
    return buf.getvalue()


def _login(api, email="a@example.com"):
    api.client.post("/api/v1/auth/register",
                    json={"email": email, "password": PASSWORD})
    token = api.client.post("/api/v1/auth/login",
                            json={"email": email, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _upload(client, name, version="1.0.0", content=None):
    return client.post(
        f"/api/v1/registry/blocks/{name}/versions/{version}/bundle",
        files={"file": (f"{name}.zip", content or _block_zip(name, version),
                        "application/zip")},
    )


class TestBundleUpload:
    def test_upload_records_digest(self, seeded):
        r = _upload(seeded.client, "hn_search_probe")
        assert r.status_code == 201
        body = r.json()
        assert body["code_digest"].startswith("sha256:")
        with seeded.app.state.session_factory() as s:
            bv = (s.query(BlockVersion).join(Block, BlockVersion.block_id == Block.id)
                  .filter(Block.name == "hn_search_probe").first())
            assert bv.code_digest == body["code_digest"]
            assert bv.code_bundle and bv.code_bundle.endswith("hn_search_probe-1.0.0.zip")

    def test_upload_idempotent_same_digest(self, seeded):
        _upload(seeded.client, "hn_search_probe")
        r = _upload(seeded.client, "hn_search_probe")
        assert r.status_code == 201

    def test_mismatched_name_422(self, seeded):
        r = _upload(seeded.client, "hn_search_probe",
                    content=_block_zip("hn_search_probe", yaml_name="other_block"))
        assert r.status_code == 422

    def test_missing_entry_422(self, seeded):
        r = _upload(seeded.client, "hn_search_probe",
                    content=_block_zip("hn_search_probe", include_entry=False))
        assert r.status_code == 422

    def test_unknown_block_404(self, seeded):
        assert _upload(seeded.client, "ghost_block").status_code == 404


class TestPackage:
    def _prepare(self, api, acquire=True):
        auth = _login(api)
        if acquire:
            api.client.post("/api/v1/store/apps/hn_weekly/acquire", headers=auth)
        return auth

    def test_package_assembles_and_signs(self, seeded):
        _upload(seeded.client, "hn_search_probe")
        _upload(seeded.client, "excel_export")
        auth = self._prepare(seeded)
        r = seeded.client.get("/api/v1/store/apps/hn_weekly/package", headers=auth)
        assert r.status_code == 200
        digest = r.headers["x-forge-digest"]
        assert digest.startswith("sha256:") and digest == r.headers.get("x-forge-digest")
        sig = r.headers["x-forge-sig"]
        import hashlib
        assert hashlib.sha256(r.content).hexdigest() == digest.split(":", 1)[1]
        # TOFU 公钥可独立验签
        pub_b64 = seeded.client.get("/api/v1/pubkey").json()["pubkey"]
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64)).verify(
            base64.b64decode(sig), digest.encode())
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names = set(z.namelist())
            assert "app.json" in names and "META/digests.json" in names
            assert "hn_search_probe/block.yaml" in names
            assert "excel_export/block.yaml" in names
            app_json = json.loads(z.read("app.json"))
            assert app_json["name"] == "hn_weekly"
            assert app_json["version"] == "0.1.0"
            assert len(app_json["composition"]) == 2
            digests = json.loads(z.read("META/digests.json"))
            assert "hn_search_probe" in digests and "excel_export" in digests

    def test_package_requires_acquisition_403(self, seeded):
        _upload(seeded.client, "hn_search_probe")
        _upload(seeded.client, "excel_export")
        auth = self._prepare(seeded, acquire=False)
        r = seeded.client.get("/api/v1/store/apps/hn_weekly/package", headers=auth)
        assert r.status_code == 403
        assert "获取" in r.json()["detail"]

    def test_package_unauthenticated_401(self, seeded, make_app):
        _upload(seeded.client, "hn_search_probe")
        _upload(seeded.client, "excel_export")
        fresh = TestClient(make_app())  # 无 Cookie 客户端（共享 client 带登录态）
        assert fresh.get("/api/v1/store/apps/hn_weekly/package").status_code == 401

    def test_package_missing_bundle_409(self, seeded):
        _upload(seeded.client, "hn_search_probe")  # excel_export 未上传
        auth = self._prepare(seeded)
        r = seeded.client.get("/api/v1/store/apps/hn_weekly/package", headers=auth)
        assert r.status_code == 409
        assert "excel_export" in r.json()["detail"]

    def test_signing_key_missing_503(self, api):
        api.app.state.forge_signing_key = None  # 模拟生产未注入
        with api.app.state.session_factory() as s:
            _seed_block(s, "hn_search_probe")
            _seed_block(s, "excel_export")
            _seed_published_app(s)
            s.commit()
        _upload(api.client, "hn_search_probe")
        _upload(api.client, "excel_export")
        auth = self._prepare(api)
        r = api.client.get("/api/v1/store/apps/hn_weekly/package", headers=auth)
        assert r.status_code == 503

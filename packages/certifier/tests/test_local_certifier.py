"""T1.32 用例矩阵：LocalCertifier 设备注册 + nonce + 本机 N 次 + ed25519 签名（M09 §3.2/§4/§6；C6/C7/C11/C13，G11）。

客户端经 ASGI 实物联测（TestClient 即 http 面，不起端口、不触外网）。
"""
import base64
import hashlib
import json
import re
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from fake_browser import FakeBrowser
from fastapi.testclient import TestClient

from forge_certifier.device import DeviceKey, register_device
from forge_certifier.nonce import fetch_nonce
from forge_certifier.certify import CertReportClient, canonical_json, certify
from forge_server.sandbox import RunOutcome

SERVER = "http://test"


class RecordingClient(TestClient):
    """捕获全部出站载荷（G11 扫描用）。"""

    def __init__(self, app):
        super().__init__(app)
        self.sent = []

    def post(self, url, **kw):
        self.sent.append((url, kw.get("json")))
        return super().post(url, **kw)


class FakeRunner:
    """假 RunnerPort：可注入失败；step_results 带页面内容字段（报告白名单的探针）。"""

    LEAK = "SECRET-PAGE-CONTENT"

    def __init__(self, fails=()):
        self.calls = 0
        self.fails = set(fails)

    def run_once(self, block_ref, params=None, *, mode="local", browser_factory=None):
        if browser_factory is not None:
            browser_factory()  # 真实 runner 在此创建一次性会话浏览器（C11）
        i = self.calls
        self.calls += 1
        ok = i not in self.fails
        return RunOutcome(
            mode=mode,
            ok=ok,
            failure_class=None if ok else "selector_missing",
            step_results=(
                {
                    "seq": 1,
                    "action": "nav",
                    "ok": ok,
                    "anchor_matched": ok,
                    "snapshot_digest": "deadbeef",
                    "duration_ms": 7,
                    "page_text": self.LEAK,
                },
            ),
        )


def make_certify_env(make_app, *, runner=None, fails=()):
    app = make_app()
    client = RecordingClient(app)
    key = DeviceKey.generate()
    device_id = register_device(client, SERVER, "creator-t132", key)
    runner = runner or FakeRunner(fails=fails)
    profiles = []

    def factory(profile_dir):
        profiles.append((str(profile_dir), Path(profile_dir).exists()))
        return FakeBrowser()

    return app, client, key, device_id, runner, factory, profiles


# --- 设备面 -------------------------------------------------------------------------


def test_device_register_roundtrip(make_app):
    _, client, key, device_id, *_ = make_certify_env(make_app)
    again = register_device(client, SERVER, "creator-t132", key)
    assert device_id > 0
    assert again == device_id  # 重复注册幂等（同 device_id）


def test_device_cap_per_creator(make_app):
    app = make_app()
    client = RecordingClient(app)
    keys = [DeviceKey.generate() for _ in range(4)]
    for k in keys[:3]:
        assert register_device(client, SERVER, "creator-cap", k) > 0
    r = client.post(
        "/api/v1/certifications/devices",
        json={
            "creator_id": "creator-cap",
            "public_key": keys[3].public_key_pem,
            "device_fp": keys[3].device_fp,
        },
    )
    assert r.status_code == 409  # 上限 3（M09 §6 多设备分流对策）


def test_nonce_single_issue_and_ttl(make_app, clock):
    app = make_app()
    client = RecordingClient(app)
    key = DeviceKey.generate()
    register_device(client, SERVER, "creator-nonce", key)

    n1 = fetch_nonce(client, SERVER, key.device_fp)
    n2 = fetch_nonce(client, SERVER, key.device_fp)
    assert n1["nonce"] != n2["nonce"]  # 二取为新 nonce
    assert n1["expires_at"] == (clock.now() + _ttl()).isoformat()

    assert app.state.nonces.consume(n1["nonce"]) == key.device_fp  # 未过期可用
    clock.advance(minutes=6)
    assert app.state.nonces.consume(n2["nonce"]) is None  # 5min TTL 过期（FrozenClock）


def _ttl():
    from forge_server.api_devices import NONCE_TTL_S

    import datetime as dt

    return dt.timedelta(seconds=NONCE_TTL_S)


# --- certify 主链 ---------------------------------------------------------------------


def test_certify_produces_signed_report(make_app):
    _, client, key, _, runner, factory, _ = make_certify_env(make_app)
    signed = certify(
        "probe-trace",
        3,
        {"q": "hello"},
        device_key=key,
        server_base=SERVER,
        browser_factory=factory,
        runner=runner,
        http=client,
    )

    assert len(signed.report["runs"]) == 3 and all(r["ok"] for r in signed.report["runs"])
    assert runner.calls == 3
    # C7 逐字：{nonce, report_hash, env_fingerprint, client_version, ts}
    assert set(signed.attestation) == {
        "nonce",
        "report_hash",
        "env_fingerprint",
        "client_version",
        "ts",
    }
    # C7：report_hash = sha256(canonical_json(report))[:16]
    assert (
        hashlib.sha256(canonical_json(signed.report)).hexdigest()[:16]
        == signed.attestation["report_hash"]
    )
    # 签名可由注册公钥验证（覆盖 attestation 全量）
    pub = serialization.load_pem_public_key(key.public_key_pem.encode("utf-8"))
    pub.verify(signed.signature, canonical_json(signed.attestation))  # 验签失败即抛异常

    n1 = fetch_nonce(client, SERVER, key.device_fp)
    assert n1["nonce"] != signed.attestation["nonce"]  # 报告用的 nonce 与后续领取互不影响


def test_session_profile_ephemeral(make_app):
    _, client, key, _, runner, factory, profiles = make_certify_env(make_app)
    certify(
        "probe-trace",
        3,
        {},
        device_key=key,
        server_base=SERVER,
        browser_factory=factory,
        runner=runner,
        http=client,
    )
    assert len(profiles) == 3
    assert all(exists for _, exists in profiles)  # 运行中 profile 目录存在
    assert all(not Path(d).exists() for d, _ in profiles)  # 结束后即焚（C11）


def test_report_excludes_page_content(make_app):
    _, client, key, _, runner, factory, _ = make_certify_env(make_app)
    signed = certify(
        "probe-trace",
        2,
        {},
        device_key=key,
        server_base=SERVER,
        browser_factory=factory,
        runner=runner,
        http=client,
    )
    text = json.dumps(signed.payload(), ensure_ascii=False)
    assert FakeRunner.LEAK not in text  # 页面内容不进报告（M09 §3.2）
    assert "snapshot_digest" not in text  # 白名单外字段一律不透传
    assert all(set(r) == {"index", "ok", "failure_class"} for r in signed.report["runs"])


def test_env_fingerprint_shape(make_app):
    _, client, key, _, runner, factory, _ = make_certify_env(make_app)
    signed = certify(
        "probe-trace",
        1,
        {},
        device_key=key,
        server_base=SERVER,
        browser_factory=factory,
        runner=runner,
        http=client,
    )
    assert re.fullmatch(r"[0-9a-f]{16}", signed.attestation["env_fingerprint"])  # C13


def test_private_key_never_leaves_client(make_app):
    _, client, key, _, runner, factory, _ = make_certify_env(make_app)
    certify(
        "probe-trace",
        1,
        {},
        device_key=key,
        server_base=SERVER,
        browser_factory=factory,
        runner=runner,
        http=client,
    )
    secret = key._private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    marks = {
        secret.hex(),
        base64.b64encode(secret).decode(),
        "PRIVATE KEY",
    }
    for url, payload in client.sent:  # 全部出站载荷扫描（G11）
        text = json.dumps(payload, ensure_ascii=False)
        for m in marks:
            assert m not in text, f"{url} 泄漏 {m[:24]}"

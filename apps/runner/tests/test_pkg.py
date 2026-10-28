"""T2.11 .aapkg 下载验签解包（docs/17）：TOFU 钉扎；篡改必拒；路径穿越必拒。"""
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from forge_runner import pkg
from forge_runner.client import ClientError


def make_aapkg(key: Ed25519PrivateKey, *, app="hn_weekly", tamper=False,
               extra_entry=None) -> tuple[bytes, str, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("app.json", json.dumps(
            {"name": app, "version": "0.1.0", "composition": [], "created_at": "x"}))
        z.writestr("hn_search_probe/block.yaml", "name: hn_search_probe")
        if extra_entry:
            z.writestr(extra_entry, "evil")
    payload = buf.getvalue()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    sig = base64.b64encode(key.sign(digest.encode())).decode()
    if tamper:  # 篡改发生在摘要/签名定格之后——模拟传输替换
        payload = payload[:-1] + bytes([payload[-1] ^ 0xFF])
    return payload, digest, sig


class FakeClient:
    def __init__(self, status=200, payload=b"", digest="", sig="", pubkey_b64="",
                 get_error=None):
        self.status, self.payload, self.digest, self.sig = status, payload, digest, sig
        self.pubkey_b64 = pubkey_b64
        self.get_error = get_error
        self.downloads = 0

    def get_bytes(self, path, token=None):
        self.downloads += 1
        if self.get_error:
            raise self.get_error
        return self.status, self.payload, {
            "x-forge-digest": self.digest, "x-forge-sig": self.sig}

    def get(self, path, token=None):
        return 200, {"pubkey": self.pubkey_b64}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "fh"))
    return tmp_path / "fh"


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


def _pubkey_b64(key) -> str:
    return base64.b64encode(key.public_key().public_bytes_raw()).decode()


class TestFetchAndUnpack:
    def test_happy_path_unpacks_and_pins(self, home, key):
        payload, digest, sig = make_aapkg(key)
        client = FakeClient(payload=payload, digest=digest, sig=sig,
                            pubkey_b64=_pubkey_b64(key))
        dest = pkg.fetch_and_unpack("hn_weekly", client, token="tok")
        assert (dest / "app.json").exists()
        assert (dest / "hn_search_probe" / "block.yaml").exists()
        marker = json.loads((dest / ".installed.json").read_text(encoding="utf-8"))
        assert marker["digest"] == digest
        from forge_runner import state as state_mod
        assert state_mod.load()["pubkey"] == _pubkey_b64(key)

    def test_repeat_same_digest_skips_unpack(self, home, key):
        payload, digest, sig = make_aapkg(key)
        client = FakeClient(payload=payload, digest=digest, sig=sig,
                            pubkey_b64=_pubkey_b64(key))
        pkg.fetch_and_unpack("hn_weekly", client, token="tok")
        sentinel = pkg.fetch_and_unpack("hn_weekly", client, token="tok")
        assert client.downloads == 2  # 下载总发生（无前置摘要端点），解包按 marker 跳过
        assert sentinel.exists()

    def test_tampered_bytes_rejected(self, home, key):
        payload, digest, sig = make_aapkg(key, tamper=True)
        client = FakeClient(payload=payload, digest=digest, sig=sig,
                            pubkey_b64=_pubkey_b64(key))
        with pytest.raises(pkg.PkgError, match="摘要"):
            pkg.fetch_and_unpack("hn_weekly", client, token="tok")

    def test_wrong_signature_rejected(self, home, key):
        payload, digest, _sig = make_aapkg(key)
        other = Ed25519PrivateKey.generate()
        sig = base64.b64encode(other.sign(digest.encode())).decode()
        client = FakeClient(payload=payload, digest=digest, sig=sig,
                            pubkey_b64=_pubkey_b64(key))
        with pytest.raises(pkg.PkgError, match="签名"):
            pkg.fetch_and_unpack("hn_weekly", client, token="tok")

    def test_server_pubkey_change_refused_pin_kept(self, home, key):
        payload, digest, sig = make_aapkg(key)
        client = FakeClient(payload=payload, digest=digest, sig=sig,
                            pubkey_b64=_pubkey_b64(key))
        pkg.fetch_and_unpack("hn_weekly", client, token="tok")  # 首次钉扎
        new_key = Ed25519PrivateKey.generate()
        payload2, digest2, sig2 = make_aapkg(new_key)
        client2 = FakeClient(payload=payload2, digest=digest2, sig=sig2,
                             pubkey_b64=_pubkey_b64(new_key))
        with pytest.raises(pkg.PkgError, match="公钥变更"):
            pkg.fetch_and_unpack("hn_weekly", client2, token="tok")
        from forge_runner import state as state_mod
        assert state_mod.load()["pubkey"] == _pubkey_b64(key)  # 钉扎未被覆盖

    def test_path_traversal_entry_rejected(self, home, key):
        payload, digest, sig = make_aapkg(key, extra_entry="../evil.txt")
        client = FakeClient(payload=payload, digest=digest, sig=sig,
                            pubkey_b64=_pubkey_b64(key))
        with pytest.raises(pkg.PkgError, match="路径"):
            pkg.fetch_and_unpack("hn_weekly", client, token="tok")
        assert not (home.parent / "evil.txt").exists()

    def test_http_error_raises_pkg_error(self, home, key):
        client = FakeClient(status=403,
                            payload='{"detail":"请先获取该应用"}'.encode("utf-8"),
                            pubkey_b64=_pubkey_b64(key))
        with pytest.raises(pkg.PkgError, match="请先获取该应用"):
            pkg.fetch_and_unpack("hn_weekly", client, token="tok")

    def test_network_error_wrapped(self, home, key):
        client = FakeClient(get_error=ClientError("无法连接服务器"),
                            pubkey_b64=_pubkey_b64(key))
        with pytest.raises(ClientError):
            pkg.fetch_and_unpack("hn_weekly", client, token="tok")


class TestVerifyUnit:
    def test_verify_ok_and_bad_digest(self, key):
        payload, digest, sig = make_aapkg(key)
        pkg.verify(payload, digest, sig, key.public_key().public_bytes_raw())
        with pytest.raises(pkg.PkgError):
            pkg.verify(payload + b"x", digest, sig,
                       key.public_key().public_bytes_raw())

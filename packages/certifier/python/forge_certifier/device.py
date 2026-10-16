"""DeviceKey：ed25519 密钥生成/加载与设备注册（G11：私钥仅存本机目录）。"""
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_FILE = "device_key.pem"


class DeviceKey:
    def __init__(self, private: Ed25519PrivateKey):
        self._private = private

    @classmethod
    def generate(cls) -> "DeviceKey":
        return cls(Ed25519PrivateKey.generate())

    def save(self, dir_path: str | Path) -> Path:
        """私钥仅落本机目录（0600 语义；Windows 无 POSIX 权限位，尽力 chmod）。"""
        d = Path(dir_path)
        d.mkdir(parents=True, exist_ok=True)
        pem = self._private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        path = d / KEY_FILE
        path.write_bytes(pem)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    @classmethod
    def load(cls, dir_path: str | Path) -> "DeviceKey":
        path = Path(dir_path) / KEY_FILE
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("设备密钥须为 ed25519")
        return cls(key)

    @property
    def public_key_pem(self) -> str:
        return (
            self._private.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("utf-8")
        )

    @property
    def device_fp(self) -> str:
        raw = self._private.public_key().public_bytes_raw()
        return hashlib.sha256(raw).hexdigest()[:16]

    def sign(self, data: bytes) -> bytes:
        return self._private.sign(data)


def register_device(http, server_base: str, creator_id: str, key: DeviceKey) -> int:
    """设备注册（幂等：同 creator+公钥返回同 device_id；被拒时 raise）。"""
    r = http.post(
        f"{server_base}/api/v1/certifications/devices",
        json={
            "creator_id": creator_id,
            "public_key": key.public_key_pem,
            "device_fp": key.device_fp,
        },
    )
    if r.status_code != 201:
        raise RuntimeError(f"设备注册被拒：{r.status_code} {r.text}")
    return int(r.json()["device_id"])

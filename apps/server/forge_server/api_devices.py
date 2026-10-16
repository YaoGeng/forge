"""C1 设备面：注册（幂等 + 同账号上限 3，M09 §6）与 nonce 一次性存储（C6）。"""
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .models import ClientDevice

NONCE_TTL_S = 300
MAX_DEVICES_PER_CREATOR = 3


class DeviceRegister(BaseModel):
    creator_id: str
    public_key: str
    device_fp: str


class NonceRequest(BaseModel):
    device_fp: str


class NonceStore:
    """服务端内存一次性 nonce 存储（D-M1E.1 载体；M11 复用同一实例）。

    单次消费即弹出；TTL 由注入时钟判定；属主绑定 device_fp。
    """

    def __init__(self, clock):
        self._clock = clock
        self._entries: dict[str, dict] = {}

    def issue(self, device_fp: str) -> tuple[str, str]:
        nonce = uuid.uuid4().hex
        expires = self._clock.now() + timedelta(seconds=NONCE_TTL_S)
        self._entries[nonce] = {"device_fp": device_fp, "expires_at": expires}
        return nonce, expires.isoformat()

    def consume(self, nonce: str) -> str | None:
        """单次消费：返回属主 device_fp；不存在/已过期返回 None。"""
        entry = self._entries.pop(nonce, None)
        if entry is None:
            return None
        if self._clock.now() >= entry["expires_at"]:
            return None
        return entry["device_fp"]


def register_device_routes(app):
    @app.post("/api/v1/certifications/devices", status_code=201)
    def register_device(body: DeviceRegister):
        with app.state.session_factory() as s:
            existing = s.execute(
                select(ClientDevice).where(
                    ClientDevice.creator_id == body.creator_id,
                    ClientDevice.public_key == body.public_key,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return {"device_id": existing.id}
            count = len(
                s.execute(
                    select(ClientDevice.id).where(ClientDevice.creator_id == body.creator_id)
                ).all()
            )
            if count >= MAX_DEVICES_PER_CREATOR:
                raise HTTPException(status_code=409, detail="device cap reached")
            row = ClientDevice(
                creator_id=body.creator_id,
                public_key=body.public_key,
                device_fp=body.device_fp,
                registered_at=app.state.clock.now(),
            )
            s.add(row)
            s.commit()
            return {"device_id": row.id}

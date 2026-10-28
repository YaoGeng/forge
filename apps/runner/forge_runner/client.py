"""HTTP 客户端（docs/17 T2.10）：stdlib urllib，零依赖（patchright 除外全 stdlib）。

base_url：FORGE_SERVER 覆盖（本地联调指向 http://127.0.0.1:8041），
缺省 https://forge.aim8848.com。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE = "https://forge.aim8848.com"
_TIMEOUT_S = 60


class ClientError(Exception):
    """网络/协议层错误（中文可读）。"""


class Client:
    def __init__(self, base_url: str | None = None):
        self.base = (base_url or os.environ.get("FORGE_SERVER") or DEFAULT_BASE).rstrip("/")

    def _request(self, path: str, *, method: str, body: bytes | None,
                 token: str | None, content_type: str | None):
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, data=body, method=method,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, OSError) as exc:
            raise ClientError(f"无法连接服务器（{self.base}）：{exc}") from exc

    def get(self, path: str, token: str | None = None) -> tuple[int, object]:
        status, raw = self._request(path, method="GET", body=None, token=token,
                                    content_type=None)
        return status, _decode(raw)

    def post_json(self, path: str, body: dict,
                  token: str | None = None) -> tuple[int, object]:
        status, raw = self._request(
            path, method="POST", body=json.dumps(body).encode(),
            token=token, content_type="application/json")
        return status, _decode(raw)

    def get_bytes(self, path: str, token: str | None = None) -> tuple[int, bytes, dict]:
        """下载用：返回 (status, body, headers小写键)。"""
        headers = {"Accept": "application/zip"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                return resp.status, resp.read(), {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), {k.lower(): v for k, v in exc.headers.items()}
        except (urllib.error.URLError, OSError) as exc:
            raise ClientError(f"无法连接服务器（{self.base}）：{exc}") from exc


def _decode(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return raw

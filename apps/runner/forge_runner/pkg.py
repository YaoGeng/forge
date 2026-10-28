"""T2.11 .aapkg 下载/验签/解包（docs/17，S-5 TOFU ed25519）。

TOFU：state 无 pubkey → 首次从 /api/v1/pubkey 取并钉扎；已钉扎且服务器返回
不同的钥 → 拒绝并保留原钉扎（不静默换钥）。篡改必拒：摘要或签名不过即 PkgError。
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import state as state_mod


class PkgError(Exception):
    """包获取/验签/解包失败（中文可读）。"""


def verify(zip_bytes: bytes, digest_header: str, sig_header: str,
           pinned_pubkey: bytes) -> None:
    """摘要与 ed25519 签名任一不过即抛 PkgError。"""
    algo, _, hex_digest = (digest_header or "").partition(":")
    if algo != "sha256" or not hex_digest:
        raise PkgError("响应缺少合法的 X-Forge-Digest 摘要头")
    actual = hashlib.sha256(zip_bytes).hexdigest()
    if actual != hex_digest:
        raise PkgError("包摘要不匹配（内容被篡改或传输损坏），拒绝执行")
    try:
        sig = base64.b64decode(sig_header or "")
        Ed25519PublicKey.from_public_bytes(pinned_pubkey).verify(
            sig, digest_header.encode())
    except Exception as exc:  # noqa: BLE001 —— 验签失败统一口径
        raise PkgError(f"包签名校验失败：{exc}") from exc


def _resolve_pubkey(client) -> str:
    """TOFU：state 钉扎优先；首次从服务器取并落钉扎；变更即拒。"""
    st = state_mod.load()
    pinned = st.get("pubkey")
    status, body = client.get("/api/v1/pubkey")
    server = (body or {}).get("pubkey") if isinstance(body, dict) else None
    if status != 200 or not server:
        raise PkgError(f"获取服务器公钥失败（HTTP {status}）")
    if pinned is None:
        st["pubkey"] = server
        state_mod.save(st)
        return server
    if pinned != server:
        raise PkgError(
            "服务器公钥变更，拒绝继续——请人工核实（防中间人替换），钉扎未改动")
    return pinned


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest_resolved = dest.resolve()
    for entry in zf.namelist():
        p = (dest / entry).resolve()
        if not str(p).startswith(str(dest_resolved)):
            raise PkgError(f"包内含路径穿越条目，拒绝解包：{entry}")
    zf.extractall(dest)


def fetch_and_unpack(app_name: str, client, token: str) -> Path:
    """下载 .aapkg → 验签 → 安全解包到 ~/.forge/apps/<name>/（同摘要跳过解包）。"""
    pubkey = _resolve_pubkey(client)
    status, payload, headers = client.get_bytes(
        f"/api/v1/store/apps/{app_name}/package", token=token)
    if status != 200:
        detail = ""
        try:
            detail = json.loads(payload.decode("utf-8")).get("detail", "")
        except Exception:  # noqa: BLE001 —— 非 JSON 错误体
            pass
        raise PkgError(detail or f"下载应用包失败（HTTP {status}）")
    digest = headers.get("x-forge-digest", "")
    sig = headers.get("x-forge-sig", "")
    verify(payload, digest, sig, base64.b64decode(pubkey))

    dest = state_mod.apps_dir() / app_name
    marker = dest / ".installed.json"
    if marker.exists():
        try:
            if json.loads(marker.read_text(encoding="utf-8")).get("digest") == digest:
                return dest  # 幂等：同版本已装，跳过解包
        except Exception:  # noqa: BLE001 —— 损坏 marker 视为未装
            pass
    if dest.exists():
        shutil.rmtree(dest)  # 换版本：整目录替换，不残留旧块
    dest.mkdir(parents=True)
    import io

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        _safe_extract(zf, dest)
    (dest / ".installed.json").write_text(
        json.dumps({"digest": digest, "at": _now_iso()}), encoding="utf-8")
    return dest


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")

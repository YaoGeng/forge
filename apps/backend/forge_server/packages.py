"""MS-2 积木代码包入库与 .aapkg 组装分发（docs/17 T2.04，S-5 TOFU ed25519）。

口径：对 .aapkg 全文件 sha256 摘要后 ed25519 签名（收款前升级双级签名——顺延清单）。
私钥：FORGE_SIGNING_KEY（base64 32B 种子）；未注入且未显式传参 → 生成临时钥并告警
（仅开发/测试；显式置 None → 签名端点 503）。
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import zipfile
from pathlib import Path

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from .auth import current_user
from .models import App, AppVersion, Block, BlockVersion, Entitlement

_LOG = logging.getLogger(__name__)


def _now(request: Request):
    return request.app.state.clock.now()


def _signing_key(request: Request) -> Ed25519PrivateKey | None:
    raw = getattr(request.app.state, "forge_signing_key", None)
    if raw is None:
        return None
    return Ed25519PrivateKey.from_private_bytes(raw)


def _find_version(s, name: str, version: str) -> BlockVersion:
    block = s.query(Block).filter_by(name=name).first()
    if block is None:
        raise HTTPException(status_code=404, detail="积木不存在")
    bv = s.query(BlockVersion).filter_by(block_id=block.id, version=version).first()
    if bv is None:
        raise HTTPException(status_code=404, detail="积木版本不存在")
    return bv


def _validate_bundle(name: str, version: str, content: bytes) -> None:
    """block.yaml 的 name/version 与路径一致、runtime.entry 指向的文件在包内。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="上传内容不是合法 zip")
    names = set(zf.namelist())
    yaml_path = f"{name}/block.yaml"
    if yaml_path not in names:
        raise HTTPException(status_code=422, detail=f"包内缺 {yaml_path}")
    try:
        meta = yaml.safe_load(zf.read(yaml_path)) or {}
        entry = ((meta.get("runtime") or {}).get("entry"))
    except yaml.YAMLError:
        raise HTTPException(status_code=422, detail="block.yaml 解析失败")
    if meta.get("name") != name or meta.get("version") != version:
        raise HTTPException(
            status_code=422,
            detail=f"block.yaml 名称/版本（{meta.get('name')}/{meta.get('version')}）"
                   f"与路径（{name}/{version}）不一致")
    if not entry or f"{name}/{entry}" not in names:
        raise HTTPException(status_code=422, detail=f"包内缺 runtime.entry 文件 {entry}")


def register_package_routes(app) -> None:
    router = APIRouter(tags=["packages"])

    @router.post("/api/v1/registry/blocks/{name}/versions/{version}/bundle",
                 status_code=201)
    def upload_bundle(name: str, version: str, request: Request,
                      file: UploadFile = File(...)):
        """平台侧代码包入库（/api/v1/registry 为 nginx Basic Auth 域）。幂等：
        重复上传同内容覆盖存储、刷新 digest。"""
        content = file.file.read()
        _validate_bundle(name, version, content)
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        root: Path = request.app.state.bundles_root
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{name}-{version}.zip").write_bytes(content)
        with request.app.state.session_factory() as s:
            bv = _find_version(s, name, version)
            bv.code_digest = digest
            bv.code_bundle = f"{name}-{version}.zip"
            s.commit()
        return {"code_digest": digest}

    @router.get("/api/v1/pubkey")
    def pubkey(request: Request):
        key = _signing_key(request)
        if key is None:
            raise HTTPException(status_code=503, detail="签名密钥未配置")
        return {"pubkey": base64.b64encode(
            key.public_key().public_bytes_raw()).decode()}

    @router.get("/api/v1/store/apps/{app_name}/package")
    def app_package(app_name: str, request: Request):
        """下载 .aapkg（需登录且已获取）。响应头带摘要与 ed25519 签名（TOFU）。"""
        user = current_user(request)
        with request.app.state.session_factory() as s:
            app_row = s.query(App).filter_by(name=app_name).first()
            av = None
            if app_row is not None:
                av = (s.query(AppVersion)
                      .filter_by(app_id=app_row.id, status="published")
                      .order_by(AppVersion.id.desc()).first())
            if app_row is None or av is None:
                raise HTTPException(status_code=404, detail="应用不存在或未上架")
            if s.query(Entitlement).filter_by(
                    user_id=user.id, app_name=app_name).first() is None:
                raise HTTPException(status_code=403, detail="请先获取该应用")

            root: Path = request.app.state.bundles_root
            buf = io.BytesIO()
            digests: dict[str, str] = {}
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("app.json", json.dumps({
                    "name": app_row.name, "version": av.version,
                    "composition": av.composition_json,
                    "created_at": _now(request).isoformat(),
                }, ensure_ascii=False))
                for step in av.composition_json or []:
                    bname = step.get("block")
                    if not bname:
                        continue
                    block = s.query(Block).filter_by(name=bname).first()
                    bv = None
                    if block is not None:
                        bv = (s.query(BlockVersion)
                              .filter_by(block_id=block.id)
                              .order_by(BlockVersion.id.desc()).first())
                    if bv is None or not bv.code_digest or not bv.code_bundle:
                        raise HTTPException(
                            status_code=409, detail=f"块 {bname} 未上传代码包")
                    with zipfile.ZipFile(root / bv.code_bundle) as bz:
                        for entry in bz.namelist():
                            z.writestr(entry, bz.read(entry))
                    digests[bname] = bv.code_digest
                z.writestr("META/digests.json",
                           json.dumps(digests, ensure_ascii=False))

        key = _signing_key(request)
        if key is None:
            raise HTTPException(status_code=503, detail="签名密钥未配置")
        payload = buf.getvalue()
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        sig = base64.b64encode(key.sign(digest.encode())).decode()
        from fastapi.responses import Response as RawResponse
        return RawResponse(
            content=payload, media_type="application/zip",
            headers={"X-Forge-Digest": digest, "X-Forge-Sig": sig})

    app.include_router(router)


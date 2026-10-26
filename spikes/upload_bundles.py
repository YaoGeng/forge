"""T2.04 平台侧代码包灌库（docs/17）。

用法：
  本地校验（不起服务）：python spikes/upload_bundles.py --local-check
    —— 把 spikes/seed_blocks 每块按服务端同款校验（block.yaml 一致性/entry 存在）打包验证。
  灌库（对已部署服务）：python spikes/upload_bundles.py --base http://127.0.0.1:8041 [--basic user:pass]
    —— /api/v1/registry 为 Basic Auth 域；幂等（重复上传覆盖刷新 digest）。
生产积木注册数据在 PG（MS-1F 26 块），灌库在生产部署后执行（T2.22）。
"""
from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "apps" / "server"))
SEED = _ROOT / "spikes" / "seed_blocks"


def block_dirs() -> list[tuple[str, str, Path]]:
    """(name, version, dir)——仅含 block.yaml 的目录。"""
    out = []
    for d in sorted(SEED.iterdir()):
        if not d.is_dir() or not (d / "block.yaml").exists():
            continue
        meta = yaml.safe_load((d / "block.yaml").read_text(encoding="utf-8")) or {}
        out.append((str(meta.get("name")), str(meta.get("version")), d))
    return out


def zip_block(name: str, d: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in sorted(d.rglob("*")):
            if f.is_file():
                z.writestr(f"{name}/{f.relative_to(d).as_posix()}", f.read_bytes())
    return buf.getvalue()


def local_check() -> int:
    from forge_server.packages import _validate_bundle

    ok = fail = 0
    for name, version, d in block_dirs():
        try:
            _validate_bundle(name, version, zip_block(name, d))
            ok += 1
        except Exception as exc:  # noqa: BLE001 —— 校验失败即报告
            fail += 1
            print(f"FAIL {name}-{version}: {exc}")
    print(f"local-check: {ok} ok / {fail} fail (共 {ok + fail} 块)")
    return 1 if fail else 0


def upload(base: str, basic: str | None) -> int:
    import base64
    import hashlib
    import secrets

    headers = {}
    if basic:
        headers["Authorization"] = "Basic " + base64.b64encode(
            basic.encode()).decode()
    ok = fail = 0
    for name, version, d in block_dirs():
        content = zip_block(name, d)
        boundary = "----forge" + secrets.token_hex(8)
        body = (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{name}.zip"\r\n'
                f"Content-Type: application/zip\r\n\r\n").encode() + content + \
            f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{base}/api/v1/registry/blocks/{name}/versions/{version}/bundle",
            data=body, method="POST", headers={
                **headers,
                "Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req) as resp:
                assert resp.status == 201, resp.status
                payload = resp.read().decode()
                digest = "sha256:" + hashlib.sha256(content).hexdigest()
                assert digest in payload, payload
                ok += 1
                print(f"ok {name}-{version} -> {digest[:20]}…")
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"FAIL {name}-{version}: {exc}")
    print(f"upload: {ok} ok / {fail} fail")
    return 1 if fail else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--local-check":
        raise SystemExit(local_check())
    base = "http://127.0.0.1:8041"
    basic = None
    if "--base" in args:
        base = args[args.index("--base") + 1]
    if "--basic" in args:
        basic = args[args.index("--basic") + 1]
    raise SystemExit(upload(base, basic))

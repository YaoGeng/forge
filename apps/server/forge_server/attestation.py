"""C1 报告初验：ed25519 验签 + 时长下限（M09 §3.2/§6；C7）。常量无配置入口。"""
import base64
import hashlib
import json

from cryptography.hazmat.primitives import serialization

MIN_RUN_SECONDS = 5  # 时长下限（每 run）；取宽值防误拒真报告（docs/12 §7）


def canonical_json(obj) -> bytes:
    """canonical：键排序、无空白（与 C7 report_hash 同规范；服务端独立实现）。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def report_hash(report: dict) -> str:
    return hashlib.sha256(canonical_json(report)).hexdigest()[:16]


def verify(attestation: dict, signature_b64: str, public_key_pem: str) -> bool:
    """ed25519 验签：签名覆盖 attestation 全量（含 nonce 与 report_hash）。"""
    try:
        pub = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        pub.verify(base64.b64decode(signature_b64), canonical_json(attestation))
        return True
    except Exception:
        return False


def duration_floor_ok(durations, n: int) -> bool:
    """时长下限：逐 run 计，总时长 < N×MIN_RUN_SECONDS 判伪运行。"""
    if not isinstance(durations, list) or len(durations) != n:
        return False
    try:
        total_ms = sum(int(d) for d in durations)
    except (TypeError, ValueError):
        return False
    return total_ms >= n * MIN_RUN_SECONDS * 1000

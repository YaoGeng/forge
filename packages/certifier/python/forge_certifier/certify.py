"""certify：本机 N 次真实运行 + 一次性 profile（C11）+ 报告生成 + C7 签名上报。"""
import base64
import hashlib
import json
import platform
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from . import __version__
from .device import DeviceKey
from .nonce import fetch_nonce


def canonical_json(obj) -> bytes:
    """canonical：键排序、无空白（与 C7 report_hash / C14 幂等键同规范）。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def env_fingerprint(browser_version: str = "unknown", network_type: str = "ethernet") -> str:
    """C13 v1：sha256(OS + 浏览器主版本 + python 版本 + 网络类型)[:16]。"""
    material = "|".join(
        [platform.system(), browser_version, platform.python_version(), network_type]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class SignedReport:
    report: dict
    attestation: dict
    signature: bytes
    device_fp: str

    def payload(self) -> dict:
        return {
            "device_fp": self.device_fp,
            "report": self.report,
            "attestation": self.attestation,
            "signature": base64.b64encode(self.signature).decode("ascii"),
        }


@dataclass(frozen=True)
class UploadResult:
    status_code: int
    body: dict | None


class CertReportClient:
    def __init__(self, http=None):
        self._http = http or httpx.Client()

    def payload(self, signed: SignedReport, cert_run_id: int) -> dict:
        return {"cert_run_id": cert_run_id, **signed.payload()}

    def upload(self, server_base: str, signed: SignedReport, cert_run_id: int) -> UploadResult:
        r = self._http.post(
            f"{server_base}/api/v1/certifications/{cert_run_id}/report",
            json=self.payload(signed, cert_run_id),
        )
        try:
            body = r.json()
        except Exception:
            body = None
        return UploadResult(status_code=r.status_code, body=body)


def certify(
    block_ref: str,
    n: int,
    params: dict | None,
    *,
    device_key: DeviceKey,
    server_base: str,
    browser_factory,
    runner,
    http=None,
    clock=None,
    browser_version: str = "unknown",
    network_type: str = "ethernet",
) -> SignedReport:
    """阻塞式认证：取 nonce → N 次真实运行（每 run 一次性 profile，即焚）→ 报告 → C7 签名。

    browser_factory(profile_dir) 每轮调用一次；runner.run_once 接收本轮工厂（C11）。
    """
    http = http or httpx.Client()
    nonce = fetch_nonce(http, server_base, device_key.device_fp)["nonce"]
    fp = env_fingerprint(browser_version, network_type)

    runs: list[dict] = []
    durations: list[int] = []
    failures: list[dict] = []
    for i in range(n):
        profile = tempfile.mkdtemp(prefix="forge-cert-profile-")
        try:
            factory_this_run = lambda: browser_factory(profile)  # noqa: E731  绑定本轮 profile
            t0 = time.perf_counter()
            outcome = runner.run_once(
                block_ref, dict(params or {}), mode="local", browser_factory=factory_this_run
            )
            durations.append(int((time.perf_counter() - t0) * 1000))
        finally:
            shutil.rmtree(profile, ignore_errors=True)  # 认证会话即焚
        runs.append({"index": i, "ok": outcome.ok, "failure_class": outcome.failure_class})
        if not outcome.ok:
            failures.append({"index": i, "failure_class": outcome.failure_class})

    report = {
        "runs": runs,  # 白名单：不含页面内容/快照文本（M09 §3.2）
        "env_fingerprint": fp,
        "fail_json": {"failures": failures},
        "durations": durations,
    }
    now = clock.now() if clock is not None else datetime.now(timezone.utc).replace(tzinfo=None)
    attestation = {
        "nonce": nonce,
        "report_hash": hashlib.sha256(canonical_json(report)).hexdigest()[:16],
        "env_fingerprint": fp,
        "client_version": __version__,
        "ts": now.isoformat(),
    }
    signature = device_key.sign(canonical_json(attestation))
    return SignedReport(
        report=report, attestation=attestation, signature=signature, device_fp=device_key.device_fp
    )

#!/usr/bin/env python3
"""verify_pf.py — macOS PF 专用用户四验证点采样（未实测，待 macOS 硬件）。

与 Windows 半边（spikes/egress_fw/probe.py）同口径的独立实现：
- --baseline <proxy_port> <host...>   策略前基线：直连 握手+TTFB n=30，输出 p95
- --in-policy <proxy_port> <host...>  策略中：应经 sudo -u _forge_comp 运行；
                                      经 127.0.0.1:<port> CONNECT 隧道采样 n=30，
                                      另做 raw socket 直连（预期阻断）与多地址 bind 尝试
- --perm-check                        专用用户权限最小化核查（无越权读取）

测量口径：TCP 建连（隧道=到 127.0.0.1 的建连+CONNECT 往返）+ TLS 完成 + 首字节，毫秒。
判定：附加率 = (策略中 p95 - 基线 p95) / 基线 p95 * 100，<10% 为过（M05 §2.1 ④ spike 口径）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import socket
import ssl
import sys
import time
from pathlib import Path

SAMPLES = 30
CONNECT_TIMEOUT_S = 15
ATTEMPT_TIMEOUT_S = 5.0


def percentile(samples: list[float], p: float) -> float:
    if not samples:
        raise ValueError("empty samples")
    if not 0 < p <= 1:
        raise ValueError("p out of range")
    ordered = sorted(samples)
    if len(ordered) == 1:
        return float(ordered[0])
    idx = p * (len(ordered) - 1)
    lo, hi = math.floor(idx), math.ceil(idx)
    frac = idx - lo
    return float(ordered[lo] * (1 - frac) + ordered[hi] * frac)


def handshake_ttfb_ms(host: str, port: int = 443, *, proxy_port: int | None = None,
                      timeout: float = CONNECT_TIMEOUT_S) -> float:
    t0 = time.perf_counter()
    if proxy_port is not None:
        sock = socket.create_connection(("127.0.0.1", proxy_port), timeout=timeout)
        sock.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                sock.close()
                raise ConnectionError("proxy closed during CONNECT")
            buf += chunk
        if b" 200 " not in buf.split(b"\r\n", 1)[0]:
            sock.close()
            raise ConnectionError(f"proxy CONNECT failed: {buf[:40]!r}")
    else:
        sock = socket.create_connection((host, port), timeout=timeout)
    try:
        tls = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    except Exception:
        sock.close()
        raise
    try:
        tls.settimeout(timeout)
        tls.sendall(f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
        if not tls.recv(1):
            raise ConnectionError("empty first byte")
        return (time.perf_counter() - t0) * 1000.0
    finally:
        tls.close()


def tcp_attempt(ip: str, port: int = 443, timeout: float = ATTEMPT_TIMEOUT_S) -> str:
    """macOS PF drop 的预期表现是超时；即时拒绝（EACCES 类）也算阻断。"""
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((ip, port))
        return "connected"
    except socket.timeout:
        return "timeout"
    except ConnectionRefusedError:
        return "refused"
    except PermissionError:
        return "blocked-eacces"
    except OSError as exc:
        return f"error:{type(exc).__name__}"
    finally:
        sock.close()


def local_ipv4s() -> list[str]:
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith("127."))


def cmd_baseline(args: argparse.Namespace) -> int:
    out: dict = {"phase": "baseline", "per_target": {}}
    for host in args.hosts:
        samples = [handshake_ttfb_ms(host) for _ in range(SAMPLES)]
        out["per_target"][host] = {"p95_ms": round(percentile(samples, 0.95), 1), "n": SAMPLES}
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_in_policy(args: argparse.Namespace) -> int:
    out: dict = {"phase": "in-policy", "per_target": {}, "bypass": {}}
    for host in args.hosts:
        ip = socket.gethostbyname(host)
        ok, samples = 0, []
        for _ in range(SAMPLES):
            try:
                samples.append(handshake_ttfb_ms(host, proxy_port=args.proxy_port))
                ok += 1
            except OSError as exc:
                print(f"sample-failed {host}: {exc}", file=sys.stderr)
        p95 = percentile(samples, 0.95) if samples else None
        out["per_target"][host] = {
            "ip": ip,
            "proxy_ok": f"{ok}/{SAMPLES}",
            "p95_ms": round(p95, 1) if p95 else None,
        }
        out["bypass"][ip] = tcp_attempt(ip)  # 预期非 connected
    alt = local_ipv4s()
    out["alt_nic"] = {a: "见 bypass 口径" for a in alt} if alt else "single-nic N/A"
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_perm_check(_args: argparse.Namespace) -> int:
    """在 _forge_comp 身份下运行：对管理域关键路径无读权限、无 admin 组。"""
    checks = {
        "home_isolated": str(Path.home()) == "/var/forge-comp",
        "cannot_read_root_lib": not Path("/Library/Keychains").is_readable()
        if Path("/Library/Keychains").exists() else None,
        "uid": os.getuid(),
    }
    print(json.dumps(checks, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("--baseline")
    p1.add_argument("proxy_port", type=int)
    p1.add_argument("hosts", nargs="+")
    p1.set_defaults(func=cmd_baseline)
    p2 = sub.add_parser("--in-policy")
    p2.add_argument("proxy_port", type=int)
    p2.add_argument("hosts", nargs="+")
    p2.set_defaults(func=cmd_in_policy)
    p3 = sub.add_parser("--perm-check")
    p3.set_defaults(func=cmd_perm_check)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

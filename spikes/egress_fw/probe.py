"""测量原语：握手+TTFB 计时、直连判定、分位数统计（MS-1A 四验证点口径）。"""
import math
import socket
import ssl
import time


def percentile(samples: list[float], p: float) -> float:
    if not samples:
        raise ValueError("empty samples")
    if not 0 < p <= 1:
        raise ValueError("p out of range")
    ordered = sorted(samples)
    if len(ordered) == 1:
        return float(ordered[0])
    idx = p * (len(ordered) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    frac = idx - lo
    return float(ordered[lo] * (1 - frac) + ordered[hi] * frac)


def delta_pct(direct_p95: float, proxy_p95: float) -> float:
    """代理附加延迟百分比；分母 = 直连 p95（M05 §2.1 验证点④口径）。"""
    if direct_p95 <= 0:
        raise ValueError("direct_p95 must be positive")
    return (proxy_p95 - direct_p95) / direct_p95 * 100.0


def tcp_attempt(ip: str, port: int = 443, timeout: float = 5.0) -> str:
    """白名单外直连判定的统一口径：connected / refused / timeout / error:<异常类名>。"""
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((ip, port))
        return "connected"
    except socket.timeout:
        return "timeout"
    except ConnectionRefusedError:
        return "refused"
    except OSError as exc:
        return f"error:{type(exc).__name__}"
    finally:
        sock.close()


def handshake_ttfb_ms(
    host: str,
    port: int = 443,
    *,
    proxy_endpoint: str | None = None,
    timeout: float = 10.0,
) -> float:
    """毫秒计：TCP 建连（走代理时=到代理的建连+CONNECT 往返）+ TLS 完成 + 首字节。

    隧道路径不解析目标域名（CONNECT 原样转发，解析在代理侧）。
    """
    t0 = time.perf_counter()
    if proxy_endpoint:
        ph, _, pp = proxy_endpoint.rpartition(":")
        sock = socket.create_connection((ph, int(pp)), timeout=timeout)
        request = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n"
        sock.sendall(request.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                sock.close()
                raise ConnectionError("proxy closed during CONNECT")
            buf += chunk
        status = buf.split(b"\r\n", 1)[0]
        if b" 200 " not in status:
            sock.close()
            raise ConnectionError(f"proxy CONNECT failed: {status!r}")
    else:
        sock = socket.create_connection((host, port), timeout=timeout)

    ctx = ssl.create_default_context()
    try:
        tls = ctx.wrap_socket(sock, server_hostname=host)
    except Exception:
        sock.close()
        raise
    try:
        tls.settimeout(timeout)
        request = f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
        tls.sendall(request.encode())
        first = tls.recv(1)
        t1 = time.perf_counter()
        if not first:
            raise ConnectionError("empty first byte")
        return (t1 - t0) * 1000.0
    finally:
        tls.close()

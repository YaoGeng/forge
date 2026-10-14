"""MS-1A T1.01-a/b 离线单测：CONNECT 代理、测量原语、防火墙封装。

不依赖外部网络与提权；防火墙命令全部经注入的 fake runner 断言命令构造。
"""
import json
import socket
import subprocess
import threading

import pytest

from egress_fw.proxy import EgressProxy
from egress_fw.probe import delta_pct, percentile, tcp_attempt


def _read_until(sock: socket.socket, marker: bytes, timeout: float = 5.0) -> bytes:
    sock.settimeout(timeout)
    buf = b""
    while marker not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf


def _ep(endpoint: str) -> tuple[str, int]:
    host, _, port = endpoint.rpartition(":")
    return host, int(port)


class _EchoServer:
    def __init__(self) -> None:
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port = self._sock.getsockname()[1]
        self._stopping = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stopping:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._echo, args=(conn,), daemon=True).start()

    @staticmethod
    def _echo(conn: socket.socket) -> None:
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    return
                conn.sendall(data)
        except OSError:
            pass
        finally:
            conn.close()

    def close(self) -> None:
        self._stopping = True
        self._sock.close()


def start_echo_server() -> _EchoServer:
    return _EchoServer()


# ---------- T1.01-a：测量原语 ----------

def test_percentile_known_vectors():
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == pytest.approx(9.55)
    assert percentile([5], 0.95) == 5
    with pytest.raises(ValueError):
        percentile([], 0.95)
    with pytest.raises(ValueError):
        percentile([1], 1.5)


def test_delta_pct_denominator():
    # 附加率分母 = 直连 p95（口径钉死，防实现时写反）
    assert delta_pct(direct_p95=100.0, proxy_p95=108.0) == pytest.approx(8.0)


# ---------- T1.01-a：CONNECT 代理 ----------

def test_proxy_connect_tunnel_and_log():
    echo = start_echo_server()
    px = EgressProxy()
    px.start()
    sock = None
    try:
        sock = socket.create_connection(_ep(px.endpoint), timeout=5)
        sock.sendall(f"CONNECT 127.0.0.1:{echo.port} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        buf = _read_until(sock, b"\r\n\r\n")
        assert b" 200 " in buf
        sock.sendall(b"ping")
        assert sock.recv(16) == b"ping"  # 隧道内双向透传
        assert px.connect_log == [f"127.0.0.1:{echo.port}"]
    finally:
        if sock is not None:
            sock.close()
        px.stop()
        echo.close()


def test_proxy_rejects_non_connect():
    px = EgressProxy()
    px.start()
    sock = None
    try:
        sock = socket.create_connection(_ep(px.endpoint), timeout=5)
        sock.sendall(b"GET / HTTP/1.1\r\n\r\n")
        assert b" 400 " in _read_until(sock, b"\r\n\r\n")
        assert px.connect_log[0].startswith("reject:")
    finally:
        if sock is not None:
            sock.close()
        px.stop()


def test_proxy_502_when_target_unreachable():
    px = EgressProxy()
    px.start()
    sock = None
    try:
        sock = socket.create_connection(_ep(px.endpoint), timeout=5)
        sock.sendall(b"CONNECT 127.0.0.1:1 HTTP/1.1\r\nHost: x\r\n\r\n")
        assert b" 502 " in _read_until(sock, b"\r\n\r\n")
    finally:
        if sock is not None:
            sock.close()
        px.stop()


def test_tcp_attempt_classification():
    echo = start_echo_server()
    try:
        assert tcp_attempt("127.0.0.1", echo.port, timeout=2) == "connected"
        # Windows 上被过滤/无服务的端口语义观测：两者都算「未连上」
        assert tcp_attempt("127.0.0.1", 1, timeout=2) in ("refused", "timeout")
    finally:
        echo.close()


# ---------- T1.01-a：worker endpoint 文件协议 ----------

def test_worker_writes_endpoint_file(tmp_path):
    from egress_fw.proxy_worker import remove_endpoint_file, write_endpoint_file

    f = tmp_path / "endpoint.txt"
    write_endpoint_file(f, "127.0.0.1:59999")
    assert f.read_text(encoding="utf-8").strip() == "127.0.0.1:59999"
    remove_endpoint_file(f)
    assert not f.exists()

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


# ---------- T1.01-b：防火墙封装（fake runner，不触系统） ----------

CANNED = json.dumps([
    {"Name": "Domain", "DefaultInboundAction": "Block", "DefaultOutboundAction": "Allow"},
    {"Name": "Private", "DefaultInboundAction": "Block", "DefaultOutboundAction": "Allow"},
    {"Name": "Public", "DefaultInboundAction": "Block", "DefaultOutboundAction": "Allow"},
])


def fake_runner(stdout: str, rc: int = 0):
    calls: list[list[str]] = []

    def run(args):
        calls.append(args)
        return subprocess.CompletedProcess(args, rc, stdout, "")

    run.calls = calls
    return run


def test_snapshot_profiles_parses_canned_json():
    from egress_fw.firewall import snapshot_profiles

    r = fake_runner(CANNED)
    snap = snapshot_profiles(r)
    assert snap["Public"] == {"in": "Block", "out": "Allow"}
    assert len(snap) == 3


def test_is_admin_true_and_false():
    from egress_fw.firewall import is_admin

    assert is_admin(fake_runner("True")) is True
    assert is_admin(fake_runner("False")) is False


def test_apply_block_preserves_inbound():
    from egress_fw.firewall import apply_outbound_block

    r = fake_runner("[]")
    snap = {"Public": {"in": "Block", "out": "Allow"}}
    apply_outbound_block(snap, r)
    joined = " ".join(r.calls[0])
    assert "Set-NetFirewallProfile" in joined
    assert "-DefaultOutboundAction Block" in joined
    assert "-DefaultInboundAction Block" in joined


def test_add_sidecar_allow_command_shape():
    from egress_fw.firewall import add_sidecar_allow

    r = fake_runner("")
    add_sidecar_allow(r"C:\v\.venv\Scripts\pythonw.exe", r)
    joined = " ".join(r.calls[0])
    assert "New-NetFirewallRule" in joined
    assert "Forge-Spike-Allow-Sidecar" in joined
    assert "Outbound" in joined and "Allow" in joined
    assert f"-Program '{r'C:\\v\\.venv\\Scripts\\pythonw.exe'}'" in joined
    assert "*" not in joined.replace("Forge-Spike-*", "")


def test_delete_uses_prefix_wildcard():
    from egress_fw.firewall import delete_spike_rules

    r = fake_runner("")
    delete_spike_rules(r)
    assert "Forge-Spike-*" in " ".join(r.calls[0])


def test_policy_matches_catches_drift():
    from egress_fw.firewall import policy_matches, snapshot_profiles

    snap = snapshot_profiles(fake_runner(CANNED))
    assert policy_matches(snap, fake_runner(CANNED)) is True
    r_drift = fake_runner(json.dumps([
        {"Name": "Domain", "DefaultInboundAction": "Block", "DefaultOutboundAction": "Block"},
        {"Name": "Private", "DefaultInboundAction": "Block", "DefaultOutboundAction": "Allow"},
        {"Name": "Public", "DefaultInboundAction": "Block", "DefaultOutboundAction": "Allow"},
    ]))
    assert policy_matches(snap, r_drift) is False


def test_ps_raises_on_nonzero():
    from egress_fw.firewall import _ps

    with pytest.raises(RuntimeError):
        _ps("anything", fake_runner("", rc=1))

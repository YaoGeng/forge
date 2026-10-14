"""最小 HTTP CONNECT 隧道代理（M05 §3 Egress Proxy 的 spike 裁剪版）。

只承载 MS-1A 验证：接收 CONNECT 请求、记录原始目标、双向透传。
不做策略引擎、不做 DNS 代理解析、不做认证——那是 M05-a 的实现范围。
"""
import asyncio
import threading


class EgressProxy:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._host = host
        self._requested_port = port
        self._server: asyncio.AbstractServer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._log: list[str] = []
        self._log_lock = threading.Lock()
        self._started = threading.Event()
        self._start_error: Exception | None = None

    @property
    def endpoint(self) -> str:
        if self._server is None:
            raise RuntimeError("proxy not started")
        port = self._server.sockets[0].getsockname()[1]
        return f"{self._host}:{port}"

    @property
    def connect_log(self) -> list[str]:
        with self._log_lock:
            return list(self._log)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="egress-proxy", daemon=True)
        self._thread.start()
        if not self._started.wait(timeout=5):
            raise RuntimeError(f"proxy failed to start: {self._start_error!r}")

    def stop(self) -> None:
        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass  # loop 已停或已关，无需再停
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise RuntimeError("proxy thread did not stop within 5s")
        if loop is not None:
            loop.close()
        if self._server is not None:
            self._server.close()
            self._server = None

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._server = self._loop.run_until_complete(
                asyncio.start_server(self._handle, self._host, self._requested_port)
            )
        except Exception as exc:
            self._start_error = exc
            self._started.set()
            return
        self._started.set()
        self._loop.run_forever()

    def _note(self, entry: str) -> None:
        with self._log_lock:
            self._log.append(entry)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            first = await asyncio.wait_for(reader.readline(), timeout=10)
            line = first.decode("latin-1", "replace").strip()
            parts = line.split()
            if len(parts) < 2 or parts[0].upper() != "CONNECT":
                self._note(f"reject:{line[:120]}")
                writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                await writer.drain()
                return
            target = parts[1]
            # 丢弃 CONNECT 头部剩余行直到空行
            while True:
                header = await asyncio.wait_for(reader.readline(), timeout=10)
                if header in (b"\r\n", b"\n", b""):
                    break
            self._note(target)
            host, _, port_s = target.rpartition(":")
            try:
                up_reader, up_writer = await asyncio.wait_for(
                    asyncio.open_connection(host, int(port_s)), timeout=10
                )
            except Exception:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                await writer.drain()
                return
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await asyncio.gather(
                self._pipe(reader, up_writer),
                self._pipe(up_reader, writer),
            )
        except (asyncio.TimeoutError, ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    @staticmethod
    async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await src.read(65536)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                dst.close()
            except Exception:
                pass

"""Recorder 装配：录制会话 + 事件采集 + 快照对齐 + 落盘（docs/11 §5 T1.21b）。

快照语义（M07 §3.1「操作与 DOM 快照按步骤对齐」）：每步快照取其**定案时点**
的页面——即聚合器产出该步的那个事件处理完的瞬间（Review Focus 1）。
实现：逐事件记录当时页面 html，落盘前用前缀聚合定位每步的定案事件。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from forge_proto.trace import Manifest, NetworkEntry, NetworkLog

from .events import BrowserEvent, Step, aggregate
from .port import BrowserPort
from .store import Annotation, RecordingsStore

# manifest 的格式版本（主.次；主段须与 proto CURRENT_MAJOR 一致）
TRACE_FORMAT_VERSION = "1.0"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class RecordingSession:
    host: str
    port: BrowserPort
    started_at: str


class Recorder:
    """录制装配。消费方经 `recorder.record.start/stop/annotate` 调用（M07 §5 签名）。"""

    def __init__(self, store: RecordingsStore, browser_factory):
        self._store = store
        self._browser_factory = browser_factory
        self._port: BrowserPort | None = None
        self._host: str | None = None
        self._events: list[BrowserEvent] = []
        self._htmls: list[str] = []
        self._network: list[NetworkEntry] = []
        self.record = _RecordFacade(self)

    def _start(self, host: str) -> RecordingSession:
        if self._port is not None:
            raise RuntimeError("录制已在进行中（record.start 不可重入）")
        port = self._browser_factory()
        port.install_hook(self._on_event)
        self._port = port
        self._host = host
        return RecordingSession(host=host, port=port, started_at=_utc_now_iso())

    def _on_event(self, event: BrowserEvent) -> None:
        assert self._port is not None
        self._events.append(event)
        self._network.extend(self._port.drain_network())
        self._htmls.append(self._port.snapshot_html())

    def _stop(self) -> str:
        if self._port is None:
            raise RuntimeError("record.stop 需先 record.start")
        events = self._events
        htmls = self._htmls
        steps = aggregate(events)
        if not steps:
            raise RuntimeError("录制未产生任何步骤，不生成轨迹")
        snapshots = _snapshots_at_finalize(events, htmls, steps)
        manifest = Manifest(
            format_version=TRACE_FORMAT_VERSION,
            site=self._host or "",
            login_steps=(),
            time_sensitive_steps=(),
        )
        network = NetworkLog(captured_at=_utc_now_iso(), entries=tuple(self._network))
        assert self._host is not None
        trace_ref = self._store.allocate(self._host)
        self._store.save_trace(trace_ref, manifest, steps, snapshots, network)
        self._port = None
        self._host = None
        self._events = []
        self._htmls = []
        self._network = []
        return trace_ref

    def _annotate(self, trace_ref: str, step_seq: int, element_ref: str, hint: str) -> Annotation:
        return self._store.annotate(trace_ref, step_seq, element_ref, hint)


def _snapshots_at_finalize(
    events: list[BrowserEvent], htmls: list[str], steps: tuple[Step, ...]
) -> dict[int, str]:
    """每步快照 = 其定案事件（前缀聚合首次产出该步）时点的页面。"""
    snapshots: dict[int, str] = {}
    for j in range(len(events)):
        prefix = aggregate(events[: j + 1])
        if len(prefix) == len(steps) and all(s in prefix for s in steps):
            # 全部步骤已定案，其后事件不再改变归属
            remaining = [s for s in steps if s.seq not in snapshots]
            for s in remaining:
                snapshots[s.seq] = htmls[j]
            break
        for s in prefix:
            if s.seq not in snapshots:
                snapshots[s.seq] = htmls[j]
    missing = [s.seq for s in steps if s.seq not in snapshots]
    if missing:
        raise RuntimeError(f"步骤快照缺失: {missing}")
    return snapshots


class _RecordFacade:
    """M07 §5 消费面：record.start(host) / record.stop() → trace_ref / record.annotate(...)。"""

    def __init__(self, recorder: Recorder):
        self._recorder = recorder

    def start(self, host: str) -> RecordingSession:
        return self._recorder._start(host)

    def stop(self) -> str:
        return self._recorder._stop()

    def annotate(self, trace_ref: str, step_seq: int, element_ref: str, hint: str) -> Annotation:
        return self._recorder._annotate(trace_ref, step_seq, element_ref, hint)

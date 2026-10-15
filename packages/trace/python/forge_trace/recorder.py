"""Recorder 装配：录制会话 + 事件采集 + 快照对齐 + 落盘（docs/11 §5 T1.21b）。

快照语义（M07 §3.1「操作与 DOM 快照按步骤对齐」）：每步快照取其**定案时点**
的页面——即聚合器产出该步的那个事件处理完的瞬间（Review Focus 1）。
实现：逐事件记录当时页面 html，落盘前用前缀聚合定位每步的定案事件。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from forge_proto.trace import CURRENT_MAJOR, Manifest, NetworkEntry, NetworkLog

from .events import BrowserEvent, Step, aggregate
from .port import BrowserPort
from .store import Annotation, RecordingsStore

# manifest 的格式版本（主.次；主段须与 proto CURRENT_MAJOR 一致，漂移在导入即暴露）
TRACE_FORMAT_VERSION = "1.0"
assert TRACE_FORMAT_VERSION.split(".")[0] == CURRENT_MAJOR, (
    f"TRACE_FORMAT_VERSION 主版本须与 proto CURRENT_MAJOR={CURRENT_MAJOR} 一致"
)


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
        if not host:
            raise ValueError("host 不能为空（manifest.site 必填）")
        if self._port is not None:
            raise RuntimeError("录制已在进行中（record.start 不可重入）")
        port = self._browser_factory()
        # 先挂自身引用再装钩子：端口可能在 install_hook 内同步回放队列事件
        self._port = port
        port.install_hook(self._on_event)
        self._host = host
        return RecordingSession(host=host, port=port, started_at=_utc_now_iso())

    def _on_event(self, event: BrowserEvent) -> None:
        assert self._port is not None
        self._events.append(event)
        self._network.extend(self._port.drain_network())
        # 优先事件自带快照（真实适配器 JS 随事件提供，事件处理器内零 CDP——
        # commit 时点调 page.content() 会阻塞到浏览器关闭，gate 实证）；
        # 缺省时回退端口主线程快照（FakeBrowser/测试路径）
        html = event.html if event.html is not None else self._port.snapshot_html()
        self._htmls.append(html)

    def _stop(self) -> str:
        if self._port is None:
            raise RuntimeError("record.stop 需先 record.start")
        try:
            # 先收口 pending nav（主线程 drain 会触发适配器 flush 并派发积压事件）
            self._network.extend(self._port.drain_network())
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
            return trace_ref
        finally:
            self._port = None
            self._host = None
            self._events = []
            self._htmls = []
            self._network = []

    def _annotate(self, trace_ref: str, step_seq: int, element_ref: str, hint: str) -> Annotation:
        return self._store.annotate(trace_ref, step_seq, element_ref, hint)


def _snapshots_at_finalize(
    events: list[BrowserEvent], htmls: list[str], steps: tuple[Step, ...]
) -> dict[int, str]:
    """每步快照 = 其定案事件时点的页面。

    前缀聚合用 end_flush=False：尾部待定缓冲不提前收口，步骤在其真实
    冲刷触发事件（或 stop 收口）时点首次出现（T1.21b 评审 Important-1）。
    """
    snapshots: dict[int, str] = {}
    for j in range(len(events)):
        prefix = aggregate(events[: j + 1], end_flush=False)
        if len(prefix) == len(steps) and all(s in prefix for s in steps):
            for s in steps:
                if s.seq not in snapshots:
                    snapshots[s.seq] = htmls[j]
            break
        for s in prefix:
            if s.seq not in snapshots:
                snapshots[s.seq] = htmls[j]
    for s in steps:
        if s.seq not in snapshots:
            # 末尾待定缓冲由 stop() 收口定案，取最后时刻页面
            snapshots[s.seq] = htmls[-1]
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

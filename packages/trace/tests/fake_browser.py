"""FakeBrowser：BrowserPort 三面测试假体（不触网）。

- 事件脚本注入：测试经 emit_* 模拟创作者操作，事件经 install_hook 送达 Recorder；
- html 编程：测试直接给 browser.html 赋值，模拟页面演变（快照对齐用）；
- route 记账：golden 面 matcher 存储 + route_hit 命中/直连记账（T1.23 消费）；
- 回放面：goto/click/fill/... 全部只记账不执行，供回放断言。
"""
from __future__ import annotations

from forge_proto.trace import NetworkEntry

from forge_trace.events import BrowserEvent
from forge_trace.port import EventHook, RouteMatcher


class FakeBrowser:
    def __init__(self) -> None:
        self.html = "<html></html>"
        self.url = ""
        self._hook: EventHook | None = None
        self._net: list[NetworkEntry] = []
        self._ts = 0
        # golden 面
        self.matcher: RouteMatcher | None = None
        self.route_hits: list[tuple[str, str]] = []  # 命中 route 的 (method, url)
        self.direct_requests: list[tuple[str, str]] = []  # 绕过 route 的直连记账
        # 回放面记账
        self.gotos: list[str] = []
        self.clicks: list[str] = []
        self.fills: list[tuple[str, str]] = []
        self.scrolls: list[int] = []
        self.waits: list[tuple[str, int]] = []
        self.presses: list[str] = []
        self.hidden: set[str] = set()  # 测试模拟元素缺失（wait_selector 判 False）

    # —— 录制面 ——
    def install_hook(self, on_event: EventHook) -> None:
        self._hook = on_event

    def snapshot_html(self) -> str:
        return self.html

    def drain_network(self) -> list[NetworkEntry]:
        out, self._net = self._net, []
        return out

    # —— 事件脚本注入（录制会话中模拟创作者操作）——
    def _emit(self, event: BrowserEvent) -> BrowserEvent:
        if self._hook is None:
            raise RuntimeError("未 install_hook：事件注入须在录制会话内")
        self._hook(event)
        return event

    def _next_ts(self, ts_ms: int | None) -> int:
        if ts_ms is None:
            self._ts += 100
            return self._ts
        self._ts = max(self._ts, ts_ms)
        return ts_ms

    def emit(
        self,
        kind: str,
        *,
        selector: str | None = None,
        anchor: str | None = None,
        value: str | None = None,
        delta: int | None = None,
        url: str | None = None,
        ts_ms: int | None = None,
    ) -> BrowserEvent:
        return self._emit(
            BrowserEvent(
                kind=kind,
                selector=selector,
                anchor=anchor,
                value=value,
                delta=delta,
                url=url,
                ts_ms=self._next_ts(ts_ms),
            )
        )

    def emit_nav(self, url: str, *, html: str | None = None) -> BrowserEvent:
        self.html = html if html is not None else f"<html><body>{url}</body></html>"
        self._net.append(
            NetworkEntry(
                url=url, method="GET", status=200, mime_type="text/html",
                request_body=None, response_body=None,
            )
        )
        return self.emit("nav", url=url)

    def emit_click(self, selector: str, anchor: str) -> BrowserEvent:
        return self.emit("click", selector=selector, anchor=anchor)

    def emit_input(self, selector: str, anchor: str, value: str) -> BrowserEvent:
        """模拟真实注入脚本形态：逐字符 keystroke 后跟 blur（冲刷由 blur 触发）。"""
        for ch in value:
            self.emit("keystroke", selector=selector, anchor=anchor, value=ch)
        return self.emit_blur(selector)

    def emit_scroll(self, selector: str | None, delta: int) -> BrowserEvent:
        return self.emit("scroll", selector=selector, delta=delta)

    def emit_blur(self, selector: str) -> BrowserEvent:
        return self.emit("blur", selector=selector)

    # —— 回放面（只记账）——
    def goto(self, url: str) -> None:
        self.gotos.append(url)
        self.url = url
        self.html = f"<html><body>{url}</body></html>"

    def click(self, selector: str) -> None:
        self.clicks.append(selector)

    def fill(self, selector: str, value: str) -> None:
        self.fills.append((selector, value))

    def scroll_by(self, delta: int) -> None:
        self.scrolls.append(delta)

    def wait_selector(self, selector: str, timeout_ms: int = 5000) -> bool:
        self.waits.append((selector, timeout_ms))
        return selector not in self.hidden

    def press(self, key: str) -> None:
        self.presses.append(key)

    def current_url(self) -> str:
        return self.url

    # —— golden 面 ——
    def set_routes(self, matcher: RouteMatcher) -> None:
        self.matcher = matcher

    def route_hit(self, method: str, url: str):
        """页面请求经 route 分流（假体语义）：命中返回 stub，未命中记直连。"""
        if self.matcher is None:
            self.direct_requests.append((method, url))
            return None
        entry = NetworkEntry(
            url=url, method=method, status=0, mime_type=None,
            request_body=None, response_body=None,
        )
        stub = self.matcher(entry, method, url)
        if stub is None:
            self.direct_requests.append((method, url))
        else:
            self.route_hits.append((method, url))
        return stub

    def feed_network(self, entry: NetworkEntry) -> None:
        """模拟「无对应录制事件的网络到达」（如最后一次 click 触发的 XHR 迟到）。"""
        self._net.append(entry)

"""BrowserPort：浏览器最小端口（docs/11 §3 C10 三面）。

patchright 适配器（patchright_browser.py，T1.25）与测试假体（tests/fake_browser.py）
共同实现本协议；其余模块一律面向端口编程（单测不触网的机制保证）。
类型约定：BrowserEvent/ElementFp 定义在 events.py/selectors.py（与其纯函数消费方同处），
此处 re-export 供消费方单点导入。
"""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

from forge_proto.trace import NetworkEntry

from .events import BrowserEvent
from .selectors import ElementFp

# 事件回调：适配器把真实浏览器事件锻造成 BrowserEvent 后经此上报
EventHook = Callable[[BrowserEvent], None]
# golden 路由匹配器：(entry, method, url) -> stub | None（stub 形态由 T1.23 钉死）
RouteMatcher = Callable[[NetworkEntry, str, str], Any]


@runtime_checkable
class BrowserPort(Protocol):
    """录制/回放/golden 三面（C10）。"""

    # —— 录制面 ——
    def install_hook(self, on_event: EventHook) -> None: ...
    def snapshot_html(self) -> str: ...
    def drain_network(self) -> list[NetworkEntry]: ...

    # —— 回放面 ——
    def goto(self, url: str) -> None: ...
    def click(self, selector: str) -> None: ...
    def fill(self, selector: str, value: str) -> None: ...
    def scroll_by(self, delta: int) -> None: ...
    def wait_selector(self, selector: str, timeout_ms: int) -> bool: ...
    def press(self, key: str) -> None: ...
    def current_url(self) -> str: ...
    def inner_text(self, selector: str) -> str: ...  # T1.71：站点脚本数据抽取消费面

    # —— golden 面 ——
    def set_routes(self, matcher: RouteMatcher) -> None: ...


__all__ = ["BrowserEvent", "BrowserPort", "ElementFp", "EventHook", "RouteMatcher"]

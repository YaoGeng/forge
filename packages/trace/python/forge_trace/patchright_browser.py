"""Patchright 适配器：BrowserPort 三面的真实实现（docs/11 §3 C10/D-M1D.1）。

边界纪律（D-M1D.1）：patchright 仅允许出现在本模块与 spikes 运行器；
其余模块一律面向 BrowserPort 编程。本模块无 pytest（触网），
由 spikes/run_ms1d_gate.py 三站点 gate 实证。

事件采集约束（gate 实证得出）：
- patchright 屏蔽 add_init_script（反检测加固）→ 注入脚本在**每次主框架
  load 时点经 evaluate 重注入**（每文档一次），并随注入返回当时 outerHTML；
- **事件处理器内零 CDP 调用**：click/input/scroll 由 JS 随 binding 自带
  outerHTML，nav 在 load 时点由注入的返回值提供——Recorder 的快照对齐
  因此不再有 commit 时点的阻塞风险（page.content() 只留在主线程回放面）；
- input 在 JS 侧防抖 800ms、异元素操作/Enter/blur 前强制冲刷（事件顺序
  与创作者操作一致）；元素以指纹（ElementFp 同构 JSON）上报，selector/
  anchor 锻造统一走 Python 侧 forge_selector（C5 单源）；
- 网络采集：response 事件增量缓冲（response body v1 不取，README 缓办；
  golden 匹配只用键不含值）。SPA pushState 导航不产生 load 事件 → 不记
  nav 步（v1 已知边界）。
"""
from __future__ import annotations

import time
from typing import Callable

from forge_proto.trace import NetworkEntry
from patchright.sync_api import sync_playwright

from .events import BrowserEvent
from .selectors import ElementFp, forge_selector

_WAIT_TIMEOUT_MS = 10_000
_GOTO_TIMEOUT_MS = 30_000

# 注入 + 快照二合一：已注入则只返回 outerHTML；每文档由 Python 在 load 时点调用
_INJECT_AND_SNAPSHOT = """
() => {
  if (!window.__forge) {
    const S = (window.__forge = { lastY: window.scrollY, pending: null, timer: null });
    const fp = (el) => {
      if (!el || !el.tagName) return null;
      const tag = el.tagName.toLowerCase();
      const path = [];
      let node = el, depth = 0;
      while (node && node.tagName && depth < 12) {
        let nth = 1, sib = node;
        while ((sib = sib.previousElementSibling)) nth++;
        path.unshift(node.tagName.toLowerCase() + ':nth-of-type(' + nth + ')');
        node = node.parentElement; depth++;
      }
      const attrs = {};
      for (const a of el.attributes || []) {
        if (a.name.startsWith('data-') || a.name === 'aria-label') attrs[a.name] = a.value;
      }
      return {
        tag,
        id: el.id || null,
        classes: [...(el.classList || [])],
        attrs,
        text: ((el.innerText || el.textContent || '') + '').slice(0, 200),
        path,
      };
    };
    const send = (payload) => {
      payload.html = document.documentElement.outerHTML;
      try { window.forgeEvent(payload); } catch (e) {}
    };
    const flush = () => {
      if (S.timer) { clearTimeout(S.timer); S.timer = null; }
      if (S.pending) { send({ kind: 'input', fp: S.pending.fp, value: S.pending.value }); S.pending = null; }
    };
    const onInput = (e) => {
      const t = e.target;
      if (!t || !t.tagName) return;
      const tag = t.tagName.toLowerCase();
      if (tag !== 'input' && tag !== 'textarea') return;
      if (!S.pending || S.pending.el !== t) flush();
      S.pending = { el: t, fp: fp(t), value: t.value || '' };
      if (S.timer) clearTimeout(S.timer);
      S.timer = setTimeout(flush, 800);
    };
    const onBlur = (e) => { if (S.pending && S.pending.el === e.target) flush(); };
    const onClick = (e) => { flush(); const f = fp(e.target); if (f) send({ kind: 'click', fp: f }); };
    const onScroll = () => {
      const y = window.scrollY, d = y - S.lastY;
      S.lastY = y;
      if (d) { flush(); send({ kind: 'scroll', delta: d }); }
    };
    document.addEventListener('input', onInput, true);
    document.addEventListener('blur', onBlur, true);
    document.addEventListener('click', onClick, true);
    document.addEventListener('keydown', (e) => { if (e.key === 'Enter') flush(); }, true);
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('load', () => {
      try { window.forgeEvent({ kind: 'nav', url: location.href, html: document.documentElement.outerHTML }); } catch (e) {}
    });
  }
  return document.documentElement.outerHTML;
}
"""


class PatchrightBrowser:
    """每个实例一个全新浏览器/上下文（录制与每次回放各自独立）。

    nav 检测：framenavigated 处理器只登记 (url, commit ts)（零 CDP），
    由后续任一主线程端口调用泵出——wait_for_load_state + 注入 + 发事件；
    事件时间戳取 commit 时点，聚合排序保持「导航先于后续页面内操作」。
    （gate 实证：patchright 下点击导航不触发 page.on("load")，
    且 commit 时点调 page.content() 会阻塞到浏览器关闭。）
    """

    def __init__(self, *, headless: bool = True, html_sink: list[str] | None = None):
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=headless)
        except BaseException:
            # 启动失败必须停掉已起的 dispatcher——否则其常驻线程会让本进程内的
            # 下一次 sync_playwright() 误报 "Sync API inside asyncio loop"
            # （MS-2 运行器首启安装后重试路径实测）；零引用泄漏留给 GC 必炸重试。
            self._pw.stop()
            raise
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._page.expose_binding("forgeEvent", self._binding)
        self._page.on("framenavigated", self._on_framenavigated)
        self._page.on("response", self._on_response)
        self._hook: Callable[[BrowserEvent], None] | None = None
        self._net_buf: list[NetworkEntry] = []
        self._pending_nav: tuple[str, int] | None = None
        self._last_nav_url: str | None = None
        self._flushing = False
        self._in_dispatch = False
        self._last_html = ""
        self._html_sink = html_sink
        self._ts0 = time.monotonic()

    # —— 录制面 ——
    def install_hook(self, on_event) -> None:
        self._hook = on_event

    def snapshot_html(self) -> str:
        """主线程调用（回放面逐步 digest；Recorder 兜底）。事件路径不经过这里。"""
        self._flush_nav()
        try:
            self._last_html = self._page.content()
        except Exception:
            pass  # 导航进行中执行上下文可能销毁：回退最近快照
        if self._html_sink is not None:
            self._html_sink.append(self._last_html)
        return self._last_html

    def drain_network(self) -> list[NetworkEntry]:
        self._flush_nav()  # 事件间与 stop 时收口待定 nav（Recorder 逐事件调用）
        out, self._net_buf = self._net_buf, []
        return out

    # —— 回放面 ——
    def goto(self, url: str) -> None:
        # wait_until=domcontentloaded（MS-2 T2.12 实测修订）：load 会被三方资源
        # （统计/广告脚本）挂起——受限网络下 30s 必超时，也是买家首跑的真实失败
        # 模式；DOM 就绪即返，元素等待由 wait_selector 独立兜底，锚语义不变。
        self._page.goto(url, timeout=_GOTO_TIMEOUT_MS, wait_until="domcontentloaded")
        self._flush_nav()

    def click(self, selector: str) -> None:
        self._flush_nav()
        self._page.click(selector, timeout=_WAIT_TIMEOUT_MS)

    def fill(self, selector: str, value: str) -> None:
        self._flush_nav()
        self._page.fill(selector, value, timeout=_WAIT_TIMEOUT_MS)

    def scroll_by(self, delta: int) -> None:
        self._flush_nav()
        self._page.mouse.wheel(0, delta)

    def wait_selector(self, selector: str, timeout_ms: int) -> bool:
        self._flush_nav()
        try:
            self._page.wait_for_selector(selector, timeout=timeout_ms, state="attached")
            return True
        except Exception:
            return False

    def press(self, key: str) -> None:
        self._flush_nav()
        self._page.keyboard.press(key)

    def current_url(self) -> str:
        self._flush_nav()
        return self._page.url

    def inner_text(self, selector: str) -> str:
        self._flush_nav()
        return self._page.locator(selector).inner_text()

    # —— golden 面 ——
    def set_routes(self, matcher) -> None:
        def handle(route, request):
            entry = NetworkEntry(
                url=request.url, method=request.method, status=0, mime_type=None,
                request_body=None, response_body=None,
            )
            stub = matcher(entry, request.method, request.url)
            if stub is not None:
                route.fulfill(
                    status=int(stub.get("status", 200)),
                    content_type=stub.get("mime_type") or "text/html",
                    body=stub.get("response_body") or "",
                )
            else:
                route.continue_()

        self._page.route("**/*", handle)

    # —— 内部 ——
    def _now_ms(self) -> int:
        return int((time.monotonic() - self._ts0) * 1000)

    def _on_framenavigated(self, frame) -> None:
        """只登记 pending（零 CDP 调用）：commit 时点快照会阻塞，泵出延迟到主线程。
        连续同 URL 的 framenavigated（patchright 对单次导航可多次派发）去重。"""
        if self._hook is None or frame is not self._page.main_frame:
            return
        if self._pending_nav is not None:
            return
        url = frame.url
        if url == self._last_nav_url:
            return
        self._pending_nav = (url, self._now_ms())

    def _flush_nav(self) -> None:
        """主线程泵出待定 nav：先给派发队列一次机会（framenavigated 只在
        playwright 调用间隙到达，纯 Python 调用期间它永远排队），等 load，
        注入（每文档一次），发 nav 事件。

        守卫：①重入（泵出 emit 经 Recorder drain 回到本函数）；②**派发
        上下文**——binding 等处理器内的任何 playwright 等待调用都会死锁
        （导航完成事件无法进入正在派发的循环，gate 实证）；派发期间登记
        的 pending 由下一个主线程端口调用泵出。"""
        if self._hook is None or self._flushing or self._in_dispatch:
            return
        self._flushing = True
        try:
            for _ in range(3):
                try:
                    self._page.wait_for_load_state("load", timeout=300)
                except Exception:
                    pass
                if self._pending_nav is None:
                    return
                url, ts = self._pending_nav
                self._pending_nav = None
                try:
                    self._page.wait_for_load_state("load", timeout=5_000)
                except Exception:
                    pass  # 慢页：如实带当前状态泵出
                try:
                    html = self._page.evaluate(_INJECT_AND_SNAPSHOT)
                except Exception:
                    html = None  # 注入失败：本页事件缺失，如实留空（不中断录制）
                self._last_nav_url = self._page.url
                self._hook(BrowserEvent(
                    kind="nav", url=self._page.url, html=html, ts_ms=ts,
                ))
        finally:
            self._flushing = False

    def _binding(self, source, payload: dict) -> None:
        if self._hook is None:
            return
        self._in_dispatch = True
        try:
            kind = payload.get("kind")
            doc = payload.get("fp") or {}
            fp = ElementFp(
                tag=str(doc.get("tag", "div")),
                id=doc.get("id"),
                classes=tuple(doc.get("classes") or ()),
                attrs=dict(doc.get("attrs") or {}),
                text=doc.get("text"),
                path=tuple(doc.get("path") or ()),
            )
            selector, anchor = forge_selector(fp)
            self._hook(BrowserEvent(
                kind=kind,
                selector=selector,
                anchor=anchor,
                value=payload.get("value"),
                delta=payload.get("delta"),
                html=payload.get("html"),
                ts_ms=self._now_ms(),
            ))
        finally:
            self._in_dispatch = False

    def _on_response(self, response) -> None:
        self._in_dispatch = True
        try:
            content_type = response.headers.get("content-type") or ""
            post_data = response.request.post_data
            self._net_buf.append(NetworkEntry(
                url=response.url,
                method=response.request.method,
                status=response.status,
                mime_type=content_type.split(";")[0] or None,
                request_body=post_data if isinstance(post_data, str) else None,
                response_body=None,  # v1 不取响应体（README 缓办；golden 匹配只用键）
            ))
        except Exception:
            pass  # 单条网络事件采集失败不阻断录制
        finally:
            self._in_dispatch = False

    def close(self) -> None:
        for closer in (self._context.close, self._browser.close, self._pw.stop):
            try:
                closer()
            except Exception:
                pass

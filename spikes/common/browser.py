"""Patchright 会话封装：Chromium 定位与标准启动。

锚：docs/07-MS0执行计划.md T0.1a Interfaces。
UA 保持真实 Chromium 默认值，不做任何指纹定制（G7 检测礼仪）。
"""
import os
from contextlib import contextmanager
from pathlib import Path

from patchright.sync_api import sync_playwright

_CHROMIUM_GLOB = "chromium*/chrome-win*/chrome.exe"


def _candidate_roots() -> list[Path]:
    # PLAYWRIGHT_BROWSERS_PATH 语义与 playwright 一致：设置即完全覆盖默认目录
    env_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_root:
        return [Path(env_root)]
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    return [Path(local) / "ms-playwright", Path(local) / "ms-playwright-patchright"]


def resolve_chromium_executable() -> Path:
    """定位 Patchright 安装的 Chromium 可执行文件；找不到抛 RuntimeError。"""
    candidates: list[Path] = []
    for root in _candidate_roots():
        if root.is_dir():
            candidates.extend(root.glob(_CHROMIUM_GLOB))
    if not candidates:
        raise RuntimeError(
            "patchright chromium not installed - run 'patchright install chromium'"
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


@contextmanager
def new_page(headless: bool = True):
    """启动 Patchright Chromium，yield Page；退出时关闭 browser/context。

    启动失败抛 RuntimeError('chromium launch failed: ...')。
    """
    executable = resolve_chromium_executable()
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=str(executable), headless=headless)
        except Exception as exc:
            raise RuntimeError(f"chromium launch failed: {exc}") from exc
        context = browser.new_context()
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()

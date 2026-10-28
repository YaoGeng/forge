"""浏览器工厂（docs/17 T2.12）：patchright 有头浏览器 + Chromium 首启自举。

边界纪律（D-M1D.1）：patchright 只允许出现在 forge_trace 适配器与本模块。
工厂失败（如买家机器无 Chromium）→ BrowserUnavailable（中文、退出码 3）。
"""
from __future__ import annotations

import os
import subprocess
import sys


class BrowserUnavailable(Exception):
    """浏览器不可用（未安装/下载失败）——CLI 退出码 3。"""


def _install_chromium() -> None:
    """首启安装：优先 FORGE_BROWSER_INSTALL_CMD（PyInstaller exe 场景），

    缺省走当前解释器 `python -m patchright install chromium`。"""
    cmd = os.environ.get("FORGE_BROWSER_INSTALL_CMD")
    if cmd:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    else:
        result = subprocess.run(
            [sys.executable, "-m", "patchright", "install", "chromium"],
            capture_output=True, text=True)
    if result.returncode != 0:
        raise BrowserUnavailable(
            f"Chromium 首启下载失败：{result.stderr or result.stdout}\n"
            f"请检查网络后重试（或设置 FORGE_BROWSER_INSTALL_CMD 指向安装命令）")


def make_factory(*, headless: bool = True):
    """买家运行默认无头（实测修订：有头在部分 Windows 机器因 GPU/焦点开销必超时；
    现库 5 应用全部无人值守可跑，浏览器可见性随 M16/Electron 阶段交付）。
    失败时自举安装一次后重试。"""

    def factory():
        from forge_trace.patchright_browser import PatchrightBrowser

        try:
            return PatchrightBrowser(headless=headless)
        except Exception as exc:  # noqa: BLE001 —— 首启缺浏览器是预期路径
            msg = str(exc)
            if "Executable" in msg or "executable" in msg or "install" in msg.lower():
                _install_chromium()
                try:
                    return PatchrightBrowser(headless=headless)
                except Exception as exc2:  # noqa: BLE001
                    raise BrowserUnavailable(
                        f"浏览器启动失败（安装后仍不可用）：{exc2}") from exc2
            raise BrowserUnavailable(f"浏览器启动失败：{msg}") from exc

    return factory

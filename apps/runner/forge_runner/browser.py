"""浏览器工厂（docs/17 T2.12）：patchright 有头浏览器 + Chromium 首启自举。

边界纪律（D-M1D.1）：patchright 只允许出现在 forge_trace 适配器与本模块。
工厂失败（如买家机器无 Chromium）→ BrowserUnavailable（中文、退出码 3）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# 浏览器落点必须稳定（用户目录）：onefile exe 每次运行解压到不同 _MEI 临时目录，
# 装在驱动旁的浏览器下次必丢；装/启两侧都读 PLAYWRIGHT_BROWSERS_PATH 保持同源。
_STABLE_BROWSERS = Path(
    os.environ.get("LOCALAPPDATA") or Path.home()) / "forge" / "ms-playwright"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_STABLE_BROWSERS))
# 下载源默认 npmmirror 镜像（官方 CDN 在国内网络 ECONNRESET 实测；playwright 下载
# 后自带哈希校验，镜像不改内容；显式设 PLAYWRIGHT_DOWNLOAD_HOST 可覆盖）
os.environ.setdefault("PLAYWRIGHT_DOWNLOAD_HOST",
                      "https://cdn.npmmirror.com/binaries/playwright")


class BrowserUnavailable(Exception):
    """浏览器不可用（未安装/下载失败）——CLI 退出码 3。"""


def _install_chromium() -> None:
    """首启安装。三种执行形态：

    - PyInstaller exe（sys.frozen）：`sys.executable -m patchright` 会把参数发给
      exe 自身（实测 argparse 报 invalid choice）——改调 patchright 自带 node driver；
    - FORGE_BROWSER_INSTALL_CMD：显式覆盖（预留）；
    - 源码运行：当前解释器 `python -m patchright install chromium`。
    """
    if getattr(sys, "frozen", False):
        from patchright._impl._driver import compute_driver_executable

        node, cli = compute_driver_executable()  # 返回 (node.exe, cli.js) 二元组
        cmd = [str(node), str(cli), "install", "chromium"]
        result = subprocess.run(cmd, capture_output=True, text=True)
    else:
        override = os.environ.get("FORGE_BROWSER_INSTALL_CMD")
        if override:
            result = subprocess.run(override, shell=True,
                                    capture_output=True, text=True)
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

"""PyInstaller 入口（T2.13）：平铺脚本保留 forge_runner 包上下文（__main__.py 直接作入口会丢包）。

输出统一 UTF-8（exe 控制台编码随系统漂移，中文消息会因 cp936/utf-8 错配碎掉；
买家终端如乱码提示 chcp 65001——v0 已知边界，Electron 壳阶段消除）。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from forge_runner.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

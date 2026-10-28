"""进程入口：python -m forge_runner / PyInstaller exe 同入口。"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())

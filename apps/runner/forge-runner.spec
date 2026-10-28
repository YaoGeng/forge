# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec（docs/17 T2.13）：单文件 Windows exe。
# 构建：cd apps/runner && pyinstaller forge-runner.spec（依赖见 requirements-build.txt）
import sys
from pathlib import Path

HERE = Path(SPECPATH)  # apps/runner
ROOT = HERE.parent.parent

# patchright 的 node driver（driver/node.exe + package/）是数据文件，
# 静态分析收集不到——显式打包，否则运行时 WinError 2（T2.13 exe 实测）
import patchright

_driver = Path(patchright.__file__).parent / "driver"
datas = [(str(_driver), "patchright/driver")] if _driver.exists() else []

a = Analysis(
    [str(HERE / "entry.py")],
    pathex=[str(HERE),
            str(ROOT / "packages" / "trace" / "python"),
            str(ROOT / "packages" / "proto" / "python")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # 惰性导入，PyInstaller 静态分析看不见
        "forge_trace.patchright_browser",
        "forge_proto.trace",
        # 块 main.py 经 importlib spec 运行时加载——其依赖必须显式收进
        "openpyxl",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="forge-runner",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
)

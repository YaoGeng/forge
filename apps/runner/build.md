# forge-runner 构建（docs/17 T2.13）

## 本地构建（Windows）

```bash
cd apps/runner
pip install -r requirements-build.txt
pyinstaller forge-runner.spec --noconfirm --distpath build-dist
```

产物：`build-dist/forge-runner.exe`（单文件，~50MB，含 patchright node driver）。

## CI 构建（deploy.yml → runner-build job）

tag `v*` 触发：部署完成后在 windows-latest 构建 → exe 冒烟（library 未登录
退出码 2）→ scp 到服务器 `/opt/aim/forge/dist/forge-runner-<ver>-win.exe` →
版本写入 `.env`（FORGE_RUNNER_VERSION）→ compose 重载 → 回源断言 `/api/v1/store/runner` 200。

## 实测坑位登记（2026-10-26 本地 exe E2E 逐项踩出）

1. **入口必须平铺脚本** `entry.py`——`__main__.py` 直接作 spec 入口丢包上下文（相对导入炸）；
2. **patchright driver 是数据文件**，spec 显式 `datas=[(driver, "patchright/driver")]`；
3. **exe 内首启安装**不能 `sys.executable -m patchright`（会把参数发给 exe 自身）——frozen 下走 `compute_driver_executable()` 返回的 `(node.exe, cli.js)` 二元组；
4. **浏览器落点钉稳定目录** `PLAYWRIGHT_BROWSERS_PATH=%LOCALAPPDATA%\forge\ms-playwright`——onefile 每次解压到不同 _MEI，装驱动旁必丢；
5. **下载源默认 npmmirror**（官方 CDN 国内 ECONNRESET 实测；env PLAYWRIGHT_DOWNLOAD_HOST 可覆盖）；
6. **块 main.py 运行时动态加载**，其依赖（openpyxl）必须进 hiddenimports；
7. **输出统一 UTF-8**（entry.py reconfigure）——exe 控制台编码随系统漂移，中文会碎；买家终端乱码提示 `chcp 65001`（Electron 壳阶段消除）。

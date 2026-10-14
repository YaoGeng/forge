# spikes/ — MS-0 端到端验证（技术验证产物，不入主干）

对应 `docs/07-MS0执行计划.md`。本目录代码不被 `apps/ packages/ runtimes/` 引用。

## 环境

```bash
# 本机 `python` 若为 WindowsApps 存根，改用绝对路径：
# PYEXE="$LOCALAPPDATA/Programs/Python/Python312/python.exe"
python -m venv spikes/.venv
spikes/.venv/Scripts/python -m pip install -r spikes/requirements.txt
# 下载挂起时走镜像：PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
spikes/.venv/Scripts/patchright install chromium
```

需要网络可达 `news.ycombinator.com` 与 `hn.algolia.com`；需代理时经环境变量 `HTTPS_PROXY` 注入。

## 三张验收命令（证据归档到 `spikes/evidence/`）

```bash
# T0.1 Patchright 直驱：HN 打开/读取/截图
spikes/.venv/Scripts/python -m pytest spikes/test_browser_link.py -v -s | tee spikes/evidence/t0.1_patchright.log

# T0.2 site_inspect 最小实现：结构报告
spikes/.venv/Scripts/python -m pytest spikes/test_site_inspect.py -v | tee spikes/evidence/t0.2_site_inspect.log
spikes/.venv/Scripts/python spikes/run_t02_evidence.py | tee spikes/evidence/t0.2_evidence.log

# T0.3 手工积木原型：HN 搜索 → Excel 报告
spikes/.venv/Scripts/python -m pytest spikes/test_manual_block.py -v | tee spikes/evidence/t0.3_test.log
spikes/.venv/Scripts/python spikes/run_t03_evidence.py | tee spikes/evidence/t0.3_evidence.log
```

全量回归：`spikes/.venv/Scripts/python -m pytest spikes/ -v`。

T0.1b Browser-Use Agent 冒烟（记录型，需 `OPENAI_API_KEY`）：
`spikes/.venv/Scripts/python spikes/agent_smoke.py spikes/evidence/t0.1_agent_smoke.json`

## 证据

验收输出与产物归档在 `spikes/evidence/`，索引与 MS-0 gate 判定见 `spikes/evidence/EVIDENCE.md`（`*.png` 不入库）。

## 措辞

代码注释与提交信息遵守产品文档 §17 词汇规范（环境标准化 / 站点结构检测 / 检测礼仪口径）。

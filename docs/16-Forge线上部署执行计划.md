# Forge 线上部署执行计划（阶段 1.5，T1.80-T1.86）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 forge-server（FastAPI 认证流水线/注册库/Creator Center 服务端）按《服务器部署标准》接入契约上线 aimServer——`forge.aim8848.com`（43.160.219.44，端口 8041），达成首个公网可达的 Forge 部署。

**Architecture:** 四段推进——①服务化（uvicorn 入口 + /healthz + 环境变量注入 + 生产关 docs）；②PG 载体（生产库 aim-pg/forge，SQLite 路径保留为本地开发载体）；③镜像与 CI（GitHub Actions 构建镜像 + tag 直推部署，服务器不做构建）；④服务器侧 SOP（标准第 8 章十步）与监控备份收尾。

**Tech Stack:** Python 3.12（fastapi/sqlalchemy 已有）+ uvicorn + psycopg3（optional `[pg]`）；Docker（python:3.12-slim，无浏览器依赖——服务器不挂 C2 执行器，`create_app(db_url)` 纯 API 形态）；GitHub Actions；Nginx（infra 容器名寻址 per 标准 5.3 注记）。

**Spec:** 《服务器部署标准》V1.3（桌面 `服务器部署标准/`）第 6 章接入契约六条、第 8 章上线流程、第 10 章安全红线；《数据架构文档》V1.1 §5.2/5.4/9.1；apps/server/README.md（运行面契约）；docs/12（M09/M10 服务端设计）。

**决策记录（2026-10-25，跑通优先裁定，人工可否决）:**
1. **生产载体 = PostgreSQL**（契约第 6 条：`aim-pg:5432` + 专属账号 `forge_app`）。D-M1E.1 的「SQLite v1 载体」口径不变——SQLite 仍是本地开发/测试载体，生产切 PG 属部署选型，经 SQLAlchemy 抽象层落地，CI 加 postgres service 全量回归。
2. **v0 暴露面 = 整站反代 + 全站 Basic Auth**：阶段 1 无买家/应用层鉴权体系（MS-2 才有），匿名公网写接口（提交认证/注册设备/上传报告）风险封死；Creator UI 同域自动携带 Basic 凭据不受影响。生产关 FastAPI /docs /openapi.json（环境变量开关）。后续如需公开只读，改 nginx `limit_except GET` 局部放开（人工可否决本裁定）。
3. **首部署即走 CI tag 链**（zfk 模式：Actions 构建 → `docker save | ssh load` 直推 → compose up → healthz 验证），不手工 SSH 上服务器装镜像；服务器侧一次性动作（DNS/建库/目录/nginx conf/secrets）由用户按命令包执行或授权执行。
4. **端口 8041**（数据架构 5.4「8041 起按 10 递增」，forge 为第 4 个产品）。

## Global Constraints

- 接入契约六条逐条对齐（标准 §6）：容器监听 `0.0.0.0:8041` 映射宿主 `127.0.0.1:8041`；配置全环境变量注入；`GET /healthz` 200；日志 stdout/stderr；无状态（不引入会话存储）；DB 连接 `aim-pg:5432` + `forge_app`。
- 安全红线 R1-R7（标准 §10）逐条不碰：凭据只存服务器 `.env`（600）与 CREDENTIALS.md，**repo 内只放占位符模板**；数据库仅容器网络；不用超级用户。
- 服务器不做构建；本开发机无 Docker——镜像构建与验证全在 GitHub Actions。
- git push 等用户明示「提交/推送」；CI 与部署链在 push 后才可验证。
- 不挂无人值守定时任务（认证/实验红线沿用；本计划无恰一次类实验）。
- 既有 SQLite 测试路径与 spikes 全绿基线不回退（本地 `python` 走 venv 绝对路径）。

## Review Focus

1. **PG 方言陷阱**：`text()` 原生 SQL、JSON 列默认值、DateTime 时区语义——server 测试套件必须对真实 PG 实例全量跑（CI postgres service），禁止只拿 sqlite 绿就宣称 PG 兼容。
2. **healthz 假活**：三层各自验证——FastAPI 路由单测；compose healthcheck 打容器内端口；上线后公网 `https://forge.aim8848.com/healthz`（带 Basic）200。
3. **暴露面漏覆盖**：FastAPI 默认 `/docs` `/openapi.json` `/redoc` 必须在生产关闭（环境变量门控 + 测试断言 404）；nginx 全站 Basic 挂在 server 级，防 location 漏网。
4. **凭据落盘**：`.env`/`admin.htpasswd`/CREDENTIALS.md 值 600 且不进 git、不进日志；repo 模板一律 `<占位符>`。
5. **CI 未跑通即宣告**：deploy.yml 首次必须真实 tag 触发并观察完整日志（build→load→up→healthz curl 200），失败如实上报不重试掩盖。

---

### Task T1.80: 服务入口与 healthz

**Files:**
- Create: `apps/server/forge_server/__main__.py`
- Modify: `apps/server/forge_server/app.py`（healthz 路由 + docs/redoc/openapi 生产开关）
- Modify: `apps/server/pyproject.toml`（uvicorn 依赖）
- Test: `apps/server/tests/test_serve_entry.py`（新建）

**Interfaces:**
- Produces: `python -m forge_server` 进程入口；环境变量 `FORGE_DB_URL`（默认 sqlite:///./forge.db）、`FORGE_PORT`（默认 8041）、`FORGE_HOST`（默认 127.0.0.1）、`FORGE_DATA_DIR`（golden/report 根，默认 tempfile 行为不变）、`FORGE_DOCS`（默认关；=1 开 docs/openapi/redoc）。
- Produces: `GET /healthz` → 200 `{"status":"ok"}`（不查库；进程活着即活）。
- Consumes: `create_app()`（既有，不改签名）。

- [ ] **Step 1: 测试先行**——test_serve_entry.py：①TestClient 断言 `/healthz` 200 且 `{"status":"ok"}`；②默认配置下 `/docs` `/openapi.json` 404；③`FORGE_DOCS=1` 时 200（monkeypatch env 重建 app）；④`_serve_config()` 环境变量解析单测（缺省值/覆盖值）。
- [ ] **Step 2: app.py 改造**——`create_app` 增可选参 `docs: bool = False`，传 `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`（docs=True 走默认）；注册 `/healthz`。
- [ ] **Step 3: `__main__.py`**——读环境变量组装 `create_app(db_url, golden_root=…, report_root=…, docs=…)`，`uvicorn.run(app, host, port)`；`FORGE_DATA_DIR` 存在时 golden/report 根 = `{dir}/golden` `{dir}/reports`（目录自建）。
- [ ] **Step 4: pyproject 加 `uvicorn>=0.29`**，venv 安装（国内镜像源）。
- [ ] **Step 5: 全量 server 测试** `apps/server/.venv`（或既有 venv 路径）`-m pytest apps/server/tests -q` 全绿（含新用例）。
- [ ] **Step 6: 冒烟**——本地起 `python -m forge_server`，curl `127.0.0.1:8041/healthz` 200、`/docs` 404，Ctrl-C 干净退出。
- [ ] **Step 7: Commit** `feat(ms15): 服务入口——python -m forge_server + /healthz + 生产关 docs（env 注入 db/端口/数据根）`

### Task T1.81: PG 载体接入

**Files:**
- Modify: `apps/server/pyproject.toml`（`[project.optional-dependencies] pg = ["psycopg[binary]>=3.1"]`）
- Modify: `apps/server/tests/conftest.py`（db_url fixture 支持 `FORGE_TEST_DB_URL` 覆盖）
- Modify: `apps/server/forge_server/`（方言修整——仅当 PG 全量测试暴露问题时动；预检 `text()` 原生 SQL 用点）
- Test: 既有套件对 PG 实例复跑（CI 内完成；本地无 PG）

**Interfaces:**
- Produces: `FORGE_TEST_DB_URL=postgresql://…` 时全套 server 测试跑 PG；缺省 sqlite 不变。
- Consumes: `make_engine`（既有非 sqlite 分支已跳过 pragma，无需改）。

- [ ] **Step 1: conftest db_url fixture** 读 `FORGE_TEST_DB_URL`（缺省 sqlite 文件路径现状不变）；PG URL 时每测试用独立 schema 或库名后缀（最简：`FORGE_TEST_DB_URL` 带 `{tmp}` 占位替换，或 fixture 里 `CREATE/DROP SCHEMA`；取落地率最高者并在计划执行时记 Ruling）。
- [ ] **Step 2: pyproject optional `[pg]`**；`_ensure_plan_json_column` 的 `ADD COLUMN JSON` 确认 PG 合法（合法，无需改）。
- [ ] **Step 3: 静态预检**——grep server 内 `text(` 与 JSON/DateTime 模型列，列清单进执行 Ruling；发现 sqlite 专用语（`strftime`/`AUTOINCREMENT`/`PRAGMA`）即改方言安全写法。
- [ ] **Step 4: 本地 sqlite 全量回归**全绿（基线不回退）。
- [ ] **Step 5: Commit**（PG 真实例验证在 T1.83 CI 内闭环，本任务不含「已验 PG」宣称）`feat(ms15): PG 载体接入——optional [pg] 驱动 + FORGE_TEST_DB_URL 测试参数化`

### Task T1.82: 镜像与部署工件

**Files:**
- Create: `deploy/Dockerfile`
- Create: `deploy/compose.yml`（模板，真 .env 在服务器）
- Create: `deploy/nginx/forge.conf`（模板）
- Create: `deploy/init-db.sql`（数据架构 9.1 实例化：`forge_app`/`forge` 库，密码占位）
- Create: `deploy/SERVER_STEPS.md`（服务器侧命令包：目录、.env、htpasswd、建库、nginx 装载、DNS、UptimeRobot）

**Interfaces:**
- Produces: 镜像 `forge-backend:<tag>`（python:3.12-slim；COPY `packages/{block-sdk,trace,certifier}/python` + `apps/server`；pip 装 `.[pg]` + 三包；非 root `forge` 用户；EXPOSE 8041；CMD `python -m forge_server`）。
- Consumes: 标准 §6.2 compose 模板（`127.0.0.1:8041:8041`、512M、json-file 10m×3、unless-stopped、infra external 网络）；标准 5.3 注记（`resolver 127.0.0.11` + `set $upstream http://forge-backend:8041`）。

- [ ] **Step 1: Dockerfile**——多阶段可选但取最简单段；层序：先 pyproject 后源码利用缓存；`HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8041/healthz')"`。
- [ ] **Step 2: compose.yml + nginx forge.conf**——server 级 `auth_basic`（全站，决策 2）+ `limit_req zone=api` 挂 `/api/`；证书/htpasswd 路径按标准模板；`/` 与 `/creator` 与 `/api/` 全部反代后端（v0 无独立 www 构建）。
- [ ] **Step 3: init-db.sql + SERVER_STEPS.md**——命令包逐步对应标准第 8 章十步，标注哪些用户做（Cloudflare DNS/UptimeRobot/GitHub secret）、哪些可代做。
- [ ] **Step 4: 静态校验**——`python -c "import yaml,sys;yaml.safe_load(open('deploy/compose.yml'))"`；nginx conf 本地无 nginx，语法核对靠模板比对（真校验在服务器 `nginx -t`，T1.84 步骤）。
- [ ] **Step 5: Commit** `feat(ms15): 部署工件——Dockerfile/compose/nginx conf/建库 SQL/服务器命令包（占位符无凭据）`

### Task T1.83: CI——测试与构建部署链

**Files:**
- Create: `.github/workflows/ci.yml`（push/PR：全量 pytest + server 套件对 postgres service 复跑）
- Create: `.github/workflows/deploy.yml`（tag `v*`：build → save → ssh load → compose up → healthz curl）

**Interfaces:**
- Consumes: `FORGE_TEST_DB_URL=postgresql://postgres:postgres@localhost:5432/forge_test`（service container）；`SERVER_SSH_KEY`/`SERVER_HOST`/部署密钥（用户配 secrets，T1.84）。

- [ ] **Step 1: ci.yml**——job1 spikes 全量（现 venv 依赖装法照 spikes/requirements.txt）；job2 apps/server+packages sqlite；job3 server 套件 `FORGE_TEST_DB_URL` 指 PG service（pg16 容器）——**PG 兼容的正式验证闭环在此**，失败修方言问题回 T1.81 登记。
- [ ] **Step 2: deploy.yml**——on tag v*；build 镜像 `forge-backend:${tag}`；`docker save | ssh deploy@43.160.219.44 docker load`；`ssh … "cd /opt/aim/forge && docker compose -p forge up -d"`；部署后 `curl -u $BASIC https://forge.aim8848.com/healthz` 200 断言；失败即退出非零（不静默）。
- [ ] **Step 3: YAML 本地校验**（python yaml.safe_load × 2）。
- [ ] **Step 4: Commit**（**push 等用户明示**；CI 首跑验证在 push 后）`feat(ms15): CI——pytest 三 job（含 PG service）+ tag 构建直推部署链`

### Task T1.84: 服务器侧上线 SOP（用户配合点）

**Files:**
- Consume: `deploy/SERVER_STEPS.md`（T1.82 产出）
- Modify（用户桌面文档，改动前在汇报中列明）: `服务器部署标准/数据架构文档.md` §5.4 表、`服务器部署标准/服务器部署标准.md` §11.2/11.3

- [ ] **Step 1: 用户侧**——Cloudflare 加 A 记录 `forge → 43.160.219.44` 灰云；GitHub 仓库 secrets 配 `SERVER_SSH_KEY`（新生成 `forge-ci-deploy` 专用密钥，独立于 zfk 可单独吊销）+ 服务器 authorized_keys 加公钥。
- [ ] **Step 2: 服务器侧**（用户贴命令或授权执行）——`mkdir /opt/aim/forge`；写 `.env`（`FORGE_DB_URL=postgresql://forge_app:< openssl rand 生成 >@aim-pg:5432/forge`、`FORGE_DATA_DIR=/opt/aim/forge/data`，600）；`htpasswd` 追加 forge 站点凭据；`aim-pg` 内执行 `init-db.sql`；`backup.sh` DB 清单加 forge；`deploy/nginx/forge.conf` 落 `conf.d/`，`nginx -t && nginx -s reload`。
- [ ] **Step 3: 验证**——`curl -H "Host: forge.aim8848.com" https://127.0.0.1/` 回源通（容器未起前 502 属预期中间态）；端口核查 `ss -tlnp` 仅新增 127.0.0.1:8041。
- [ ] **Step 4: 文档回填**——资源分配表加 forge 行（库/账号/8041）；标准 §11.2 追加 forge 部署记录、§11.3 版本行。

### Task T1.85: 首次 tag 部署 v0.1.0 与全链路验证

- [ ] **Step 1: push**（用户明示后）——main + tag `v0.1.0` 推 origin，观察 ci.yml 三 job 全绿（**PG 兼容正式结论以 job3 为准**）。
- [ ] **Step 2: deploy.yml 首跑**——完整日志核对：build→save→load→up→healthz 200；服务器 `docker ps` 容器 healthy（512M 限）。
- [ ] **Step 3: 公网验证清单**——`https://forge.aim8848.com/healthz` 200（带 Basic）；无 Basic 401；`/docs` 404；`/creator` 200（页面可达）；`GET /api/v1/apps` 200（空列表）；`POST` 无 Basic 401；限速生效（api zone 突发 40 后 503 抽查）；`ss -tlnp` 公网仍仅 22/80/443。
- [ ] **Step 4: 异常处理**——任一步失败：容器日志定位→修复→新 tag 重发；**禁止**跳过验证宣告成功。
- [ ] **Step 5: UptimeRobot 拨测**（用户侧）+ 次日备份文件确认（`/opt/aim/backups/forge/`）。

### Task T1.86: 收口登记

- [ ] **Step 1: docs/06** 新增「阶段 1.5 线上化」条目（部署完成状态、决策记录 1-4、证据指向 CI run 与部署记录）。
- [ ] **Step 2: 台账** `.superpowers/sdd/16-线上部署执行计划/progress.md` 全程 Ruling/finding 补记；commit 收口。
- [ ] **Step 3: 记忆更新**——部署选型记忆改为「用户自有服务器 aim8848.com 已上线，RackNerd/Hetzner 方案作废」。

---

**执行顺序与阻塞点:** T1.80→T1.81→T1.82→T1.83 为本地/仓库工作（可连跑）；T1.84 起需用户配合（DNS/secrets/服务器命令）；push 与 tag 触发等用户明示。

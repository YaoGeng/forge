# forge-server

Forge 认证流水线服务端（M09 编码，docs/12 MS-1E）：CertScheduler 批次礼仪强制、certification_runs 落库、C2 本机执行器、C1 签名报告上传链、抽查重测、详情页初始分 REST API。

## 运行面（/api/v1）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /certifications | 提交认证（subject/version/level/site_tier），排期两时段计划 |
| GET | /certifications/{id} | 认证报告（live/regression 分列、环境、归因、verdict、批次分段） |
| POST | /certifications/devices | C1 设备注册（公钥+指纹；同账号上限 3，重复注册幂等） |
| POST | /certifications/nonce | C1 取 nonce（一次性、TTL 5min、属主绑定设备指纹） |
| POST | /certifications/{id}/report | C1 签名报告上传：验签→nonce 消费→时长下限→golden 拒收→落库→verdict（幂等） |
| GET | /blocks/{name}/versions/{v}/reliability | 详情页初始分：仅 live 口径 + C1 标注 + N + 时间窗；无样本「数据不足」 |
| GET/POST | /certifications/spotcheck/tasks[/{id}/accept] | 抽查任务拉取/接受（服务端随机参数 + 时间窗） |
| WS | /certifications/{id}/stream | 重测流式上报（C10 行协议 + seq 位图断点续传） |

## v1 载体边界（D-M1E.1）

- **SQLAlchemy 2 + SQLite**（`create_all` 建表；Alembic 随 PG16 升级位引入）；模型/查询代码对 SQLite/PostgreSQL 同构，生产位换连接串即迁移。
- **进程内 asyncio 调度循环**（lifespan 启动，1s tick）；「单进程」仅指调度器实例数，并发语义（限频 ≥5s、≤20 次/批次、跨 ≥48h）由礼仪常量强制，不可配置绕过（`etiquette.py`，G10）。
- nonce 存储、上传幂等缓存、抽查抽样均在进程内存（重启丢失为 v1 已知边界）；批次礼仪语义、表结构、REST 契约不因载体放宽。
- 时钟注入点 = `Clock` 协议（生产 wall-clock；测试 FrozenClock）。**批次跨度以真实时钟计，gate 不用假钟。**

## 生产位升级清单（登记缓办）

容器/浏览器集群调度（C2 执行器 v1 = 本机白名单环境，复用 forge_trace `replay.run`）；PostgreSQL + Alembic；Redis/Celery 队列；nonce/幂等缓存持久化；真实副作用站点幂等联测（阶段 1 seed 全部 side_effects=false）；抽查 mismatch 的 delisted 联动（M10 未建）；环境指纹交叉校验（C13 v1 = 单源 sha256 截断）；C9 步骤序列比对的锚身份维度（v1 按 action+步数，replay StepResult 不含 dom_anchor）。

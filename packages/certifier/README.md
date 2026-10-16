# forge-certifier

Forge C1 本机认证器（M09 §3.2 编码，docs/12 MS-1E）：设备注册、nonce 领取、本机 N 次真实运行、ed25519 签名报告上传。**凭证不出本机（G11）**——私钥仅存客户端目录（0600 语义），服务端只见签名报告与公钥。

## 客户端 API

- `DeviceKey.generate()/load(dir)/save(dir)`：ed25519 密钥；`device_fp` = 公钥 sha256[:16]。
- `register_device(http, server_base, creator_id, key) -> device_id`（幂等）。
- `fetch_nonce(http, server_base, device_fp) -> {nonce, expires_at}`（TTL 5 分钟、单次消费）。
- `certify(block_ref, n, params, *, device_key, server_base, browser_factory, runner, http=None, clock=None) -> SignedReport`：阻塞式——取 nonce → N 次真实运行（每 run 一次性会话，即焚）→ 报告（白名单：runs/env_fingerprint/fail_json/durations/network_shape，不含页面内容）→ C7 attestation 签名。
- `CertReportClient.upload(server_base, signed_report, cert_run_id) -> UploadResult`。
- `accept_spotcheck(task, *, block_ref, runner, sender=None)`：接受抽查任务，以**服务端下发的随机参数**执行并逐 step 上送（M09 §6 参数服务端生成）。

## v1 边界

- 会话隔离（C11）：每 run 一次性浏览器会话（patchright 每 run 独立 chromium + 全新 context）+ tempfile profile 目录即焚；safeStorage 私钥保护归 T1.50 Electron 壳。
- attestation 五字段 = M09 §4 逐字：`{nonce, report_hash, env_fingerprint, client_version, ts}`；`report_hash = sha256(canonical_json(report))[:16]`（键排序、无空白）。
- 环境指纹（C13 v1）：sha256(OS + 浏览器主版本 + python 版本 + 网络类型)[:16]；多源交叉校验登记缓办。
- WS 上送传输装配（sender 注入点）由 gate/客户端壳侧接线；流式行协议见 forge-server README。

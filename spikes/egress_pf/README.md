# macOS PF 专用用户出网验证规程（MS-1A T1.02）

> **状态：未实测——待 macOS 硬件。** 本目录全部内容由 AI 依据 M05 §2.2 编写并静态核对，
> 从未在任何 macOS 机器上执行过。首次执行前须逐行人工核对，产出实测报告后方可作为
> MS-1A 双平台报告的 macOS 半边。

## 机制（M05 §2.2，D-1 冻结路线）

组件进程以专用用户 `_forge_comp` 运行；PF 规则对该用户出站默认阻断，仅放行
loopback → 本地代理端口。组件 DNS 一并被阻断（external UDP 53 不放行），
域名解析由代理侧完成——与 Windows 半边的观测口径一致。

## 与四验证点的映射

| 验证点（M05 §2.1） | 本规程对应步骤 |
|---|---|
| ② 代理可达性 | `verify_pf.py --in-policy` 经 `127.0.0.1:<port>` CONNECT 成功 + 代理侧 connect_log 出现原始目标 |
| ③ 绕过尝试被丢弃 | raw socket 直连目标 IP → 阻断；借其他用户身份对照（应放行，登记机制边界）；多网卡逐一 bind 尝试 |
| ④ 性能开销 <10% | `--baseline`（策略前，管理员身份）与 `--in-policy`（策略中，`_forge_comp`）各 30 样本，p95 附加率 |
| 附加：权限最小化 | `--perm-check`：`_forge_comp` 对 `$HOME` 之外关键路径无读权限、shell 为 `/usr/bin/false`、无管理组 |

## 前置

- macOS 12+，sudo 可用；
- Python 3（系统自带即可，verify_pf.py 仅 stdlib）；
- 一个最小 CONNECT 代理（可复用 `spikes/egress_fw/proxy_worker.py`，与平台无关）。

## 执行步骤（runbook）

```bash
# 0) 备份系统 PF 状态（恢复依据，务必留存输出）
sudo pfctl -s rules      | tee pf_rules_backup.txt
sudo pfctl -s info       | tee pf_info_backup.txt

# 1) 建专用用户 + 启用 anchor 规则
./setup_pf.sh <proxy_port>          # 内部逐步回显每条命令

# 2) 启动本地代理（任一终端）
python3 ../egress_fw/proxy_worker.py /tmp/forge_pf_endpoint /tmp/forge_pf_log.json

# 3) 策略前基线（管理员身份跑，策略此时已生效则跳过本步改为先行测量）
python3 verify_pf.py --baseline <proxy_port> hn.algolia.com www.baidu.com | tee baseline.log

# 4) 策略中采样（专用用户身份）
python3 verify_pf.py --in-policy <proxy_port> hn.algolia.com www.baidu.com | tee inpolicy.log

# 5) 权限最小化核查
python3 verify_pf.py --perm-check | tee perm.log

# 6) 恢复（卸载 anchor 规则、删专用用户、对照第 0 步备份确认一致）
./teardown_pf.sh
```

## 恢复纪律（与 Windows 半边 G12 同等）

- `setup_pf.sh` 第一步即备份 PF 规则到时间戳文件；
- `teardown_pf.sh` 逐项还原并 diff 备份；
- 任何一步失败：先 `sudo pfctl -a forge-spike -F all`，再人工核对 `pf_rules_backup.txt`；
- 专用用户删除：`sudo dscl . -delete /Users/_forge_comp`。

## 已知风险（未实测确认项）

1. `pfctl -a forge-spike -f com.forge-spike.pf.conf` 的 anchor 语义在 macOS 版本间有差异；
   若 `-a` 装载不生效，改走主规则集 `pfctl -f`（须先备份 `/etc/pf.conf`，teardown 还原）。
2. `_forge_comp` 的 `udp 53` 是否确被 `block drop out ... user` 规则覆盖，需实测确认
   （预期：是；若否，须显式补一条 block）。
3. WSAEACCES 型「即时拒绝」在 macOS 上的对应表现预期为超时（PF 默认 drop），
   判定口径按 `verify_pf.py` 内注释执行。

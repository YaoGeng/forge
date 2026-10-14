"""MS-1A T1.01-c 诊断窗口：定位「放行规则在场但未穿透默认出站 Block」的失配层。

背景（evidence/t1.01_windows.log 第 3 轮）：程序路径放行规则创建成功且在场，
sidecar 角色进程 outbound 仍 WSAEACCES。本诊断按层排除：
  A. 程序放行（PowerShell cmdlet）→ 测 sidecar 连通
  B. A + TCP/443 端口放行 → 测 sidecar 与组件连通（端口层是否生效）
  C. B + netsh 变体程序放行 → 测 sidecar（cmdlet 语义 vs netsh 语义）
  D. 规则存储回读（Action/Enabled/Program 原文）+ profile 辅助开关 + 活动网络
  E. 全程快照自恢复（G12）

每个连通测试用「pythonw/python 直连 443 的单次尝试」承载，即时失败（WSAEACCES）
不影响窗口时长。总窗口预算 240s，超时立即恢复。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from egress_fw import firewall  # noqa: E402
from egress_fw.probe import tcp_attempt  # noqa: E402

PYTHON = Path(sys.executable).resolve()
PYTHONW = PYTHON.with_name("pythonw.exe")
EVIDENCE_LOG = BASE / "evidence" / "t1.01_diag_allow.log"
WINDOW_BUDGET_S = 240

TARGET_IP = "183.2.172.177"  # www.baidu.com（国内稳定目标，仅 TCP 连通性观测）

_log_fh = None


def log(msg: str) -> None:
    global _log_fh
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    if _log_fh is None:
        EVIDENCE_LOG.parent.mkdir(parents=True, exist_ok=True)
        _log_fh = EVIDENCE_LOG.open("w", encoding="utf-8")
    _log_fh.write(line + "\n")
    _log_fh.flush()


def _connect_as(exe: Path) -> str:
    code = (
        "import sys\n"
        f"sys.path.insert(0, '{BASE.as_posix()}')\n"
        "from egress_fw.probe import tcp_attempt\n"
        "print(tcp_attempt(sys.argv[1], 443, timeout=5))\n"
    )
    proc = subprocess.run(
        [str(exe), "-c", code, TARGET_IP],
        capture_output=True, text=True, timeout=30, cwd=str(BASE),
    )
    return proc.stdout.strip() or f"error:{proc.stderr.strip()[:120]}"


def _ps_dump(runner) -> str:
    lines = []
    lines.append("profile[Name,Enabled,DefaultOutboundAction,AllowLocalFirewallRules,AllowLocalIPsecRules]=")
    lines.append(firewall._ps(
        "Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultOutboundAction,"
        "AllowLocalFirewallRules,AllowLocalIPsecRules | ConvertTo-Json -Compress", runner))
    lines.append("connprofile=")
    lines.append(firewall._ps(
        "Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,NetworkCategory | "
        "ConvertTo-Json -Compress", runner))
    lines.append("stored_rule[Name,Enabled,Direction,Action]=")
    lines.append(firewall._ps(
        "Get-NetFirewallRule -Name 'Forge-Spike-*' -ErrorAction SilentlyContinue | "
        "Select-Object Name,Enabled,Direction,Action | ConvertTo-Json -Compress", runner))
    lines.append("stored_rule_program=")
    lines.append(firewall._ps(
        "Get-NetFirewallRule -Name 'Forge-Spike-*' -ErrorAction SilentlyContinue | "
        "Get-NetFirewallApplicationFilter | Select-Object Name,Program | "
        "ConvertTo-Json -Compress", runner))
    lines.append("globalsettings=")
    lines.append(firewall._ps("netsh advfirewall show globalsettings", runner))
    return "\n".join(lines)


def main() -> int:
    global _log_fh
    window_start = time.time()
    log("[G14] 告知：诊断窗口，出网临时全局阻断，预算 240s，结束自动恢复。")
    runner = firewall._make_runner()
    if not firewall.is_admin(runner):
        log("[exit 5] 非管理员，未做任何变更。")
        return 5

    snapshot = firewall.snapshot_profiles(runner)
    verdict: dict = {}
    restored = False
    try:
        firewall.apply_outbound_block(snapshot, runner)
        results = verdict
        errors: list[str] = []
        verdict["errors"] = errors

        def step(name: str, fn) -> None:
            try:
                results[name] = fn()
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")

        step("stepA_program_allow", lambda: (
            firewall.add_sidecar_allow(str(PYTHONW), runner),
            firewall._ps(f"New-NetFirewallRule -Name Forge-Spike-Allow-Comp -DisplayName Forge-Spike-Allow-Comp "
                         f"-Direction Outbound -Action Allow -Program '{PYTHON}'", runner),
            {
                "pythonw_connect": _connect_as(PYTHONW),
                "python_connect": _connect_as(PYTHON),
            },
        )[2])

        def step_b():
            firewall._ps("New-NetFirewallRule -Name Forge-Spike-Allow-Port443 -DisplayName Forge-Spike-Allow-Port443 "
                         "-Direction Outbound -Action Allow -Protocol TCP -RemotePort 443", runner)
            return {
                "pythonw_connect": _connect_as(PYTHONW),
                "python_connect": _connect_as(PYTHON),
            }

        step("stepB_port_allow", step_b)

        def step_c():
            firewall._ps(f"netsh advfirewall firewall add rule name=\"Forge-Spike-Allow-Netsh\" "
                         f"dir=out action=allow program=\"{PYTHONW}\" enable=yes", runner)
            return {"pythonw_connect": _connect_as(PYTHONW)}

        step("stepC_netsh_variant", step_c)
        step("stepD_storage_dump", lambda: _ps_dump(runner))
    finally:
        restored, errors = firewall_restore(snapshot, runner)
        log(f"恢复: restored={restored} errors={errors}")
        if not restored:
            for name, actions in snapshot.items():
                log(f"  手动: Set-NetFirewallProfile -Name {name} -DefaultInboundAction {actions['in']} -DefaultOutboundAction {actions['out']}")

    verdict["restored"] = restored
    verdict["window_seconds"] = round(time.time() - window_start)
    log("诊断矩阵 JSON:")
    log(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if restored else 8


def firewall_restore(snapshot, runner):
    errors: list[str] = []
    try:
        firewall.restore_profiles(snapshot, runner)
    except Exception as exc:
        errors.append(f"restore_profiles: {exc}")
    try:
        firewall.delete_spike_rules(runner)
    except Exception as exc:
        errors.append(f"delete_spike_rules: {exc}")
    try:
        matched = firewall.policy_matches(snapshot, runner)
    except Exception as exc:
        errors.append(f"policy_matches: {exc}")
        matched = False
    return matched and not errors, errors


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback

        log("诊断脚本异常（栈如下）:")
        log(traceback.format_exc())
        raise

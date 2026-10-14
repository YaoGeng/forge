"""Windows 防火墙出站白名单封装（M05 §2.1 spike 验证用）。

全部经 PowerShell *NetFirewall* cmdlet（属性名与系统区域设置无关）；
所有命令经可注入 runner 执行，离线测试用 fake runner 断言命令构造。
仅做四件事：管理员预检、快照、各 profile 出站阻断+sidecar 放行、恢复与校验。
"""
import json
import subprocess
from collections.abc import Callable

Runner = Callable[[list[str]], subprocess.CompletedProcess]

RULE_NAME = "Forge-Spike-Allow-Sidecar"
RULE_WILDCARD = "Forge-Spike-*"


def _make_runner() -> Runner:
    def run(args: list[str]) -> subprocess.CompletedProcess:
        # 终审 Important-1：无超时的 PowerShell 调用会让 G14 看门狗与 finally
        # 恢复一起卡死；run 超时会 kill 子进程后抛 TimeoutExpired
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(args, returncode=124, stdout="", stderr=str(exc))

    return run


def _ps(script: str, runner: Runner) -> str:
    # cmdlet 错误默认不改变退出码（R6）——前置 EAP=Stop 让失败可被 rc 捕获
    proc = runner(["powershell", "-NoProfile", "-Command", "$ErrorActionPreference='Stop'; " + script])
    if proc.returncode != 0:
        raise RuntimeError(
            f"powershell failed rc={proc.returncode}: {proc.stdout!r} {proc.stderr!r}"
        )
    return proc.stdout


def is_admin(runner: Runner) -> bool:
    out = _ps(
        "([Security.Principal.WindowsPrincipal]"
        "[Security.Principal.WindowsIdentity]::GetCurrent()"
        ").IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)",
        runner,
    )
    return out.strip().lower() == "true"


def snapshot_profiles(runner: Runner) -> dict[str, dict[str, str]]:
    # Action 属性是 NetSecurity.Action 枚举（NotConfigured=0/Allow=2/Block=4），
    # ConvertTo-Json 会序列化成底层数字——必须先 ToString() 归一为字符串。
    raw = _ps(
        "Get-NetFirewallProfile | Select-Object Name,"
        "@{n='DefaultInboundAction';e={$_.DefaultInboundAction.ToString()}},"
        "@{n='DefaultOutboundAction';e={$_.DefaultOutboundAction.ToString()}}"
        " | ConvertTo-Json -Compress",
        runner,
    )
    data = json.loads(raw)
    if isinstance(data, dict):  # 单 profile 时 PowerShell 不返回数组
        data = [data]
    return {
        item["Name"]: {"in": item["DefaultInboundAction"], "out": item["DefaultOutboundAction"]}
        for item in data
    }


def apply_outbound_block(snapshot: dict[str, dict[str, str]], runner: Runner) -> None:
    for name, actions in snapshot.items():
        _ps(
            f"Set-NetFirewallProfile -Name {name} "
            f"-DefaultInboundAction {actions['in']} -DefaultOutboundAction Block",
            runner,
        )


def _q(value: str) -> str:
    """PowerShell 单引号串转义（路径含撇号时不被截断）。"""
    return "'" + value.replace("'", "''") + "'"


def add_sidecar_allow(program: str, runner: Runner) -> None:
    _ps(
        f"New-NetFirewallRule -Name {RULE_NAME} -DisplayName {RULE_NAME} "
        f"-Direction Outbound -Action Allow -Program {_q(program)}",
        runner,
    )


def delete_spike_rules(runner: Runner) -> None:
    _ps(f"Remove-NetFirewallRule -Name '{RULE_WILDCARD}' -ErrorAction SilentlyContinue", runner)


def allow_rule_present(runner: Runner) -> bool:
    out = _ps(
        f"(Get-NetFirewallRule -Name {RULE_NAME} -ErrorAction SilentlyContinue | "
        "Measure-Object).Count",
        runner,
    )
    return out.strip() == "1"


def restore_profiles(snapshot: dict[str, dict[str, str]], runner: Runner) -> None:
    for name, actions in snapshot.items():
        _ps(
            f"Set-NetFirewallProfile -Name {name} "
            f"-DefaultInboundAction {actions['in']} -DefaultOutboundAction {actions['out']}",
            runner,
        )


def policy_matches(snapshot: dict[str, dict[str, str]], runner: Runner) -> bool:
    return snapshot_profiles(runner) == snapshot

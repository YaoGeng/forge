"""MS-1A T1.01-c 诊断 v3：程序放行规则失配的根因定位。

v2 结论（t1.01_diag_allow.log）：默认出站 Block 下，
- 程序路径 Allow（cmdlet，venv pythonw / venv python）→ 均未穿透（WSAEACCES）；
- TCP/443 端口 Allow → 立即穿透（任意程序）。
本版按「失配的是程序条件本身，还是特定镜像」分四路对照：
  E1  venv pythonw 程序放行（-Protocol TCP 显式）
  E2  venv pythonw 程序+端口组合放行
  E3  curl.exe（系统镜像）程序放行
  E4  基础解释器 pythonw.exe 程序放行
  E5  端口放行（对照，应全通）
  D   存储规则回读（每条独立容错）+ profile 辅助开关
窗口预算 240s，快照自恢复。
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
BASE_PY = PYTHON.resolve()  # venv launcher 同目录
BASE_INSTALL_PYW = PYTHONW  # venv pythonw.exe
BASE_HOME_PYW = Path(sys.base_prefix) / "pythonw.exe"  # 基础安装目录解释器
CURL = Path("C:/Windows/System32/curl.exe")
TARGET_IP = "183.2.172.177"
EVIDENCE_LOG = BASE / "evidence" / "t1.01_diag_allow2.log"
WINDOW_BUDGET_S = 240

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


def _snippet(exe_role: str) -> str:
    return (
        "import sys\n"
        f"sys.path.insert(0, '{BASE.as_posix()}')\n"
        "from egress_fw.probe import tcp_attempt\n"
        "print(tcp_attempt(sys.argv[1], 443, timeout=5))\n"
    )


def _connect(exe: Path) -> str:
    proc = subprocess.run(
        [str(exe), "-c", _snippet(str(exe)), TARGET_IP],
        capture_output=True, text=True, timeout=30, cwd=str(BASE),
    )
    return proc.stdout.strip() or f"error:{proc.stderr.strip()[:120]}"


def _curl_connect() -> str:
    proc = subprocess.run(
        [str(CURL), "-s", "-o", "NUL", "--connect-timeout", "6", f"https://{TARGET_IP}/"],
        capture_output=True, text=True, timeout=30,
    )
    return f"rc={proc.returncode}"


def _dump_one(runner, name: str, script: str) -> dict:
    try:
        return {name: firewall._ps(script, runner).strip()}
    except Exception as exc:
        return {name: f"ERROR: {exc}"}


def _dump(runner) -> dict:
    out: dict = {}
    out.update(_dump_one(runner, "profiles", (
        "Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultOutboundAction,"
        "AllowLocalFirewallRules,AllowLocalIPsecRules | ConvertTo-Json -Compress")))
    out.update(_dump_one(runner, "rules", (
        "Get-NetFirewallRule -Name 'Forge-Spike-*' -ErrorAction SilentlyContinue | "
        "Select-Object Name,Enabled,Direction,Action,Profile | ConvertTo-Json -Compress")))
    out.update(_dump_one(runner, "app_filters", (
        "Get-NetFirewallRule -Name 'Forge-Spike-*' -ErrorAction SilentlyContinue | "
        "Get-NetFirewallApplicationFilter | Select-Object Name,Program | "
        "ConvertTo-Json -Compress")))
    out.update(_dump_one(runner, "conn_profile", (
        "Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,NetworkCategory | "
        "ConvertTo-Json -Compress")))
    return out


def main() -> int:
    global _log_fh
    window_start = time.time()
    log("[G14] 告知：诊断窗口 v3，出网临时全局阻断，预算 240s，结束自动恢复。")
    runner = firewall._make_runner()
    if not firewall.is_admin(runner):
        log("[exit 5] 非管理员，未做任何变更。")
        return 5

    snapshot = firewall.snapshot_profiles(runner)
    verdict: dict = {"errors": []}
    restored = False
    try:
        firewall.apply_outbound_block(snapshot, runner)
        errors: list[str] = verdict["errors"]

        def step(name, fn):
            try:
                verdict[name] = fn()
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")

        def e1():
            firewall._ps(f"New-NetFirewallRule -Name Forge-Spike-E1 -DisplayName E1 "
                         f"-Direction Outbound -Action Allow -Protocol TCP "
                         f"-Program '{PYTHONW}'", runner)
            return {"venv_pythonw": _connect(PYTHONW)}
        step("E1_program_tcp_venv", e1)

        def e2():
            firewall._ps(f"New-NetFirewallRule -Name Forge-Spike-E2 -DisplayName E2 "
                         f"-Direction Outbound -Action Allow -Protocol TCP -RemotePort 443 "
                         f"-Program '{PYTHONW}'", runner)
            return {"venv_pythonw": _connect(PYTHONW)}
        step("E2_program_plus_port_venv", e2)

        def e3():
            firewall._ps(f"New-NetFirewallRule -Name Forge-Spike-E3 -DisplayName E3 "
                         f"-Direction Outbound -Action Allow -Protocol TCP "
                         f"-Program '{CURL}'", runner)
            return {"curl": _curl_connect()}
        step("E3_program_curl", e3)

        def e4():
            firewall._ps(f"New-NetFirewallRule -Name Forge-Spike-E4 -DisplayName E4 "
                         f"-Direction Outbound -Action Allow -Protocol TCP "
                         f"-Program '{BASE_HOME_PYW}'", runner)
            return {"base_pythonw": _connect(BASE_HOME_PYW)}
        step("E4_program_base_pythonw", e4)

        def e5():
            firewall._ps("New-NetFirewallRule -Name Forge-Spike-E5 -DisplayName E5 "
                         "-Direction Outbound -Action Allow -Protocol TCP -RemotePort 443", runner)
            return {"venv_pythonw": _connect(PYTHONW), "curl": _curl_connect()}
        step("E5_port_control", e5)

        step("D_storage_dump", lambda: _dump(runner))
    finally:
        restored, errors = firewall_restore(snapshot, runner)
        log(f"恢复: restored={restored} errors={errors}")

    verdict["restored"] = restored
    verdict["window_seconds"] = round(time.time() - window_start)
    log("诊断矩阵 v3 JSON:")
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

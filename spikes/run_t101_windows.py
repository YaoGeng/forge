"""MS-1A T1.01-c：Windows 防火墙出站白名单四验证点实机电池。

特权窗口纪律（计划 G12/G13/G14）：
- 变更前快照各 profile 策略；finally 强制恢复 + 快照一致性校验；恢复失败 exit 8 附手动指引；
- 规则名仅 Forge-Spike 前缀，不留其他持久配置；禁止创建用户/装驱动/改 hosts；
- 管理员预检前置：非管理员打印精确指引后 exit 5；
- 启动即打印窗口告知与时间戳；全程 transcript 自归档 evidence/t1.01_windows.log
  （Ruling R4：提权进程无管道，验收日志由驱动自写，不再用 tee 双写同文件）。

角色映射：pythonw.exe（venv）= sidecar（白名单内，代理宿主）；
python.exe（venv）= 组件进程角色（白名单外，被阻断方，含其子/孙进程）。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from egress_fw import firewall  # noqa: E402
from egress_fw.probe import delta_pct, handshake_ttfb_ms, percentile, tcp_attempt  # noqa: E402

TARGET_CANDIDATES = ("hn.algolia.com", "www.baidu.com", "example.com")
SAMPLES = 30
PYTHON = Path(sys.executable).resolve()
# R8：venv launcher 镜像（.venv/Scripts/pythonw.exe）的程序放行规则在 WFP 不匹配
# （diag v2/v3 实证：同规则对基础安装镜像/curl 生效）；sidecar 角色改用基础安装
# pythonw.exe（E4 实证放行生效）。生产注记：平台应自带私有解释器安装，使被放行
# 镜像不与用户共享。
SIDECAR_PYW = (Path(sys.base_prefix) / "pythonw.exe").resolve()
EVIDENCE_LOG = BASE / "evidence" / "t1.01_windows.log"

PROXY_WAIT_S = 10
CONNECT_TIMEOUT_S = 15
WINDOW_BUDGET_S = 600  # G14：窗口硬预算，超时立即中止电池并走恢复

_log_fh = None
_deadline = float("inf")


def _tick() -> None:
    if time.time() > _deadline:
        raise TimeoutError("window budget exceeded（G14 看门狗触发，立即恢复）")


def _is_blocked(result: str | None) -> bool:
    """R7：本机阻断签名是 connect() 即时 WSAEACCES；口径 = 命中网络阻断签名。

    终审 Important-2：仅认三类网络阻断观测（timeout/refused/error:PermissionError）；
    其余 error:*（子进程超时/派生失败等基础设施故障）与 None 一律不算阻断——
    宁可判「未成立」也不引入假阳性。对照组（策略前）须另行校验为 connected。
    """
    return result in ("timeout", "refused", "error:PermissionError")


def log(msg: str) -> None:
    global _log_fh
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    if _log_fh is None:
        EVIDENCE_LOG.parent.mkdir(parents=True, exist_ok=True)
        _log_fh = EVIDENCE_LOG.open("w", encoding="utf-8")
    _log_fh.write(line + "\n")
    _log_fh.flush()


def _manual_restore_lines(snapshot: dict) -> list[str]:
    lines = ["[手动恢复指引]（管理员终端逐条执行）:"]
    for name, actions in snapshot.items():
        lines.append(
            f"  powershell -Command \"Set-NetFirewallProfile -Name {name} "
            f"-DefaultInboundAction {actions['in']} -DefaultOutboundAction {actions['out']}\""
        )
    lines.append("  powershell -Command \"Remove-NetFirewallRule -Name 'Forge-Spike-*'\"")
    return lines


def _safe_restore(snapshot: dict, runner) -> tuple[bool, list[str]]:
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


def _curl_direct(host: str) -> int:
    env = {
        k: v
        for k, v in os.environ.items()
        if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")
    }
    proc = subprocess.run(
        ["curl", "-s", "-o", "NUL", "--connect-timeout", "8", f"https://{host}/"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return proc.returncode


def _local_ipv4s() -> list[str]:
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith("127."))


def _bound_attempt(source_ip: str, ip: str, timeout: float = 5.0) -> str:
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.bind((source_ip, 0))
        sock.connect((ip, 443))
        return "connected"
    except socket.timeout:
        return "timeout"
    except OSError as exc:
        return f"error:{type(exc).__name__}"
    finally:
        sock.close()


def _tree_snippet() -> str:
    # 组件子进程与孙进程各做一次直连判定（进程树继承阻断的子/孙两级证据）。
    # 路径一律 posix 斜杠：非 raw 字符串里 \U 会被当 unicode 转义（R6 前车之鉴）
    base = BASE.as_posix()
    return (
        "import subprocess, sys\n"
        f"sys.path.insert(0, '{base}')\n"
        "from egress_fw.probe import tcp_attempt\n"
        "ip = sys.argv[1]\n"
        "child = tcp_attempt(ip, 443, timeout=5)\n"
        "code = (\n"
        f"    \"import sys; sys.path.insert(0, '{base}');\"\n"
        "    \"from egress_fw.probe import tcp_attempt;\"\n"
        "    \"print(tcp_attempt(sys.argv[1], 443, timeout=5))\"\n"
        ")\n"
        "g = subprocess.run([sys.executable, '-c', code, ip], capture_output=True, text=True)\n"
        "grand = g.stdout.strip() or 'error:' + g.stderr.strip()[:80]\n"
        "print('child:' + child)\n"
        "print('grandchild:' + grand)\n"
    )


def _single_attempt_snippet() -> str:
    base = BASE.as_posix()
    return (
        "import sys\n"
        f"sys.path.insert(0, '{base}')\n"
        "from egress_fw.probe import tcp_attempt\n"
        "print(tcp_attempt(sys.argv[1], 443, timeout=5))\n"
    )


def _run_snippet(exe: Path, snippet: str, ip: str, timeout_s: int) -> str:
    proc = subprocess.run(
        [str(exe), "-c", snippet, ip],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        cwd=str(BASE),
    )
    return proc.stdout.strip() or f"error:{proc.stderr.strip()[:120]}"


def _wait_endpoint(endpoint_file: Path) -> str | None:
    deadline = time.time() + PROXY_WAIT_S
    while time.time() < deadline:
        try:
            endpoint = endpoint_file.read_text(encoding="utf-8").strip()
            host, _, port = endpoint.rpartition(":")
            with socket.create_connection((host, int(port)), timeout=2):
                return endpoint
        except (OSError, ValueError):
            time.sleep(0.3)
    return None


def _read_connect_log(path: Path, want_hosts: list[str]) -> list[str]:
    deadline = time.time() + 10
    entries: list[str] = []
    while time.time() < deadline:
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
            if entries and all(any(h in e for e in entries) for h in want_hosts):
                return entries
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    return entries


def _battery(
    targets: list[tuple[str, str]],
    endpoint: str,
    baseline: dict[str, list[float]],
    pre_ctrl: dict[str, str],
    curl_ctrl: dict[str, int],
    connect_log_file: Path,
) -> dict:
    results: dict = {
        "vp1": {},
        "vp1_block": True,
        "vp2_proxy": True,
        "proxy_saw_targets": None,
        "vp3": {},
        "vp4": {"per_target": {}, "pass": True},
    }
    tree = _tree_snippet()
    single = _single_attempt_snippet()
    want_hosts = []

    for host, ip in targets:
        want_hosts.append(f"{host}:443")

        # VP1 进程树继承阻断（子/孙两级，对照 pre_ctrl 的 connected）
        _tick()
        try:
            out = _run_snippet(PYTHON, tree, ip, timeout_s=90)
            lines = dict(
                item.split(":", 1) for item in out.splitlines() if ":" in item
            )
        except Exception as exc:
            lines = {"child": f"error:{exc}", "grandchild": "-"}
        child_res = lines.get("child")
        grand_res = lines.get("grandchild")
        control_ok = pre_ctrl[ip] == "connected"  # 终审 Important-2：对照组失效则不判阻断
        blocked = control_ok and _is_blocked(child_res) and _is_blocked(grand_res)
        results["vp1"][host] = {
            "pre_policy": pre_ctrl[ip],
            "control_ok": control_ok,
            "child": child_res,
            "grandchild": grand_res,
            "blocked": blocked,
        }
        if not blocked:
            results["vp1_block"] = False

        # VP4 经代理采样（窗口内；成败同时供 VP2 判定；连续 3 失败快速失败省窗口）
        samples: list[float | None] = []
        consec_fail = 0
        for i in range(SAMPLES):
            _tick()
            try:
                samples.append(handshake_ttfb_ms(host, proxy_endpoint=endpoint, timeout=CONNECT_TIMEOUT_S))
                consec_fail = 0
            except OSError as exc:
                samples.append(None)
                consec_fail += 1
                log(f"  采样失败 {host}({i + 1}/{SAMPLES}): {exc}")
                if consec_fail >= 3:
                    log(f"  快速失败: {host} 连续 3 次采样失败，跳过剩余样本")
                    break
        ok = [s for s in samples if s is not None]
        d_p95 = percentile(baseline[host], 0.95)
        target_ok = len(ok) == SAMPLES
        delta = delta_pct(d_p95, percentile(ok, 0.95)) if ok else None
        passed = bool(target_ok and delta is not None and delta < 10.0)
        results["vp4"]["per_target"][host] = {
            "direct_p95_ms": round(d_p95, 1),
            "proxy_p95_ms": round(percentile(ok, 0.95), 1) if ok else None,
            "delta_pct": round(delta, 2) if delta is not None else None,
            "samples_ok": f"{len(ok)}/{SAMPLES}",
            "fast_fail": consec_fail >= 3,
            "pass": passed,
        }
        if not passed:
            results["vp4"]["pass"] = False
        if len(ok) < 3:
            results["vp2_proxy"] = False

    # VP2 代理收到原始目标
    entries = _read_connect_log(connect_log_file, want_hosts)
    results["proxy_saw_targets"] = bool(entries) and all(
        any(h in e for e in entries) for h in want_hosts
    )
    results["connect_log_sample"] = entries[:5]

    # VP3 直连绕过尝试（驱动进程即组件进程角色）
    host0, ip0 = targets[0]
    alt_ips = [a for a in _local_ipv4s() if a != ip0]
    results["vp3"] = {
        "raw_socket_direct": {ip: tcp_attempt(ip) for _, ip in targets},
        "curl_direct": {
            "pre_policy_rc": curl_ctrl[host0],
            "in_policy_rc": _curl_direct(host0),
            "note": "非 0 即未连通（6=DNS 失败 7=连接失败 28=超时）",
        },
        "borrowed_whitelist_demo": {
            "note": "白名单按镜像路径生效：sidecar 镜像（基础安装 pythonw.exe，生产应为平台私有解释器安装）放行，组件镜像不放行（R8）",
            "result": _run_snippet(SIDECAR_PYW, single, ip0, timeout_s=30),
        },
        "alt_nic": (
            {src: _bound_attempt(src, ip0) for src in alt_ips[:3]}
            if alt_ips
            else "single-nic N/A"
        ),
    }
    return results


def main() -> int:
    global _log_fh, _deadline
    window_start = time.time()
    _deadline = window_start + WINDOW_BUDGET_S
    log(f"[G14] 告知：本机出网将临时全局阻断，硬预算 {WINDOW_BUDGET_S}s，结束自动恢复。")
    log(f"窗口开始时间: {time.strftime('%Y-%m-%dT%H:%M:%S')}")

    try:
        runner = firewall._make_runner()
        if not firewall.is_admin(runner):
            log("[exit 5] 当前 shell 非管理员，防火墙未做任何变更。")
            log("请以管理员身份运行一次: ")
            log(f"  cd /d {Path.cwd()} && \"{PYTHON}\" \"{Path(__file__).resolve()}\"")
            log("或启用 系统设置 > 开发者选项 > sudo 后重试。")
            return 5
        if not SIDECAR_PYW.exists():
            log(f"[exit 9] sidecar 解释器缺失: {SIDECAR_PYW}")
            return 9

        # ② 选目标（策略未变，兼作可达性预检与 DNS 预解析）
        targets: list[tuple[str, str]] = []
        for host in TARGET_CANDIDATES:
            if len(targets) >= 2:
                break
            try:
                ms = handshake_ttfb_ms(host, timeout=10)
                ip = socket.gethostbyname(host)
                targets.append((host, ip))
                log(f"目标可达: {host} ({ip}) 首样 {ms:.0f}ms")
            except OSError as exc:
                log(f"目标不可达，跳过: {host} ({exc})")
        if not targets:
            log("[exit 6] 全部候选目标不可达。")
            return 6

        # ③ 基线与对照（策略未变；网络劣化时逐样本容错，坏样计入 direct_ok）
        baseline: dict[str, list[float]] = {}
        for host, _ in targets:
            samples: list[float] = []
            for _ in range(SAMPLES):
                _tick()
                try:
                    samples.append(handshake_ttfb_ms(host, timeout=8))
                except OSError as exc:
                    log(f"  基线采样失败 {host}: {exc}")
            if not samples:
                log(f"[exit 6] 基线全失败: {host}")
                return 6
            baseline[host] = samples
            log(f"基线完成: {host} ok={len(samples)}/{SAMPLES} p95={percentile(samples, 0.95):.0f}ms")
        pre_ctrl = {ip: tcp_attempt(ip) for _, ip in targets}
        curl_ctrl = {host: _curl_direct(host) for host, _ in targets}
        log(f"对照（策略前）: 直连={pre_ctrl} curl_rc={curl_ctrl}")

        # ④ sidecar（白名单内角色）
        tmpdir = Path(tempfile.mkdtemp(prefix="forge-t101-"))
        endpoint_file = tmpdir / "endpoint.txt"
        connect_log_file = tmpdir / "connect_log.json"
        worker = subprocess.Popen(
            [
                str(SIDECAR_PYW),
                str(BASE / "egress_fw" / "proxy_worker.py"),
                str(endpoint_file),
                str(connect_log_file),
            ]
        )
        endpoint = _wait_endpoint(endpoint_file)
        if endpoint is None:
            worker.terminate()
            log("[exit 7] 归因 proxy_not_listening: sidecar 未在期限内监听（非机制失败）。")
            return 7
        log(f"sidecar 就绪: {endpoint}")

        # ⑤-⑦ 防火墙变更 + 电池 + 恢复（外层 finally 兜底 worker 资源，终审 M4）
        restored = False
        restore_errors: list[str] = []
        results: dict | None = None
        failure: str | None = None
        try:
            # 防火墙变更（快照先行；finally 恢复）
            snapshot = firewall.snapshot_profiles(runner)
            log(f"快照: {json.dumps(snapshot)}")
            try:
                firewall.apply_outbound_block(snapshot, runner)
                firewall.add_sidecar_allow(str(SIDECAR_PYW), runner)
                if not firewall.allow_rule_present(runner):
                    raise RuntimeError("放行规则未在场（New-NetFirewallRule 未生效）")
                now = firewall.snapshot_profiles(runner)
                if any(v["out"] != "Block" for v in now.values()):
                    raise RuntimeError(f"出站策略未生效: {now}")
                log("防火墙已变更: 各 profile 出站默认 Block，仅放行 sidecar。")

                # ⑥ 验证电池
                results = _battery(targets, endpoint, baseline, pre_ctrl, curl_ctrl, connect_log_file)
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
                log(f"电池执行异常: {failure}")
            finally:
                restored, restore_errors = _safe_restore(snapshot, runner)
                log(f"防火墙恢复: restored={restored} errors={restore_errors}")
                if not restored:
                    for line in _manual_restore_lines(snapshot):
                        log(line)
        finally:
            worker.terminate()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
            shutil.rmtree(tmpdir, ignore_errors=True)

        # ⑧ 汇总判定
        window_seconds = round(time.time() - window_start)
        verdict = {
            "targets": [f"{host}({ip})" for host, ip in targets],
            "vp1_block": bool(results and results["vp1_block"]),
            "vp1_detail": results["vp1"] if results else None,
            "vp2_proxy": bool(results and results["vp2_proxy"]),
            "proxy_saw_targets": bool(results and results["proxy_saw_targets"]),
            "vp3": results["vp3"] if results else None,
            "vp4": results["vp4"] if results else None,
            "failure": failure,
            "restored": restored,
            "window_seconds": window_seconds,
        }
        log("判定 JSON:")
        log(json.dumps(verdict, ensure_ascii=False, indent=2))
        log(f"窗口结束时间: {time.strftime('%Y-%m-%dT%H:%M:%S')}（历时 {window_seconds}s）")

        if not restored:
            return 8
        # R9：M05 §2.1② 的「代理收到原始目标」入 exit 门（终审 M3）
        if failure or not (
            verdict["vp1_block"]
            and verdict["vp2_proxy"]
            and verdict["proxy_saw_targets"]
            and verdict["vp4"]["pass"]
        ):
            return 7
        return 0
    finally:
        if _log_fh is not None:
            _log_fh.close()
            _log_fh = None


if __name__ == "__main__":
    raise SystemExit(main())

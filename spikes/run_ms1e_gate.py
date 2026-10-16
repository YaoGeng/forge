"""MS-1E gate 运行器（docs/12 §5 T1.35；触网，两段式跨 ≥48h 真实时钟，不用假钟）。

--segment 1：C2（录 hn.algolia 轨迹+golden → 提交认证 → 时段一 10 次真实运行落库）；
             C1（录 saucedemo 登录轨迹+golden → 设备注册 → 时段一 10 次 → 签名上传 n=10）。
--segment 2：≥48h 真实时钟后：C2 时段二 10 次 → N=20 → verdict 出档；
             C1 时段二 10 次 → 二次签名上传 n=20 → verdict + reliability API 校验。
两段命令幂等（--segment 2 可重复执行至成功）；证据写 spikes/evidence/t1.35_seg*.{json,log}。

C2 seed 站点说明：计划 C12 原名 baidu_search_probe，因 baidu AI 首页改版（MS-1D C1-R2
实证并换站登记）按 docs/12 §7 风险处置换 hn.algolia.com（medium 档同链路）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for rel in (
    "packages/trace/python",
    "packages/proto/python",
    "packages/block-sdk/python",
    "packages/certifier/python",
    "apps/server",
):
    p = _ROOT / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient

from forge_block_sdk import lint, validate_block_dir
from forge_certifier.certify import CertReportClient, certify
from forge_certifier.device import DeviceKey, register_device
from forge_trace import RecordingsStore, Recorder, collect_golden, validate_golden_no_raw
from forge_trace.patchright_browser import PatchrightBrowser

from forge_server.app import create_app
from forge_server.models import CertificationRun
from forge_server.sandbox import C2Executor, TraceRunner, scheduler_hook

EVIDENCE = _ROOT / "spikes" / "evidence"
STORE = EVIDENCE / "ms1e_store"
SEEDS = _ROOT / "spikes" / "seed_blocks"
SERVER = "http://test"
SEGMENT_RUNS = 10
DRIVE_TIMEOUT_S = 60 * 40  # 单段驱动上限（10 次真实运行 + 限频余量）


def script_c2(port) -> None:
    port.goto("https://hn.algolia.com/?q=python")
    port.wait_selector(".hits li", 15_000)
    time.sleep(1.5)
    port.goto("https://hn.algolia.com/?q=nodejs")
    port.wait_selector(".hits li", 15_000)
    time.sleep(1.5)


def script_c1(port) -> None:
    # 完整真实流：登录 → 库存 → 商品详情（时长须真实落在 ≥5s/run 下限之上）
    port.goto("https://www.saucedemo.com/")
    port.wait_selector("#user-name", 15_000)
    time.sleep(1.0)
    port.fill("#user-name", "standard_user")
    port.fill("#password", "secret_sauce")
    port.click("#login-button")
    port.wait_selector(".inventory_list", 15_000)
    time.sleep(1.5)
    port.click(".inventory_item_name")
    port.wait_selector(".inventory_details_container", 15_000)
    time.sleep(1.5)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict:
    p = STORE / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_state(state: dict) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_trace(store: RecordingsStore, state: dict, key: str, host: str, script) -> str:
    """录制幂等：state 已有 ref 直接复用（gate 两段/重跑不重录）；瞬时网络抖动重试 3 次。"""
    ref = state.get("trace_refs", {}).get(key)
    if ref:
        return ref
    last_exc: Exception | None = None
    for attempt in range(3):
        browser = PatchrightBrowser()
        try:
            rec = Recorder(store, lambda: browser)
            session = rec.record.start(host)
            script(session.port)
            ref = rec.record.stop()
            break
        except Exception as exc:
            last_exc = exc
            print(f"  [record] {key} 第{attempt + 1}次失败：{type(exc).__name__}，重试", flush=True)
            time.sleep(5 * (attempt + 1))
        finally:
            browser.close()
    if ref is None:
        raise RuntimeError(f"录制失败（3 次）：{key}") from last_exc
    golden = collect_golden(ref, store=store, environment_fingerprint="ms1e-gate")
    errors = validate_golden_no_raw(golden)
    if errors:
        raise RuntimeError(f"golden 脱敏泄漏 {key}: {errors}")
    state.setdefault("trace_refs", {})[key] = ref
    save_state(state)
    return ref


def ensure_device(client: TestClient, state: dict) -> DeviceKey:
    key_dir = STORE / "client_keys"
    fp = state.get("device_fp")
    if fp and (key_dir / "device_key.pem").exists():
        return DeviceKey.load(key_dir)
    key = DeviceKey.generate()
    key.save(key_dir)
    register_device(client, SERVER, "gate-creator", key)
    state["device_fp"] = key.device_fp
    save_state(state)
    return key


def drive_scheduler(sched, target_n: int, run_id: int) -> dict:
    """真实时钟逐 tick 驱动到目标 N；礼仪（≥5s 间隔/时段跨度）由调度器层强制。"""
    t0 = time.monotonic()
    last_n = -1
    while time.monotonic() - t0 < DRIVE_TIMEOUT_S:
        sched.tick()
        with sched.session_factory() as s:
            row = s.get(CertificationRun, run_id)
            n = row.n
            if n != last_n:
                print(f"  [drive] n={n}/{target_n} verdict={row.verdict} t={now_iso()}", flush=True)
                last_n = n
            if n >= target_n:
                return {
                    "n": row.n, "pass": row.pass_count,
                    "live_pass_rate": row.live_pass_rate,
                    "regression_pass_rate": row.regression_pass_rate,
                    "verdict": row.verdict,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                }
        time.sleep(2)
    raise TimeoutError(f"驱动超时：n 未达 {target_n}")


def run_c2_segment(segment: int, state: dict) -> dict:
    store = RecordingsStore(STORE)
    ref = ensure_trace(store, state, "c2", "hn.algolia.com", script_c2)
    block_dir = SEEDS / "hn_search_probe"
    validate_block_dir(block_dir)
    if not lint(block_dir).ok:
        raise RuntimeError("C2 seed lint 未通过")

    app = create_app(
        f"sqlite:///{(STORE / 'server.db').as_posix()}",
        clock=_Wall(),
        executor_hook=None,  # 先建 app 再挂 hook：runner 需要 ref
    )
    runner = TraceRunner(store, lambda: PatchrightBrowser(), block_dirs={ref: block_dir})
    app.state.scheduler.executor_hook = scheduler_hook(
        C2Executor(), runner, block_ref=ref, clock=app.state.clock
    )

    run_id = state.get("run_ids", {}).get("c2")
    if run_id is None:
        r = TestClient(app).post(
            "/api/v1/certifications",
            json={"subject_type": "block", "subject_id": "hn_search_probe",
                  "version": "1.0.0", "level": "C2", "site_tier": "medium",
                  "site_host": "hn.algolia.com"},
        )
        run_id = r.json()["run_id"]
        state.setdefault("run_ids", {})["c2"] = run_id
        save_state(state)
    elif not app.state.scheduler.reattach(run_id, site_tier="medium"):
        raise RuntimeError(f"C2 run_id={run_id} 无法重建调度态（reattach 失败）")

    result = {"segment": segment, "run_id": run_id, "submitted_at": now_iso()}
    result.update(drive_scheduler(app.state.scheduler, SEGMENT_RUNS * segment, run_id))
    result["gate"] = "PASS" if (
        result["n"] == SEGMENT_RUNS * segment and result["live_pass_rate"] is not None
    ) else "FAIL"
    return result


def load_golden_payload(ref: str) -> dict:
    """golden 目录 → 上传载荷形态（三件套；服务端强制 C8 脱敏校验）。"""
    d = STORE / "golden" / ref
    steps = [
        json.loads(line)
        for line in (d / "expected_steps.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    stubs = json.loads((d / "network_stubs.json").read_text(encoding="utf-8"))
    return {"expected_steps": steps, "network_stubs": stubs}


def run_c1_segment(segment: int, state: dict) -> dict:
    store = RecordingsStore(STORE)
    ref = ensure_trace(store, state, "c1", "saucedemo.com", script_c1)
    block_dir = SEEDS / "login_demo_probe"
    validate_block_dir(block_dir)
    if not lint(block_dir).ok:
        raise RuntimeError("C1 seed lint 未通过")

    app = create_app(f"sqlite:///{(STORE / 'server.db').as_posix()}")  # C1 侧无执行器
    client = TestClient(app)
    key = ensure_device(client, state)

    run_id = state.get("run_ids", {}).get("c1")
    if run_id is None:
        r = client.post(
            "/api/v1/certifications",
            json={"subject_type": "block", "subject_id": "login_demo_probe",
                  "version": "1.0.0", "level": "C1", "site_tier": "standard"},
        )
        run_id = r.json()["run_id"]
        state.setdefault("run_ids", {})["c1"] = run_id
        save_state(state)

    runner = TraceRunner(store, lambda: PatchrightBrowser(), block_dirs={ref: block_dir})
    signed = certify(
        ref, SEGMENT_RUNS, {},
        device_key=key, server_base=SERVER,
        browser_factory=lambda profile: PatchrightBrowser(),
        runner=runner, http=client,
    )
    up = CertReportClient(http=client).upload(
        SERVER, signed, run_id, golden=load_golden_payload(ref)
    )
    if up.status_code != 200:
        raise RuntimeError(f"C1 报告上传失败：{up.status_code} {up.body}")
    reliability = client.get(
        "/api/v1/blocks/login_demo_probe/versions/1.0.0/reliability"
    ).json()
    return {
        "segment": segment,
        "run_id": run_id,
        "n": len(signed.report["runs"]),
        "durations_sum_s": round(sum(signed.report["durations"]) / 1000, 1),
        "upload": up.body,
        "reliability": reliability,
        "gate": "PASS" if up.body.get("verdict") not in (None, "rejected") else "FAIL",
        "finished_at": now_iso(),
    }


class _Wall:
    def now(self):
        return datetime.now(timezone.utc).replace(tzinfo=None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segment", type=int, choices=[1, 2], required=True)
    args = parser.parse_args()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    STORE.mkdir(parents=True, exist_ok=True)
    state = load_state()

    overall = True
    for name, fn in (("c2", run_c2_segment), ("c1", run_c1_segment)):
        print(f"=== seg{args.segment} {name} ===", flush=True)
        try:
            result = fn(args.segment, state)
        except Exception as exc:
            import traceback

            traceback.print_exc()
            result = {"segment": args.segment, "path": name, "gate": "FAIL",
                      "error": f"{type(exc).__name__}: {exc}"}
        if "gate" not in result:
            result["gate"] = "FAIL"  # 路径自判缺失即不通过，不默认放行
        out = EVIDENCE / f"t1.35_seg{args.segment}_{name}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        overall = overall and result.get("gate") == "PASS"
    print(f"gate: {'PASS' if overall else 'FAIL'}", flush=True)
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())

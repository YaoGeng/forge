"""时钟日执行器（2026-10-18）：等待各 48h 真实时钟窗口后串行执行——
批次一 seg2（两遍兜底）→ 批次二 seg2 → register 全库 → T1.64c 五应用 → T1.65e 覆盖实验
（docs/13 收口排期 + docs/14 T1.65e）。

- 单进程串行（同一 sqlite 库不并发）；窗口由 server.db started_at+48h 实时推算（不写死时刻）。
- 全段幂等断点续跑：drive 已达标块立即返回（reattach 跨进程重建）、register 重复登记按已
  登记处理、assemble 有 t164c_state.json 断点、coverage runs/<id>.json 判定冻结跳过。
- 前段失败不拦后段（依赖段自检：assemble 自查注册块 ≥20；coverage 只需 registry 读侧）。
- 日志：spikes/evidence/clock_day.log；驱动子进程输出全文追加同文件。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _rel in ("apps/server", "spikes", "packages/certifier/python",
             "packages/trace/python", "packages/proto/python",
             "packages/block-sdk/python"):
    _p = _ROOT / _rel
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

EVIDENCE = _ROOT / "spikes" / "evidence"
STORE = EVIDENCE / "ms1e_store"
LOG = EVIDENCE / "clock_day.log"
PY = sys.executable


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def wait_until(target: datetime, label: str) -> None:
    while True:
        remain = (target - datetime.now(timezone.utc)).total_seconds()
        if remain <= 0:
            log(f"到点：{label}")
            return
        if remain > 300:
            log(f"等窗 {label}：还剩 {remain / 60:.0f} 分钟")
            time.sleep(300)
        else:
            time.sleep(min(remain, 10))


def run_cli(script: str, *args: str, timeout_s: int) -> int:
    cmd = [PY, str(_ROOT / "spikes" / script), *args]
    log(f"$ {script} {' '.join(args)}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(_ROOT), timeout=timeout_s, env=env)
        out, err, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = (e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        rc = 124
        log(f"子进程超时（>{timeout_s}s）——按失败段记录，继续后续段")
    with LOG.open("a", encoding="utf-8") as f:
        if out:
            f.write(out + "\n")
        if err:
            f.write("[stderr]\n" + err + "\n")
    log(f"exit={rc}（子进程输出已全文入 log）")
    return rc


def seg2_windows() -> dict[int, dict]:
    """各批新块 48h 窗（reattach 同口径：started_at + 48h）；run 集取 state.run_ids。"""
    import sqlite3

    from seedline import load_manifest

    state = json.loads((STORE / "state.json").read_text(encoding="utf-8"))
    run_ids = state.get("run_ids", {})
    manifest = load_manifest(_ROOT / "spikes" / "seed_blocks" / "manifest.yaml")
    con = sqlite3.connect(STORE / "server.db")
    out: dict[int, dict] = {}
    try:
        for batch in (1, 2):
            opens, names = [], []
            for b in manifest.blocks:
                if not (b.level == "C2" and not b.exists and b.batch == batch):
                    continue
                rid = run_ids.get(b.name)
                if rid is None:
                    continue
                row = con.execute(
                    "SELECT started_at FROM certification_runs WHERE id = ?", (rid,)
                ).fetchone()
                if row is None or row[0] is None:
                    raise RuntimeError(f"run {rid}（{b.name}）无 started_at")
                started = datetime.fromisoformat(row[0])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                opens.append(started + timedelta(hours=48))
                names.append(b.name)
            if not opens:
                raise RuntimeError(f"批次 {batch} 无待驱动 run")
            out[batch] = {"names": names, "min": min(opens), "max": max(opens)}
    finally:
        con.close()
    return out


def phase_register() -> int:
    """register 全库：新块走 block.yaml 元数据；遗留两块手动 POST（state 键映射 run 1/2）。"""
    import yaml
    from fastapi.testclient import TestClient

    from forge_server.app import create_app
    from seedline import load_manifest

    state = json.loads((STORE / "state.json").read_text(encoding="utf-8"))
    run_ids = {k: v for k, v in state.get("run_ids", {}).items() if k not in ("c1", "c2")}
    manifest = load_manifest(_ROOT / "spikes" / "seed_blocks" / "manifest.yaml")
    for b in manifest.blocks:
        if b.exists and b.legacy_state_key:
            legacy_rid = state.get("run_ids", {}).get(b.legacy_state_key)
            if legacy_rid is not None:
                run_ids[b.name] = legacy_rid

    app = create_app(f"sqlite:///{(STORE / 'server.db').as_posix()}")
    client = TestClient(app)
    results: dict[str, int] = {}
    for name, rid in sorted(run_ids.items()):
        meta = {}
        ypath = _ROOT / "spikes" / "seed_blocks" / name / "block.yaml"
        if ypath.exists():
            meta = yaml.safe_load(ypath.read_text(encoding="utf-8")) or {}
        domains = [p.get("value") for p in (meta.get("permissions") or [])
                   if isinstance(p, dict) and p.get("type") == "domain"]
        r = client.post("/api/v1/registry/blocks", json={
            "name": name, "version": meta.get("version", "1.0.0"),
            "certification_run_id": rid,
            "side_effects": bool(meta.get("side_effects", False)),
            "domains": domains})
        results[name] = r.status_code
        if r.status_code not in (200, 201, 409):
            log(f"  register {name}: {r.status_code} {r.text[:160]}")
    ok = sum(1 for c in results.values() if c in (200, 201))
    known = sum(1 for c in results.values() if c in (200, 201, 409))
    (EVIDENCE / "t1.63_register.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"register：受理 {ok} + 已登记 {known - ok} / 共 {len(results)} → t1.63_register.json")
    return 0 if known == len(results) else 1


def main() -> int:
    log("时钟日执行器启动（真实钟；全段幂等断点续跑）")
    from forge_server.app import create_app

    create_app(f"sqlite:///{(STORE / 'server.db').as_posix()}")  # 预热：旧库补列等迁移问题前置暴露
    log("预热 create_app 完成（建表/补列幂等）")

    w = seg2_windows()
    for b in (1, 2):
        log(f"批次{b}：{len(w[b]['names'])} 块 [{','.join(w[b]['names'])}] "
            f"窗 {w[b]['min']:%H:%M:%S}~{w[b]['max']:%H:%M:%S}Z")
    rc: dict[str, int] = {}

    wait_until(w[1]["min"] + timedelta(seconds=30), "批次一窗口")
    rc["drive_b1"] = run_cli("cert_batch.py", "drive", "--segment", "2", "--batch", "1",
                             timeout_s=60 * 95)
    if rc["drive_b1"] != 0:
        # 批内末块（book_detail 重录）窗口晚于首轮 90 分钟预算起点——第二遍兜底（幂等）
        wait_until(w[1]["max"] + timedelta(seconds=15), "批次一末块窗口")
        rc["drive_b1_topup"] = run_cli("cert_batch.py", "drive", "--segment", "2",
                                       "--batch", "1", timeout_s=30 * 60)
    wait_until(w[2]["min"] + timedelta(seconds=30), "批次二窗口")
    rc["drive_b2"] = run_cli("cert_batch.py", "drive", "--segment", "2", "--batch", "2",
                             timeout_s=60 * 95)
    rc["register"] = phase_register()
    rc["assemble"] = run_cli("assemble_apps.py", timeout_s=30 * 60)
    rc["coverage"] = run_cli("run_coverage.py", timeout_s=30 * 60)
    log(f"汇总：{json.dumps(rc)}")
    ok = ((rc.get("drive_b1") == 0 or rc.get("drive_b1_topup") == 0)
          and rc["drive_b2"] == 0 and rc["register"] == 0
          and rc["assemble"] == 0 and rc["coverage"] == 0)
    log(f"时钟日执行器结束：{'ALL PASS' if ok else '存在失败段（见上）'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

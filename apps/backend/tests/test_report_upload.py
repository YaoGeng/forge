"""T1.33 用例矩阵：报告签名上传链——验签/nonce/时长下限/golden 拒收 + reliability API
（M09 §3.2/§5/§8.5/§8.7；C7/C8）。
"""
import base64
import hashlib
import json

from fastapi.testclient import TestClient

from forge_certifier.device import DeviceKey

SERVER = "http://test"
C1_LABEL = "创作者环境实测，平台抽查复核"


def _all_ok_hook(live_fails=()):
    from forge_server.scheduler import SegmentRunOutcome

    def hook(run_id, segment, index):
        ok = index not in live_fails
        return SegmentRunOutcome(live_ok=ok, regression_ok=True,
                                 failure_class=None if ok else "anchor_mismatch")

    return hook


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def register_key(client, creator="c-t133"):
    key = DeviceKey.generate()
    r = client.post(
        "/api/v1/certifications/devices",
        json={"creator_id": creator, "public_key": key.public_key_pem, "device_fp": key.device_fp},
    )
    assert r.status_code == 201
    return key


def get_nonce(client, key):
    r = client.post("/api/v1/certifications/nonce", json={"device_fp": key.device_fp})
    assert r.status_code == 201
    return r.json()["nonce"]


def make_report(n=20, fails=(), durations_ms=None):
    runs = [
        {
            "index": i,
            "ok": i not in fails,
            "failure_class": "selector_missing" if i in fails else None,
            "action": "nav" if i == 0 else "click",  # C9 比对所需（T1.34 白名单扩展）
            "duration_ms": 100,
        }
        for i in range(n)
    ]
    return {
        "runs": runs,
        "env_fingerprint": "0123456789abcdef",
        "fail_json": {"failures": [{"index": i, "failure_class": "selector_missing"} for i in fails]},
        "durations": durations_ms or [6000] * n,  # 默认 6s/run > 5s 下限
        "network_shape": ["GET example.com /search?q"],  # 形状键（无值，C8 边界内）
    }


def signed_payload(key, nonce, report, *, signer=None):
    attestation = {
        "nonce": nonce,
        "report_hash": hashlib.sha256(canonical(report)).hexdigest()[:16],
        "env_fingerprint": "0123456789abcdef",
        "client_version": "0.1.0",
        "ts": "2026-10-16T09:00:00",
    }
    sig = (signer or key).sign(canonical(attestation))
    return {
        "device_fp": key.device_fp,
        "report": report,
        "attestation": attestation,
        "signature": base64.b64encode(sig).decode("ascii"),
    }


GOOD_GOLDEN = {
    "expected_steps": [
        {"seq": 1, "action": "nav", "value": "https://example.com/search?q=⟦R:0⟧&lang=⟦R:1⟧"},
        {"seq": 2, "action": "input", "target_selector": "#q", "value": "⟦R:0⟧"},
    ],
    "network_stubs": {
        "entries": [
            {
                "url": "https://example.com/api",
                "method": "POST",
                "request_body": '{"user": "⟦R:2⟧", "count": 3}',
                "response_body": None,
            }
        ]
    },
}


def submit_c1_run(client, subject="login_demo", version="1.0.0"):
    r = client.post(
        "/api/v1/certifications",
        json={"subject_type": "block", "subject_id": subject, "version": version, "level": "C1"},
    )
    assert r.status_code == 201
    return r.json()["run_id"]


def upload(client, run_id, payload):
    return client.post(f"/api/v1/certifications/{run_id}/report", json=payload)


# --- 上传主链 ------------------------------------------------------------------------


def test_valid_report_accepted(make_app, clock):
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)

    payload = signed_payload(key, get_nonce(client, key), make_report(n=20, fails=(3, 9)))
    payload["golden"] = GOOD_GOLDEN
    r = upload(client, run_id, payload)

    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "pass"  # 18/20 达 standard 阈值
    assert body["live_pass_rate"] == 0.9
    assert body["regression_pass_rate"] is None  # C1 上传通道无 golden 回放，分列不混算

    data = client.get(f"/api/v1/certifications/{run_id}").json()
    assert data["verdict"] == "pass"  # verdict 落库
    assert data["attestation_sig"] == payload["signature"]
    assert data["n"] == 20 and data["pass"] == 18
    assert data["started_at"] == clock.now().isoformat()  # 受理时刻即窗口（FrozenClock）


def test_wrong_key_rejected(make_app):
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    other = DeviceKey.generate()
    run_id = submit_c1_run(client)

    payload = signed_payload(key, get_nonce(client, key), make_report(n=5), signer=other)
    payload["golden"] = GOOD_GOLDEN
    body = upload(client, run_id, payload).json()
    assert body["verdict"] == "rejected"
    assert any("签名" in r for r in body["reasons"])


def test_nonce_single_use(make_app):
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)
    nonce = get_nonce(client, key)

    p1 = signed_payload(key, nonce, make_report(n=5))
    p1["golden"] = GOOD_GOLDEN
    assert upload(client, run_id, p1).json()["verdict"] == "pass"

    p2 = signed_payload(key, nonce, make_report(n=5, durations_ms=[6001] * 5))
    p2["golden"] = GOOD_GOLDEN
    body = upload(client, run_id, p2).json()
    assert body["verdict"] == "rejected"  # 同 nonce 二传被拒
    assert any("nonce" in r for r in body["reasons"])


def test_expired_nonce_rejected(make_app, clock):
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)
    nonce = get_nonce(client, key)

    clock.advance(minutes=6)
    payload = signed_payload(key, nonce, make_report(n=5))
    payload["golden"] = GOOD_GOLDEN
    body = upload(client, run_id, payload).json()
    assert body["verdict"] == "rejected"
    assert any("nonce" in r for r in body["reasons"])


def test_idempotent_resubmit(make_app):
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)

    payload = signed_payload(key, get_nonce(client, key), make_report(n=5))
    payload["golden"] = GOOD_GOLDEN
    r1 = upload(client, run_id, payload).json()
    before = client.get(f"/api/v1/certifications/{run_id}").json()
    r2 = upload(client, run_id, payload).json()  # 同载荷二传
    after = client.get(f"/api/v1/certifications/{run_id}").json()

    assert r1["verdict"] == "pass" and r2 == r1  # 200 同结果
    assert before == after  # 不重复计数/不改写


def test_second_upload_accumulates_n(make_app):
    """docs/12 T1.35 C1 语义：两时段各上传一批 → 行内 N=20 累计（时钟日偏差修复）。"""
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)

    p1 = signed_payload(key, get_nonce(client, key), make_report(n=10))
    p1["golden"] = GOOD_GOLDEN
    assert upload(client, run_id, p1).json()["verdict"] == "pass"

    p2 = signed_payload(key, get_nonce(client, key), make_report(n=10, fails=(2,)))
    p2["golden"] = GOOD_GOLDEN
    body = upload(client, run_id, p2).json()
    assert body["verdict"] == "pass"

    data = client.get(f"/api/v1/certifications/{run_id}").json()
    assert data["n"] == 20  # 10 + 10 累计，非末批替换
    assert data["pass"] == 19
    assert abs(data["live_pass_rate"] - 0.95) < 1e-9
    rel = client.get(f"/api/v1/blocks/login_demo/versions/1.0.0/reliability").json()
    assert rel["n"] == 20


def test_replayed_report_hash_with_new_nonce_rejected(make_app):
    """同报告内容换新 nonce 重传 → 拒绝且不重复计数（累加语义下的防重放）。"""
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)
    report = make_report(n=10)

    p1 = signed_payload(key, get_nonce(client, key), report)
    p1["golden"] = GOOD_GOLDEN
    assert upload(client, run_id, p1).json()["verdict"] == "pass"

    p2 = signed_payload(key, get_nonce(client, key), report)  # 同内容、新 nonce
    p2["golden"] = GOOD_GOLDEN
    body = upload(client, run_id, p2).json()
    assert body["verdict"] == "rejected"
    assert any("已受理" in r for r in body["reasons"])

    data = client.get(f"/api/v1/certifications/{run_id}").json()
    assert data["n"] == 10  # 未重复计数；已判 verdict 不被降级路径改写
    assert data["verdict"] == "pass"


def test_min_duration_floor(make_app):
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)

    payload = signed_payload(
        key, get_nonce(client, key), make_report(n=20, durations_ms=[1500] * 20)
    )
    payload["golden"] = GOOD_GOLDEN
    body = upload(client, run_id, payload).json()
    assert body["verdict"] == "rejected"  # 30s < 20×5s
    assert any("时长" in r for r in body["reasons"])


def test_report_hash_binding_enforced(make_app):
    """C7 绑定：attestation.report_hash 必须等于上传报告的 sha256（签名保护的是报告内容）。"""
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)

    report = make_report(n=5)
    payload = signed_payload(key, get_nonce(client, key), report)
    payload["attestation"]["report_hash"] = "0" * 16  # 与报告脱钩的哈希
    payload["golden"] = GOOD_GOLDEN
    body = upload(client, run_id, payload).json()
    assert body["verdict"] == "rejected"
    assert any("report_hash" in r for r in body["reasons"])


def test_rejected_resubmit_keeps_accepted_verdict(make_app):
    """已受理（pass）的报告不被后续校验失败的重传降级为 rejected。"""
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)

    good = signed_payload(key, get_nonce(client, key), make_report(n=5))
    good["golden"] = GOOD_GOLDEN
    assert upload(client, run_id, good).json()["verdict"] == "pass"

    stale = signed_payload(key, "deadnonce", make_report(n=5, durations_ms=[6001] * 5))
    stale["golden"] = GOOD_GOLDEN
    assert upload(client, run_id, stale).json()["verdict"] == "rejected"  # nonce 已消费

    data = client.get(f"/api/v1/certifications/{run_id}").json()
    assert data["verdict"] == "pass"  # 既判不被覆写


def test_report_channel_requires_c1(make_app):
    """上传通道仅限 C1 run（M09 §5）：C2 run 的调度器数据不被外部报告覆写（G6 分列）。"""
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    r = client.post(
        "/api/v1/certifications",
        json={"subject_type": "block", "subject_id": "c2probe", "version": "1.0.0", "level": "C2"},
    )
    run_id = r.json()["run_id"]

    payload = signed_payload(key, get_nonce(client, key), make_report(n=5))
    payload["golden"] = GOOD_GOLDEN
    body = upload(client, run_id, payload).json()
    assert body["verdict"] == "rejected"
    assert any("C1" in rr for rr in body["reasons"])


def test_golden_raw_value_rejected(make_app):
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)

    def golden_with(steps=(), entries=()):
        return {"expected_steps": list(steps), "network_stubs": {"entries": list(entries)}}

    cases = [
        # steps[].value 明文
        (golden_with(steps=({"seq": 1, "action": "input", "value": "明文搜索词"},)),
         ("expected_steps", "value")),
        # URL query 值明文
        (golden_with(steps=({"seq": 1, "action": "nav", "value": "https://example.com/?q=明文"},)),
         ("query",)),
        # bodies 字符串标量明文
        (golden_with(entries=({"url": "https://example.com/api", "method": "POST",
                               "request_body": '{"user": "张三"}', "response_body": None},)),
         ("request_body",)),
        # URL userinfo 未剥离（R1②缺口服务端闭合）
        (golden_with(steps=({"seq": 1, "action": "nav", "value": "https://user:pw@example.com/?q=⟦R:0⟧"},)),
         ("userinfo",)),
    ]
    for golden, marks in cases:
        payload = signed_payload(key, get_nonce(client, key), make_report(n=5))
        payload["golden"] = golden
        body = upload(client, run_id, payload).json()
        assert body["verdict"] == "rejected", golden
        joined = json.dumps(body["reasons"], ensure_ascii=False)
        for m in marks:
            assert m in joined, (m, joined)  # 拒收并指出位置


# --- reliability API（详情页初始分）-----------------------------------------------------


def test_reliability_live_only(make_app, clock, drain):
    app = make_app(hook=_all_ok_hook(live_fails=(18, 19)))
    client = TestClient(app)
    sched = app.state.scheduler
    sched.submit("block", "probe", "1.0.0", "C2")
    drain(sched, clock)

    r = client.get("/api/v1/blocks/probe/versions/1.0.0/reliability")
    assert r.status_code == 200
    body = r.json()
    assert body["pass_rate"] == 0.9  # 仅 live 口径
    assert body["n"] == 20
    assert "regression" not in json.dumps(body)  # 无 regression 字段出口


def test_reliability_c1_label_and_window(make_app):
    app = make_app()
    client = TestClient(app)
    key = register_key(client)
    run_id = submit_c1_run(client)
    payload = signed_payload(key, get_nonce(client, key), make_report(n=20, fails=(0,)))
    payload["golden"] = GOOD_GOLDEN
    assert upload(client, run_id, payload).json()["verdict"] == "pass"

    body = client.get("/api/v1/blocks/login_demo/versions/1.0.0/reliability").json()
    assert body["c1_label"] == C1_LABEL  # 标注逐字
    assert body["n"] == 20
    assert body["window_start"] and body["window_end"]  # 时间窗
    assert body["pass_rate"] == 0.95


def test_reliability_no_samples(make_app):
    app = make_app()
    client = TestClient(app)
    body = client.get("/api/v1/blocks/none/versions/9.9.9/reliability").json()
    assert body["message"] == "数据不足"
    assert body["pass_rate"] is None and body["n"] == 0

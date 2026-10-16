"""T1.65b/c/d 覆盖实验产线单测（离线，不触网）。"""
from __future__ import annotations

import json

import pytest

from spikes.coverage_runner import (
    KNOWN_DOMAINS,
    check_shape,
    load_pool,
    load_sample,
    run_one,
    select_sample,
    tally,
    write_report,
)


# ---------- T1.65b load_pool ----------

def _mk_entry(eid, verdict="in_domain", domains=None, posted_at="2025-01-01T00:00:00Z", **kw):
    base = {
        "id": eid, "source": "t", "community": "c", "url": f"https://x/{eid}",
        "title": f"t-{eid}", "excerpt": "need text", "posted_at": posted_at,
        "posted_at_precision": "s", "fetched_at": "2026-10-16T00:00:00Z",
        "verdict": verdict, "domains": domains, "note": "n", "reason": "n",
    }
    base.update(kw)
    return base


def _write_pool(tmp_path, entries, counts=None):
    pool = {"meta": {"counts": counts or {}}, "entries": entries}
    p = tmp_path / "pool.json"
    p.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    return p


class TestLoadPool:
    def test_loads_real_pool_and_counts(self):
        entries = load_pool("spikes/coverage/pool.json")
        assert len(entries) >= 60
        in_dom = [e for e in entries if e["verdict"] == "in_domain"]
        assert len(in_dom) >= 35
        assert len({e["community"] for e in in_dom}) >= 2
        for e in entries:
            assert e["url"] and e["title"]
            if e["verdict"] == "in_domain":
                assert e["domains"] and e["posted_at"] and e["excerpt"]

    def test_rejects_in_domain_without_posted_at(self, tmp_path):
        p = _write_pool(tmp_path, [_mk_entry("a", domains=["s1"], posted_at=None)])
        with pytest.raises(ValueError, match="posted_at"):
            load_pool(str(p))

    def test_rejects_unknown_domain(self, tmp_path):
        p = _write_pool(tmp_path, [_mk_entry("a", domains=["s99"])])
        with pytest.raises(ValueError, match="s99"):
            load_pool(str(p))

    def test_rejects_duplicate_ids(self, tmp_path):
        p = _write_pool(tmp_path, [_mk_entry("a", domains=["s1"]), _mk_entry("a", domains=["s2"])])
        with pytest.raises(ValueError, match="重复"):
            load_pool(str(p))


# ---------- T1.65c select_sample / load_sample ----------

class TestSelectSample:
    def test_selection_is_mechanical(self, tmp_path):
        # 同一池快照重跑选样：逐字节一致；且严格按 posted_at 倒序
        pool_entries = [
            _mk_entry("old", domains=["s1"], posted_at="2020-01-01T00:00:00Z"),
            _mk_entry("mid", domains=["s1"], posted_at="2023-06-01T00:00:00Z"),
            _mk_entry("new", domains=["s2"], posted_at="2026-01-01T00:00:00Z"),
        ] + [_mk_entry(f"f{i}", domains=["s1"], posted_at=f"2024-01-{i+1:02d}T00:00:00Z") for i in range(28)]
        p = _write_pool(tmp_path, pool_entries)
        s1 = select_sample(load_pool(str(p)), 30)
        s2 = select_sample(load_pool(str(p)), 30)
        assert [e["id"] for e in s1] == [e["id"] for e in s2]
        assert len(s1) == 30
        assert "old" not in [e["id"] for e in s1]  # 最旧被挤出
        dates = [e["posted_at"] for e in s1]
        assert dates == sorted(dates, reverse=True)

    def test_ties_broken_by_pool_order(self, tmp_path):
        pool_entries = [
            _mk_entry(f"t{i}", domains=["s1"], posted_at="2025-01-01T00:00:00Z") for i in range(3)
        ]
        p = _write_pool(tmp_path, pool_entries)
        s = select_sample(load_pool(str(p)), 2)
        assert [e["id"] for e in s] == ["t0", "t1"]  # 同刻按池序

    def test_sample_ids_subset_of_pool(self, tmp_path):
        pool_entries = [_mk_entry(f"t{i}", domains=["s1"], posted_at=f"2025-01-{i+1:02d}T00:00:00Z") for i in range(5)]
        p = _write_pool(tmp_path, pool_entries)
        s = select_sample(load_pool(str(p)), 3)
        assert {e["id"] for e in s} <= {e["id"] for e in pool_entries}


class TestLoadSample:
    def test_rejects_sample_not_from_pool(self, tmp_path):
        pool = _write_pool(tmp_path, [_mk_entry("a", domains=["s1"])])
        sample = {
            "meta": {"pool_ref": "sha256:deadbeef"},
            "entries": [{"id": "ghost", "domains": ["s1"], "expected_shape": {"type": "table"}}],
        }
        sp = tmp_path / "sample.json"
        sp.write_text(json.dumps(sample), encoding="utf-8")
        with pytest.raises(ValueError, match="ghost"):
            load_sample(str(sp), str(pool))

    def test_expected_shape_required_and_hashed(self, tmp_path):
        pool = _write_pool(tmp_path, [_mk_entry("a", domains=["s1"])])
        sample = {
            "meta": {"pool_ref": "sha256:x"},
            "entries": [{
                "id": "a", "domains": ["s1"], "expected_shape": {"type": "table", "fields": ["k"]},
                "attempt": {"kind": "uncoverable", "reason": "站点未覆盖"},
            }],
        }
        sp = tmp_path / "sample.json"
        sp.write_text(json.dumps(sample), encoding="utf-8")
        entries = load_sample(str(sp), str(pool))
        assert entries[0]["expected_shape"] == {"type": "table", "fields": ["k"]}
        assert entries[0]["shape_digest"].startswith("sha256:")

    def test_attempt_cannot_mutate_domains(self, tmp_path):
        pool = _write_pool(tmp_path, [_mk_entry("a", domains=["s1"])])
        sample = {
            "meta": {"pool_ref": "sha256:x"},
            "entries": [{
                "id": "a", "domains": ["s1", "s7"],  # 阶段二字段偷偷改域 → 拒绝
                "expected_shape": {"type": "table"},
                "attempt": {"kind": "uncoverable", "reason": "x"},
                "domains_digest": None,  # 未按阶段一登记的摘要提供
            }],
        }
        sp = tmp_path / "sample.json"
        sp.write_text(json.dumps(sample), encoding="utf-8")
        with pytest.raises(ValueError, match="domains"):
            load_sample(str(sp), str(pool))


def test_known_domains_are_ten_scenarios():
    assert KNOWN_DOMAINS == [f"s{i}" for i in range(1, 11)]


class TestRealArtifacts:
    """真实产物校验（池/样本落盘后跑；不触网）。"""

    def test_real_sample_loads_and_domains_frozen(self):
        entries = load_sample("spikes/coverage/sample.json", "spikes/coverage/pool.json")
        assert len(entries) == 30
        # 两阶段写入：阶段一产物（选样+域映射）与阶段二（形状+尝试）一致性由池快照钉死
        for e in entries:
            assert e["shape_digest"].startswith("sha256:")

    def test_domain_mapping_recorded_before_attempt(self, tmp_path):
        # 阶段二字段（attempt/expected_shape）不得回写阶段一域判定：
        # 构造「阶段一 domains 与池一致、阶段二被篡改」的样本 → 必须拒绝
        pool = _write_pool(tmp_path, [_mk_entry("a", domains=["s1"])])
        sample = {
            "meta": {"pool_ref": "sha256:x"},
            "entries": [{
                "id": "a", "domains": ["s7"],  # 篡改：池登记 s1
                "expected_shape": {"format": "digest"},
                "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "x"},
            }],
        }
        sp = tmp_path / "sample.json"
        sp.write_text(json.dumps(sample), encoding="utf-8")
        with pytest.raises(ValueError, match="domains"):
            load_sample(str(sp), str(pool))

    def test_real_sample_attempt_kinds_valid(self):
        entries = load_sample("spikes/coverage/sample.json", "spikes/coverage/pool.json")
        cats = {"site_not_covered", "capability_missing", "needs_genericization"}
        for e in entries:
            a = e["attempt"]
            if a["kind"] == "uncoverable":
                assert a["category"] in cats and a["reason"]
            else:
                assert a["kind"] == "chain" and a["steps"]


# ---------- T1.65d run_one / tally / write_report ----------

def _chain_entry(eid="c1", must=None, blocks=("text_clean", "markdown_export")):
    return {
        "id": eid, "domains": ["s8"], "title": "t", "url": "u", "excerpt": "e",
        "posted_at": "2025-01-01T00:00:00Z", "community": "c",
        "expected_shape": {"format": "markdown", "checked": True,
                           "must": must or {"title_row": True, "min_point_rows": 3}},
        "shape_digest": "sha256:abc",
        "attempt": {"kind": "chain", "steps": [
            {"block": b, "params": {"text": "x"}} for b in blocks]},
    }


class TestRunOne:
    def test_chain_executes_exactly_once(self):
        calls = []

        def exec_chain(steps):
            calls.append(steps)
            return {"ok": True, "steps": [], "context": {"markdown_export": {"ok": True, "file": "a.md", "rows": 5}}}

        rec = run_one(_chain_entry(), exec_chain, registry={"text_clean", "markdown_export"})
        assert len(calls) == 1  # C9 单次运行，不重试
        assert rec["verdict"] == "covered"

    def test_unregistered_block_refuses_to_run(self):
        # Review Focus 3：未注册块绝不执行，也绝不落产线脚本直跑
        calls = []

        def exec_chain(steps):
            calls.append(steps)
            return {"ok": True, "steps": [], "context": {}}

        rec = run_one(_chain_entry(), exec_chain, registry={"text_clean"})
        assert calls == []
        assert rec["verdict"] == "uncovered"
        assert rec["category"] == "registry_missing"
        assert "text_clean" not in rec.get("executed_via", "spikes-direct")  # 不出现直跑通道

    def test_uncoverable_never_runs(self):
        entry = {
            "id": "u1", "domains": ["s7"], "title": "t", "url": "u", "excerpt": "e",
            "posted_at": "2025-01-01T00:00:00Z", "community": "c",
            "expected_shape": {"format": "alert", "checked": False},
            "shape_digest": "sha256:abc",
            "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "x"},
        }
        calls = []

        def exec_chain(steps):
            calls.append(steps)
            return {"ok": True, "steps": [], "context": {}}

        rec = run_one(entry, exec_chain, registry=set())
        assert calls == []
        assert rec["verdict"] == "uncovered" and rec["category"] == "site_not_covered"

    def test_run_failure_marks_run_failed(self):
        def exec_chain(steps):
            return {"ok": False, "steps": [{"index": 0, "block": "text_clean", "ok": False}], "context": {}}

        rec = run_one(_chain_entry(), exec_chain, registry={"text_clean", "markdown_export"})
        assert rec["verdict"] == "uncovered" and rec["category"] == "run_failed"

    def test_shape_mismatch_marks_uncovered(self):
        def exec_chain(steps):
            # 实际只产出 1 行（无拆行/标题能力）——预期形状要求标题+3 要点 → 形状不符
            return {"ok": True, "steps": [], "context": {"markdown_export": {"ok": True, "file": "a.md", "rows": 1}}}

        rec = run_one(_chain_entry(), exec_chain, registry={"text_clean", "markdown_export"})
        assert rec["verdict"] == "uncovered" and rec["category"] == "shape_mismatch"

    def test_run_record_carries_expected_shape_hash(self):
        # Review Focus 2：判定记录携带预登记形状摘要——事后改样本与记录对不上即露馅
        def exec_chain(steps):
            return {"ok": True, "steps": [], "context": {"markdown_export": {"ok": True, "rows": 5, "file": "a.md"}}}

        rec = run_one(_chain_entry(), exec_chain, registry={"text_clean", "markdown_export"})
        assert rec["shape_digest"] == "sha256:abc"
        assert rec["expected_must"] == {"title_row": True, "min_point_rows": 3}

    def test_binding_error_is_run_failed_not_crash(self):
        def exec_chain(steps):
            raise KeyError("text_clean.text")

        rec = run_one(_chain_entry(), exec_chain, registry={"text_clean", "markdown_export"})
        assert rec["verdict"] == "uncovered" and rec["category"] == "run_failed"


class TestCheckShape:
    def test_markdown_rows_account_for_title(self):
        assert check_shape({"rows": 4}, {"title_row": True, "min_point_rows": 3})
        assert not check_shape({"rows": 3}, {"title_row": True, "min_point_rows": 3})
        assert check_shape({"rows": 3}, {"min_point_rows": 3})
        assert not check_shape({"rows": 2}, {"min_point_rows": 3})


class TestTallyReport:
    def _records(self):
        return [
            {"id": "a", "verdict": "uncovered", "category": "site_not_covered"},
            {"id": "b", "verdict": "uncovered", "category": "site_not_covered"},
            {"id": "c", "verdict": "uncovered", "category": "capability_missing"},
            {"id": "d", "verdict": "uncovered", "category": "shape_mismatch"},
            {"id": "e", "verdict": "covered"},
        ]

    def test_tally_counts(self):
        t = tally(self._records())
        assert t["denominator"] == 5 and t["covered"] == 1
        assert t["rate"] == 0.2
        assert t["categories"]["site_not_covered"] == 2

    def test_report_contents(self, tmp_path):
        t = tally(self._records())
        out = tmp_path / "report.md"
        write_report(out, self._records(), t, out_of_domain={"total": 56, "top": [("管理/防护工具", 9)]},
                     sample_meta={"pool_ref": "sha256:x"})
        text = out.read_text(encoding="utf-8")
        assert "5" in text and "20.0%" in text
        assert "site_not_covered" in text and "域外" in text
        assert "人工复核" in text  # C10 复核列
        assert "sha256:x" in text  # 池快照引用可追溯

"""T1.65b/c/d 覆盖实验产线单测（离线，不触网）。"""
from __future__ import annotations

import json

import pytest

from spikes.coverage_runner import (
    KNOWN_DOMAINS,
    check_shape,
    load_pool,
    load_sample,
    pool_digest,
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
        # T1.78：R1 池作废留档；现网池 = pool_r2.json（A.10 R2）
        entries = load_pool("spikes/coverage/pool_r2.json")
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
            _mk_entry("new", domains=["s9"], posted_at="2026-01-01T00:00:00Z"),
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
            "meta": {"pool_ref": pool_digest(load_pool(str(pool)))},
            "entries": [{"id": "ghost", "domains": ["s1"], "expected_shape": {"type": "table"}}],
        }
        sp = tmp_path / "sample.json"
        sp.write_text(json.dumps(sample), encoding="utf-8")
        with pytest.raises(ValueError, match="ghost"):
            load_sample(str(sp), str(pool))

    def test_expected_shape_required_and_hashed(self, tmp_path):
        pool = _write_pool(tmp_path, [_mk_entry("a", domains=["s1"])])
        sample = {
            "meta": {"pool_ref": pool_digest(load_pool(str(pool)))},
            "entries": [{
                "id": "a", "domains": ["s1"], "expected_shape": {"type": "table", "fields": ["k"]},
                "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "站点未覆盖"},
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
            "meta": {"pool_ref": pool_digest(load_pool(str(pool)))},
            "entries": [{
                "id": "a", "domains": ["s1", "s7"],  # 阶段二字段偷偷改域 → 拒绝
                "expected_shape": {"type": "table"},
                "attempt": {"kind": "uncoverable", "category": "site_not_covered", "reason": "x"},
            }],
        }
        sp = tmp_path / "sample.json"
        sp.write_text(json.dumps(sample), encoding="utf-8")
        with pytest.raises(ValueError, match="domains"):
            load_sample(str(sp), str(pool))


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
        assert "executed_via" not in rec  # 不存在任何直跑通道字段

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
                     sample_meta={"pool_ref": "sha256:x", "supply_side": 18, "demand_side": 12})
        text = out.read_text(encoding="utf-8")
        assert "5" in text and "20.0%" in text
        assert "site_not_covered" in text and "域外" in text
        assert "人工复核" in text  # C10 复核列
        assert "sha256:x" in text  # 池快照引用可追溯
        assert "供给帖（Show HN 产品动机）18 条" in text  # I2 构成披露


# ---------- T1.78 A.10 R2：排除域硬校验 + 8 场景锚定 ----------

def test_known_domains_are_eight_scenarios_r2():
    """A.9 R2①：场景集 10→8（砍 s2/s10）——域锚定集合同步收窄。"""
    assert KNOWN_DOMAINS == ["s1", "s3", "s4", "s5", "s6", "s7", "s8", "s9"]


class TestLoadPoolR2Exclusions:
    """Review Focus 4：排除域条目入样即 load_pool 拒绝（硬校验而非标注）。"""

    def _pool_with(self, tmp_path, **kw):
        return _write_pool(tmp_path, [_mk_entry("a", domains=["s1"], **kw)])

    def test_rejects_gambling(self, tmp_path):
        p = self._pool_with(tmp_path, note="博彩 Odds 赔率聚合")
        with pytest.raises(ValueError, match="排除域"):
            load_pool(str(p))

    def test_rejects_social_media(self, tmp_path):
        p = _write_pool(tmp_path, [_mk_entry("a", domains=["s1"], title="Export TikTok comments",
                                             note="TikTok 评论导出")])
        with pytest.raises(ValueError, match="排除域"):
            load_pool(str(p))

    def test_rejects_oauth_deep_credential(self, tmp_path):
        p = self._pool_with(tmp_path, note="GSC 数据拉取做 SEO")
        with pytest.raises(ValueError, match="排除域"):
            load_pool(str(p))

    def test_rejects_finance_dex(self, tmp_path):
        p = self._pool_with(tmp_path, note="DEX 总锁仓值抓取")
        with pytest.raises(ValueError, match="排除域"):
            load_pool(str(p))

    def test_excluded_verdict_not_judged_by_patterns(self, tmp_path):
        """excluded 条目不走排除域判定（本就是被排除记录，只留痕）。"""
        p = _write_pool(tmp_path, [_mk_entry("a", verdict="excluded", domains=None,
                                             note="博彩类需求（法务排除）")])
        assert len(load_pool(str(p))) == 1

    def test_rejects_retired_scenario_domains(self, tmp_path):
        """8 场景外形状（s2/s10）不入池：in_domain 引用被裁场景即拒绝。"""
        p = _write_pool(tmp_path, [_mk_entry("a", domains=["s2"])])
        with pytest.raises(ValueError, match="s2"):
            load_pool(str(p))
        p10 = _write_pool(tmp_path, [_mk_entry("b", domains=["s10"])])
        with pytest.raises(ValueError, match="s10"):
            load_pool(str(p10))


class TestRealArtifactsR2:
    """R2 真实产物（池重生成后跑；不触网）。R1 产物作废留档不加载。"""

    POOL = "spikes/coverage/pool_r2.json"
    SNAPSHOT = "spikes/evidence/coverage/pool_snapshot_r2.json"

    def test_r2_pool_loads_with_thresholds(self):
        entries = load_pool(self.POOL)
        assert len(entries) >= 60  # A.10 池规模下限
        in_dom = [e for e in entries if e["verdict"] == "in_domain"]
        assert len(in_dom) >= 35
        assert len({e["community"] for e in in_dom}) >= 2  # ≥2 来源
        assert len(select_sample(entries, 30)) == 30  # 选样框充足

    def test_r2_snapshot_matches_working_pool(self):
        import json as _json
        snap = _json.loads(open(self.SNAPSHOT, encoding="utf-8").read())
        work = _json.loads(open(self.POOL, encoding="utf-8").read())
        assert pool_digest(snap["entries"]) == pool_digest(work["entries"])


class TestRealSampleR2:
    """R2 样本复算与冻结（T1.78；样本=stage2 产物 sample_r2.json）。"""

    POOL = "spikes/coverage/pool_r2.json"
    SAMPLE = "spikes/coverage/sample_r2.json"

    def test_r2_sample_matches_mechanical_selection(self):
        pool = load_pool(self.POOL)
        entries = load_sample(self.SAMPLE, self.POOL)
        assert [e["id"] for e in entries] == [e["id"] for e in select_sample(pool, 30)]

    def test_r2_sample_loads_and_shapes_frozen(self):
        entries = load_sample(self.SAMPLE, self.POOL)
        assert len(entries) == 30
        for e in entries:
            assert e["shape_digest"].startswith("sha256:")

    def test_r2_sample_pool_ref_pins_full_pool(self, tmp_path):
        pool = load_pool(self.POOL)
        tampered = [dict(e) for e in pool]
        tampered[0]["excerpt"] = tampered[0]["excerpt"] + "（事后追加）"
        p = tmp_path / "tampered_pool_r2.json"
        p.write_text(json.dumps({"meta": {}, "entries": tampered}, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError, match="pool_ref"):
            load_sample(self.SAMPLE, str(p))

    def test_r2_pool_fetch_times_all_present(self):
        for e in load_pool(self.POOL):
            assert e["fetched_at"]

    def test_r2_sample_attempt_kinds_valid(self):
        entries = load_sample(self.SAMPLE, self.POOL)
        for e in entries:
            att = e["attempt"]
            if att["kind"] == "uncoverable":
                assert att["category"] in ("site_not_covered", "capability_missing", "needs_genericization")
                assert att["reason"]
            else:
                assert att["kind"] == "chain" and att["steps"]
                for st in att["steps"]:
                    assert st["block"] and isinstance(st.get("params", {}), dict)


# ---------- 终审 I-1 修复：列表型最小条目核验（假覆盖口封堵）----------

class TestCheckShapeList:
    def test_list_min_items_pass(self):
        assert check_shape({"entries": [{"t": 1}, {"t": 2}, {"t": 3}]},
                           {"list_key": "entries", "min_items": 3}) is True

    def test_list_min_items_fail_on_short_list(self):
        assert check_shape({"entries": []}, {"list_key": "entries", "min_items": 3}) is False

    def test_list_min_items_fail_on_missing_or_non_list(self):
        assert check_shape({}, {"list_key": "entries", "min_items": 3}) is False
        assert check_shape({"entries": "not-a-list"}, {"list_key": "entries", "min_items": 1}) is False

    def test_rows_semantics_unchanged(self):
        assert check_shape({"rows": 5}, {"title_row": True, "min_point_rows": 3}) is True
        assert check_shape({"rows": 2}, {"title_row": True, "min_point_rows": 3}) is False


class TestExclusionWindowWidened:
    """终审 I-2：排除域证据在 excerpt/url 的条目入池即拒（校验窗扩至四字段）。"""

    def test_rejects_when_evidence_in_excerpt(self, tmp_path):
        p = _write_pool(tmp_path, [_mk_entry("a", domains=["s1"],
            excerpt="pulls data from Google Search Console (GSC) API")])
        with pytest.raises(ValueError, match="排除域"):
            load_pool(str(p))

    def test_rejects_when_evidence_in_url(self, tmp_path):
        p = _write_pool(tmp_path, [_mk_entry("a", domains=["s1"],
            url="https://youtube.com/watch?v=x", title="digest tool", note="聚合")])
        with pytest.raises(ValueError, match="排除域"):
            load_pool(str(p))


class TestReportTitle:
    """T1.79/终审 minor：报告头轮次参数化（R2 复判不得错标 T1.65e 轮次）。"""

    def test_default_title_is_r1(self, tmp_path):
        t = tally([])
        out = tmp_path / "r.md"
        write_report(out, [], t, out_of_domain={"total": 0, "top": []},
                     sample_meta={"pool_ref": "n/a", "supply_side": 0, "demand_side": 0})
        assert "T1.65e" in out.read_text(encoding="utf-8")

    def test_custom_title_overrides(self, tmp_path):
        t = tally([])
        out = tmp_path / "r2.md"
        write_report(out, [], t, out_of_domain={"total": 0, "top": []},
                     sample_meta={"pool_ref": "n/a", "supply_side": 0, "demand_side": 0},
                     title="MS-1G 覆盖率复判报告（R2 产出，A.10 R2）")
        text = out.read_text(encoding="utf-8")
        assert "复判报告（R2 产出" in text and "T1.65e" not in text

"""T1.65b/c/d 覆盖实验产线单测（离线，不触网）。"""
from __future__ import annotations

import json

import pytest

from spikes.coverage_runner import (
    KNOWN_DOMAINS,
    load_pool,
    load_sample,
    select_sample,
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

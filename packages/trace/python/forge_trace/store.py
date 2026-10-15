"""RecordingsStore：本地登记表 + 轨迹目录 + 脱敏映射目录（docs/11 §3 C2）。

布局：
  root/recordings.sqlite          recordings/annotations 两表（M07 §4 接口约定字段）
  root/traces/<trace_ref>/        四件套（冻结格式，写盘后过 proto validate 自检）
  root/redaction_maps/            值→占位符映射表（仅本机，docs/11 §3 C8；T1.23 启用）
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from forge_proto.format import write_ndjson
from forge_proto.trace import Manifest, NetworkLog, Step, validate_trace_dir

TRACE_REF_PREFIX = "tr_"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Annotation:
    trace_ref: str
    step_seq: int
    element_ref: str
    hint: str
    created_at: str


@dataclass(frozen=True)
class Recording:
    trace_ref: str
    site: str
    created_at: str
    fragile_steps: tuple[int, ...]
    annotations: tuple[Annotation, ...]
    trace_dir: Path


class RecordingsStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.traces_dir = self.root / "traces"
        self.redaction_dir = self.root / "redaction_maps"
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self.redaction_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.root / "recordings.sqlite")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS recordings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_ref TEXT UNIQUE NOT NULL,
                site TEXT NOT NULL,
                created_at TEXT NOT NULL,
                fragile_steps_json TEXT NOT NULL DEFAULT '[]')"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS annotations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_ref TEXT NOT NULL,
                step_seq INTEGER NOT NULL,
                element_ref TEXT NOT NULL,
                hint TEXT NOT NULL,
                created_at TEXT NOT NULL)"""
        )
        self._conn.commit()

    def allocate(self, site: str) -> str:
        """trace_ref 分配（C2：tr_<UTC 时间戳>_<8hex>，登记表内唯一）。"""
        for _ in range(16):
            ref = (
                f"{TRACE_REF_PREFIX}"
                f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                f"_{secrets.token_hex(4)}"
            )
            row = self._conn.execute(
                "SELECT 1 FROM recordings WHERE trace_ref=?", (ref,)
            ).fetchone()
            if row is None:
                return ref
        raise RuntimeError("trace_ref 分配失败：连续冲突（异常罕见）")

    def save_trace(
        self,
        trace_ref: str,
        manifest: Manifest,
        steps: tuple[Step, ...],
        snapshots: dict[int, str],
        network: NetworkLog,
    ) -> None:
        d = self.traces_dir / trace_ref
        (d / "snapshots").mkdir(parents=True, exist_ok=True)
        manifest_doc = {
            "format_version": manifest.format_version,
            "site": manifest.site,
            "login_steps": list(manifest.login_steps),
            "time_sensitive_steps": [
                {"seq": t.seq, "tolerance_ms": t.tolerance_ms}
                for t in manifest.time_sensitive_steps
            ],
        }
        (d / "manifest.yaml").write_text(
            yaml.safe_dump(manifest_doc, allow_unicode=True, sort_keys=True), encoding="utf-8"
        )
        write_ndjson(
            d / "steps.ndjson",
            [
                {
                    "seq": s.seq,
                    "action": s.action,
                    "target_selector": s.target_selector,
                    "dom_anchor": s.dom_anchor,
                    "value": s.value,
                    "wait_condition": s.wait_condition,
                    "ts_offset": s.ts_offset,
                }
                for s in steps
            ],
        )
        (d / "network.json").write_text(
            json.dumps(
                {
                    "captured_at": network.captured_at,
                    "entries": [
                        {
                            "url": e.url,
                            "method": e.method,
                            "status": e.status,
                            "mime_type": e.mime_type,
                            "request_body": e.request_body,
                            "response_body": e.response_body,
                        }
                        for e in network.entries
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        for seq, html in snapshots.items():
            (d / "snapshots" / f"{seq:06d}.html").write_text(html, encoding="utf-8")
        errors = validate_trace_dir(d)
        if errors:
            raise ValueError("trace 目录自检失败: " + "; ".join(errors))
        self._conn.execute(
            "INSERT INTO recordings(trace_ref, site, created_at) VALUES (?, ?, ?)",
            (trace_ref, manifest.site, _utc_now_iso()),
        )
        self._conn.commit()

    def get(self, trace_ref: str) -> Recording:
        row = self._conn.execute(
            "SELECT trace_ref, site, created_at, fragile_steps_json FROM recordings WHERE trace_ref=?",
            (trace_ref,),
        ).fetchone()
        if row is None:
            raise KeyError(f"未知 trace_ref: {trace_ref}")
        annotations = tuple(
            Annotation(
                trace_ref=r[1], step_seq=r[2], element_ref=r[3], hint=r[4], created_at=r[5]
            )
            for r in self._conn.execute(
                """SELECT id, trace_ref, step_seq, element_ref, hint, created_at
                   FROM annotations WHERE trace_ref=? ORDER BY id""",
                (trace_ref,),
            )
        )
        return Recording(
            trace_ref=row[0],
            site=row[1],
            created_at=row[2],
            fragile_steps=tuple(sorted(set(json.loads(row[3])))),
            annotations=annotations,
            trace_dir=self.traces_dir / trace_ref,
        )

    def annotate(self, trace_ref: str, step_seq: int, element_ref: str, hint: str) -> Annotation:
        created_at = _utc_now_iso()
        self._conn.execute(
            """INSERT INTO annotations(trace_ref, step_seq, element_ref, hint, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (trace_ref, step_seq, element_ref, hint, created_at),
        )
        self._conn.commit()
        return Annotation(
            trace_ref=trace_ref,
            step_seq=step_seq,
            element_ref=element_ref,
            hint=hint,
            created_at=created_at,
        )

    def mark_fragile(self, trace_ref: str, seqs) -> None:
        row = self._conn.execute(
            "SELECT fragile_steps_json FROM recordings WHERE trace_ref=?", (trace_ref,)
        ).fetchone()
        if row is None:
            raise KeyError(f"未知 trace_ref: {trace_ref}")
        merged = sorted(set(json.loads(row[0])) | set(int(s) for s in seqs))
        self._conn.execute(
            "UPDATE recordings SET fragile_steps_json=? WHERE trace_ref=?",
            (json.dumps(merged), trace_ref),
        )
        self._conn.commit()

    def list(self) -> tuple[Recording, ...]:
        refs = [
            r[0]
            for r in self._conn.execute("SELECT trace_ref FROM recordings ORDER BY id")
        ]
        return tuple(self.get(ref) for ref in refs)

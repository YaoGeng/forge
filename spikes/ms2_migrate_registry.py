"""MS-2 生产注册表迁移（docs/17 部署段）：本地证据库 → 生产 PG SQL dump。

生产 PG 注册表为空（MS-1E/1F 数据在 spikes/evidence/ms1e_store/server.db）；
本脚本读 sqlite 六表（blocks/block_versions/apps/app_versions/block_refs/
certification_runs）生成 INSERT + setval 的 SQL 文件，供服务器侧
`docker exec -i aim-pg psql -U postgres -d forge` 执行。
用法：python spikes/ms2_migrate_registry.py > ms2_registry.sql
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
SRC = _ROOT / "spikes" / "evidence" / "ms1e_store" / "server.db"

TABLES = {
    "blocks": ["id", "name", "distribution", "owner_id", "created_at"],
    "block_versions": ["id", "block_id", "version", "change_kind",
                       "certification_level", "reliability_json", "side_effects",
                       "domains_json", "created_at"],
    "apps": ["id", "name", "title", "owner_id", "created_at"],
    "app_versions": ["id", "app_id", "version", "status", "composition_json",
                     "user_input_schema_json", "created_at"],
    "block_refs": ["id", "app_id", "block_name", "base_version", "patch_window"],
    "certification_runs": ["id", "subject_type", "subject_id", "version", "level",
                           "n", "pass", "live_pass_rate", "regression_pass_rate",
                           "env_fingerprint_json", "fail_json", "attestation_sig",
                           "accepted_report_hashes", "batch_id", "plan_json",
                           "started_at", "finished_at", "verdict"],
}
JSON_COLS = {"reliability_json", "domains_json", "composition_json",
             "user_input_schema_json", "patch_window", "env_fingerprint_json",
             "fail_json", "accepted_report_hashes", "plan_json"}
BOOL_COLS = {"side_effects"}


def esc(v) -> str:
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"


def main() -> int:
    con = sqlite3.connect(SRC)
    con.row_factory = sqlite3.Row
    print("-- MS-2 注册表迁移（生成于本地证据库，目标 forge@aim-pg）")
    print("BEGIN;")
    for table, cols in TABLES.items():
        try:
            rows = con.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
        except sqlite3.OperationalError:
            print(f"-- 跳过 {table}（源库无此表）")
            continue
        if not rows:
            print(f"-- {table}: 源库 0 行，跳过")
            continue
        print(f"\n-- {table}: {len(rows)} 行")
        for r in rows:
            vals = []
            for c in cols:
                v = r[c]
                if v is None:
                    vals.append("NULL")
                elif c in BOOL_COLS:
                    vals.append("TRUE" if v else "FALSE")
                elif c in JSON_COLS:
                    # sqlite 里 JSON 列是文本（或已是合法 JSON 字符串）
                    vals.append(esc(v) + "::json")
                elif isinstance(v, float):
                    vals.append(repr(v))
                else:
                    vals.append(esc(v))
            print(f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
                  f"({', '.join(vals)});")
        print(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
              f"(SELECT COALESCE(MAX(id), 1) FROM {table}));")
    print("COMMIT;")
    total = con.execute("SELECT (SELECT count(*) FROM blocks) + "
                        "(SELECT count(*) FROM app_versions)").fetchone()[0]
    print(f"-- 源库校验：blocks + app_versions 共 {total} 行", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

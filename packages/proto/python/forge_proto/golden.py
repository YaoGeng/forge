"""golden/ 三件套（run_meta.json / expected_steps.ndjson / network_stubs.json）的类型与校验。

冻结基线：M07 §4（golden 不随积木包分发；值脱敏为占位符——占位符格式归 M09 细化）。
表达细节裁定：docs/09-MS1B执行计划.md §3（C5/C6）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .format import (
    FormatError,
    opt_str,
    parse_json_object,
    reject_extra_fields,
    require_iso8601,
    require_str,
)
from .trace import load_network, load_steps


@dataclass(frozen=True)
class RunMeta:
    environment_fingerprint: str
    captured_at: str
    source_cert_run_id: str | None


def load_run_meta(path: str | Path) -> RunMeta:
    where = str(path)
    doc = parse_json_object(Path(path).read_text(encoding="utf-8"), where)
    reject_extra_fields(doc, {"environment_fingerprint", "captured_at", "source_cert_run_id"}, where)
    return RunMeta(
        environment_fingerprint=require_str(doc, "environment_fingerprint", where),
        captured_at=require_iso8601(doc.get("captured_at"), f"{where}: captured_at"),
        source_cert_run_id=opt_str(doc, "source_cert_run_id", where),
    )


def validate_golden_dir(golden_dir: str | Path) -> list[str]:
    """返回错误列表；空列表 = 通过。三件套：run_meta / expected_steps / network_stubs。"""
    d = Path(golden_dir)
    errors: list[str] = []
    run_meta_path = d / "run_meta.json"
    expected_path = d / "expected_steps.ndjson"
    stubs_path = d / "network_stubs.json"

    if not run_meta_path.exists():
        errors.append(f"缺少 {run_meta_path}")
    else:
        try:
            load_run_meta(run_meta_path)
        except FormatError as exc:
            errors.append(str(exc))
    if not expected_path.exists():
        errors.append(f"缺少 {expected_path}")
    else:
        try:
            load_steps(expected_path)
        except FormatError as exc:
            errors.append(str(exc))
    if not stubs_path.exists():
        errors.append(f"缺少 {stubs_path}")
    else:
        try:
            load_network(stubs_path)
        except FormatError as exc:
            errors.append(str(exc))
    return errors

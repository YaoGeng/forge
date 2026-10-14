"""trace/ 目录四件套（manifest.yaml / steps.ndjson / snapshots/ / network.json）的类型与校验。

冻结基线：M07 §4（docs/03-模块设计/M07-BlockSDK与测试框架.md）。
表达细节裁定：docs/09-MS1B执行计划.md §3（C1-C4）——变更走 minor + 四方适配评审。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .format import (
    FormatError,
    opt_str,
    read_ndjson,
    reject_extra_fields,
    require_int,
    require_iso8601,
    require_str,
)

CURRENT_MAJOR = "1"
ACTIONS = ("click", "input", "scroll", "wait", "nav")  # M07 §2/§3.3，M06 §3.2 同源
_VERSION_SEPARATOR = "."


@dataclass(frozen=True)
class TimeSensitiveStep:
    seq: int
    tolerance_ms: int | None


@dataclass(frozen=True)
class Manifest:
    format_version: str
    site: str
    login_steps: tuple[int, ...]
    time_sensitive_steps: tuple[TimeSensitiveStep, ...]


@dataclass(frozen=True)
class Step:
    seq: int
    action: str
    target_selector: str | None
    dom_anchor: str | None
    value: str | None
    wait_condition: str | None
    ts_offset: int


@dataclass(frozen=True)
class NetworkEntry:
    url: str
    method: str
    status: int
    mime_type: str | None
    request_body: str | None
    response_body: str | None


@dataclass(frozen=True)
class NetworkLog:
    captured_at: str
    entries: tuple[NetworkEntry, ...]


def _parse_major(version: str, where: str) -> str:
    if not isinstance(version, str) or not version:
        raise FormatError(f"{where}: format_version 必须是非空字符串")
    parts = version.split(_VERSION_SEPARATOR)
    if len(parts) > 2 or not all(p.isdigit() for p in parts):
        raise FormatError(f"{where}: format_version 必须形如 \"主\" 或 \"主.次\"，得到 {version!r}")
    return parts[0]


def load_manifest(source: str | Path) -> Manifest:
    """source 为 YAML 文本或文件路径（C1 裁定字段）。"""
    where = str(source)
    if isinstance(source, Path) or ("\n" not in str(source) and Path(source).exists()):
        doc = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
        where = str(source)
    else:
        doc = yaml.safe_load(source)
    if not isinstance(doc, dict):
        raise FormatError(f"{where}: manifest 必须是 YAML 映射")
    reject_extra_fields(doc, {"format_version", "site", "login_steps", "time_sensitive_steps"}, where)
    major = _parse_major(doc.get("format_version"), where)
    _ = major  # 完整性在 is_compatible；此处仅做格式校验
    manifest = Manifest(
        format_version=doc["format_version"],
        site=require_str(doc, "site", where),
        login_steps=_load_login_steps(doc, where),
        time_sensitive_steps=_load_time_sensitive(doc, where),
    )
    return manifest


def _load_login_steps(doc: dict, where: str) -> tuple[int, ...]:
    raw = doc.get("login_steps")
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(isinstance(v, bool) or not isinstance(v, int) for v in raw):
        raise FormatError(f"{where}: login_steps 必须是整数数组")
    return tuple(raw)


def _load_time_sensitive(doc: dict, where: str) -> tuple[TimeSensitiveStep, ...]:
    raw = doc.get("time_sensitive_steps")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise FormatError(f"{where}: time_sensitive_steps 必须是数组")
    out: list[TimeSensitiveStep] = []
    for i, item in enumerate(raw):
        w = f"{where}: time_sensitive_steps[{i}]"
        if not isinstance(item, dict):
            raise FormatError(f"{w}: 必须是映射")
        reject_extra_fields(item, {"seq", "tolerance_ms"}, w)
        tolerance = item.get("tolerance_ms")
        if tolerance is not None and (isinstance(tolerance, bool) or not isinstance(tolerance, int)):
            raise FormatError(f"{w}: tolerance_ms 必须是整数或 null")
        out.append(TimeSensitiveStep(seq=require_int(item, "seq", w), tolerance_ms=tolerance))
    return tuple(out)


def is_compatible(manifest: Manifest) -> bool:
    """主段等于本包实现的主版本即兼容；次版本向后兼容（M07 §4 接口约定）。"""
    return _parse_major(manifest.format_version, "<manifest>") == CURRENT_MAJOR


def load_steps(path: str | Path) -> tuple[Step, ...]:
    rows = read_ndjson(path)
    if not rows:
        raise FormatError(f"{path}: steps.ndjson 不能为空")
    steps: list[Step] = []
    prev_seq = 0
    prev_ts = -1
    for lineno, doc in rows:
        where = f"{path}:{lineno}"
        reject_extra_fields(
            doc,
            {"seq", "action", "target_selector", "dom_anchor", "value", "wait_condition", "ts_offset"},
            where,
        )
        seq = require_int(doc, "seq", where)
        action = require_str(doc, "action", where)
        if seq != prev_seq + 1:
            raise FormatError(f"{where}: seq 必须 from 1 连续递增，得到 {seq}（前一行 {prev_seq}）")
        if action not in ACTIONS:
            raise FormatError(f"{where}: action {action!r} 不在 {ACTIONS}")
        ts = require_int(doc, "ts_offset", where)
        if ts < prev_ts:
            raise FormatError(f"{where}: ts_offset 必须非递减（{ts} < {prev_ts}）")
        steps.append(Step(
            seq=seq,
            action=action,
            target_selector=opt_str(doc, "target_selector", where),
            dom_anchor=opt_str(doc, "dom_anchor", where),
            value=opt_str(doc, "value", where),
            wait_condition=opt_str(doc, "wait_condition", where),
            ts_offset=ts,
        ))
        prev_seq, prev_ts = seq, ts
    return tuple(steps)


def load_network(path: str | Path) -> NetworkLog:
    where = str(path)
    import json

    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise FormatError(f"{where}: network.json 必须是 JSON 对象")
    reject_extra_fields(doc, {"captured_at", "entries"}, where)
    captured_at = require_iso8601(doc.get("captured_at"), f"{where}: captured_at")
    raw_entries = doc.get("entries")
    if not isinstance(raw_entries, list):
        raise FormatError(f"{where}: entries 必须是数组")
    entries: list[NetworkEntry] = []
    for i, item in enumerate(raw_entries):
        w = f"{where}: entries[{i}]"
        if not isinstance(item, dict):
            raise FormatError(f"{w}: 必须是 JSON 对象")
        reject_extra_fields(
            item,
            {"url", "method", "status", "mime_type", "request_body", "response_body"},
            w,
        )
        method = require_str(item, "method", w)
        if not method.isupper() or not method.isalpha():
            raise FormatError(f"{w}: method 必须全大写字母，得到 {method!r}")
        status = require_int(item, "status", w)
        entries.append(NetworkEntry(
            url=require_str(item, "url", w),
            method=method,
            status=status,
            mime_type=opt_str(item, "mime_type", w),
            request_body=opt_str(item, "request_body", w),
            response_body=opt_str(item, "response_body", w),
        ))
    return NetworkLog(captured_at=captured_at, entries=tuple(entries))


def validate_trace_dir(trace_dir: str | Path) -> list[str]:
    """返回错误列表；空列表 = 通过。校验 C3 快照与 steps 一一对应。"""
    d = Path(trace_dir)
    errors: list[str] = []
    manifest_path = d / "manifest.yaml"
    steps_path = d / "steps.ndjson"
    network_path = d / "network.json"
    snapshots_dir = d / "snapshots"

    manifest: Manifest | None = None
    steps: tuple[Step, ...] = ()
    if not manifest_path.exists():
        errors.append(f"缺少 {manifest_path}")
    else:
        try:
            manifest = load_manifest(manifest_path)
        except FormatError as exc:
            errors.append(str(exc))
    if not steps_path.exists():
        errors.append(f"缺少 {steps_path}")
    else:
        try:
            steps = load_steps(steps_path)
        except FormatError as exc:
            errors.append(str(exc))
    if not network_path.exists():
        errors.append(f"缺少 {network_path}")
    else:
        try:
            load_network(network_path)
        except FormatError as exc:
            errors.append(str(exc))
    if not snapshots_dir.is_dir():
        errors.append(f"缺少快照目录 {snapshots_dir}")
    elif steps:
        expected = {f"{s.seq:06d}.html" for s in steps}
        actual = {p.name for p in snapshots_dir.iterdir() if p.is_file()}
        for missing in sorted(expected - actual):
            errors.append(f"缺少快照 snapshots/{missing}")
        for extra in sorted(actual - expected):
            errors.append(f"多余快照 snapshots/{extra}（命名须为 {{seq:06d}}.html 且与 steps 一一对应）")
    if manifest is not None and not is_compatible(manifest):
        errors.append(
            f"manifest 主版本 {manifest.format_version!r} 与本实现 {CURRENT_MAJOR}.x 不兼容"
            "（Recorder/Replayer 拒绝不兼容主版本，M07 §4）"
        )
    return errors

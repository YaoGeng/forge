"""轨迹格式 v1 的底层解析工具：FormatError、NDJSON、ISO8601。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class FormatError(ValueError):
    """解析/校验失败；消息含位置（文件:行）。"""


def read_ndjson(path: str | Path) -> list[tuple[int, dict]]:
    """逐行解析 NDJSON：空行容错；残行抛 FormatError（带行号）。"""
    out: list[tuple[int, dict]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                doc = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise FormatError(f"{path}:{lineno}: NDJSON 行解析失败: {exc}") from exc
            if not isinstance(doc, dict):
                raise FormatError(f"{path}:{lineno}: 行必须是 JSON 对象")
            out.append((lineno, doc))
    return out


def write_ndjson(path: str | Path, docs: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for doc in docs:
            fh.write(json.dumps(doc, ensure_ascii=False) + "\n")


def parse_json_object(text: str, where: str) -> dict:
    """JSON 文本 → 对象；解析失败统一为 FormatError（终审 Important-1）。"""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FormatError(f"{where}: JSON 解析失败: {exc}") from exc
    if not isinstance(doc, dict):
        raise FormatError(f"{where}: 必须是 JSON 对象")
    return doc


def parse_yaml_object(text: str, where: str) -> dict:
    """YAML 文本 → 对象；解析失败统一为 FormatError（终审 Important-1）。"""
    import yaml

    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise FormatError(f"{where}: YAML 解析失败: {exc}") from exc
    if not isinstance(doc, dict):
        raise FormatError(f"{where}: 必须是 YAML 映射")
    return doc


def require_iso8601(value, where: str) -> str:
    if not isinstance(value, str):
        raise FormatError(f"{where}: 时间戳必须是字符串")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise FormatError(f"{where}: 非法 ISO8601 时间戳 {value!r}") from exc
    return value


def require_str(doc: dict, key: str, where: str) -> str:
    value = doc.get(key)
    if not isinstance(value, str) or not value:
        raise FormatError(f"{where}: 缺必填字符串字段 {key}")
    return value


def opt_str(doc: dict, key: str, where: str, *, allow_empty: bool = True) -> str | None:
    value = doc.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise FormatError(f"{where}: 字段 {key} 必须是字符串或 null")
    if not allow_empty and not value:
        raise FormatError(f"{where}: 字段 {key} 为空串（Schema minLength 1）")
    return value


def require_int(doc: dict, key: str, where: str) -> int:
    value = doc.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise FormatError(f"{where}: 缺必填整数字段 {key}")
    return value


def reject_extra_fields(doc: dict, allowed: set[str], where: str) -> None:
    extra = set(doc) - allowed
    if extra:
        raise FormatError(f"{where}: 多余字段 {sorted(extra)}（冻结格式，新增字段走 minor）")

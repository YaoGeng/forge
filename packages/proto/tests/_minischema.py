"""极简 JSON Schema（draft-07 子集）校验器——仅用于「Schema 与 Python 校验器对齐」测试。

支持关键字：type / enum / required / properties / additionalProperties(false) /
items / minItems / minimum / pattern。有意不实现 ref/oneOf 等复杂特性——proto 的
schema 刻意保持在这个子集内（跨语言契约工件，复杂约束由各语言校验器承载）。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _check_type(value: Any, name: str) -> bool:
    expected = _TYPES[name]
    if name in ("integer", "number") and isinstance(value, bool):
        return False  # bool 是 int 子类，显式排除
    if name == "boolean" and not isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _check_datetime(value: str) -> bool:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(text)
        return True
    except ValueError:
        return False


def validate(instance: Any, schema: dict) -> list[str]:
    """返回错误列表；空列表 = 通过。错误格式 "path: 原因"。"""
    return _validate(instance, schema, "$")


def _validate(instance: Any, schema: dict, path: str) -> list[str]:
    errors: list[str] = []
    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        if not any(_check_type(instance, n) for n in names):
            errors.append(f"{path}: 类型应为 {types}，实际 {type(instance).__name__}")
            return errors
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: 不在枚举 {schema['enum']} 内")
    if "minimum" in schema and isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if instance < schema["minimum"]:
            errors.append(f"{path}: 小于最小值 {schema['minimum']}")
    if "pattern" in schema and isinstance(instance, str):
        if not re.search(schema["pattern"], instance):
            errors.append(f"{path}: 不匹配模式 {schema['pattern']}")
    if schema.get("format") == "date-time" and isinstance(instance, str):
        # draft-07 里 format 本是注解；proto 有意将其作为硬约束（与 Python 校验器对齐）
        if not _check_datetime(instance):
            errors.append(f"{path}: 非法 ISO8601 时间戳 {instance!r}")
    if "minItems" in schema and isinstance(instance, list):
        if len(instance) < schema["minItems"]:
            errors.append(f"{path}: 元素数少于 {schema['minItems']}")
    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            errors += _validate(item, schema["items"], f"{path}[{i}]")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: 缺必填字段 {key}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{path}: 多余字段 {key}")
        for key, sub in props.items():
            if key in instance:
                errors += _validate(instance[key], sub, f"{path}.{key}")
    return errors

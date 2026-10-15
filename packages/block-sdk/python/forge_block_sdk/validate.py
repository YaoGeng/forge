"""block.yaml v2 / interactions.yaml 手写校验器（无 schema 引擎；错误一律 ValidationError + path）。"""
from __future__ import annotations

import datetime
import re
from pathlib import Path, PurePosixPath

import yaml

from .model import (
    BLOCK_FIELDS,
    FAMILIES,
    BlockSpec,
    InteractionSpec,
    PermissionSpec,
    ReliabilitySpec,
    RuntimeSpec,
)

SITE_CHANGE_TIERS = ("standard", "medium", "high", "protected")
ADAPTER_SUFFIXES = {"python": (".py",), "node": (".js", ".mjs"), "agent": (".md",)}
PERMISSION_TYPES = ("domain", "credential", "ai", "interact")
PERMISSION_VALUE_ENUMS = {"ai": ("fast", "deep"), "interact": ("input", "login")}
INTERACTION_TYPES = ("input", "login", "confirm", "captcha", "review")
RELIABILITY_LEVELS = ("C0", "C1", "C2")

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})$")
DOMAIN_RE = re.compile(r"^([a-z0-9-]+\.)+[a-z]{2,}$")
CAPABILITY_RE = re.compile(r"^(%s)(_[a-z0-9_]+)?$" % "|".join(FAMILIES))


class ValidationError(ValueError):
    def __init__(self, message: str, path: str = ""):
        super().__init__(f"{path}: {message}" if path else message)
        self.path = path


def _fail(message: str, path: str) -> None:
    raise ValidationError(message, path)


def _mapping(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        _fail("应为 mapping", path)
    return value


def _nonempty_str(value: object, path: str, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("应为非空字符串", f"{path}.{key}")
    return value


def _int_in(value: object, path: str, key: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(f"应为 ≥{minimum} 的整数", f"{path}.{key}")
    return value


def _resolve(source: str | Path, default_name: str) -> tuple[str, str]:
    """把 str-YAML 文本 / 文件路径 / 目录归一为 (yaml_text, label)；文件缺失报 ValidationError。"""
    if isinstance(source, str) and "\n" in source:
        return source, default_name
    p = Path(source)
    target = p if p.is_file() else p / default_name
    try:
        return target.read_text(encoding="utf-8"), str(target)
    except OSError as exc:
        _fail(f"文件不存在或不可读：{exc}", str(target))
    except UnicodeDecodeError as exc:
        _fail(f"文件非 UTF-8 编码：{exc}", str(target))
    raise  # 不可达；安抚类型检查


def _parse_yaml(text: str, label: str) -> object:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        _fail(f"YAML 解析失败：{exc}", label)
        raise  # 不可达；安抚类型检查


def load_block(source: str | Path) -> BlockSpec:
    """加载并校验 block.yaml（source 为目录、文件路径或 YAML 文本）。"""
    text, label = _resolve(source, "block.yaml")
    data = _mapping(_parse_yaml(text, label), label)
    return _build_block(data, label)


def _build_block(data: dict, root: str) -> BlockSpec:
    unknown = sorted(repr(k) for k in data if not isinstance(k, str) or k not in BLOCK_FIELDS)
    if unknown:
        _fail(f"未知字段：{', '.join(unknown)}", root)

    sv = data.get("schema_version")
    if isinstance(sv, bool) or not isinstance(sv, int) or sv != 2:
        _fail("必须为整数 2", f"{root}.schema_version")
    kind = _nonempty_str(data.get("kind"), root, "kind")
    if kind == "composite_block":
        _fail("composite_block 不在本 SDK 版本范围（支持随 M02 画布卡）", f"{root}.kind")
    if kind != "block":
        _fail("必须为 block", f"{root}.kind")

    name = _nonempty_str(data.get("name"), root, "name")
    if not NAME_RE.match(name):
        _fail("必须匹配 ^[a-z][a-z0-9_]*$", f"{root}.name")
    version = _nonempty_str(data.get("version"), root, "version")
    if not SEMVER_RE.match(version):
        _fail("必须为严格 X.Y.Z 三段数字 semver", f"{root}.version")
    _nonempty_str(data.get("title"), root, "title")

    tier = _nonempty_str(data.get("site_change_tier"), root, "site_change_tier")
    if tier not in SITE_CHANGE_TIERS:
        _fail(f"必须为 {'/'.join(SITE_CHANGE_TIERS)} 之一", f"{root}.site_change_tier")

    side_effects = data.get("side_effects")
    if not isinstance(side_effects, bool):
        _fail("必须为布尔值", f"{root}.side_effects")

    caps_raw = data.get("capabilities")
    if not isinstance(caps_raw, list):
        _fail("应为字符串列表", f"{root}.capabilities")
    capabilities = []
    for i, cap in enumerate(caps_raw):
        if not isinstance(cap, str) or not CAPABILITY_RE.match(cap):
            _fail("必须是 M05 §4 家族（可带 _变体）", f"{root}.capabilities[{i}]")
        capabilities.append(cap)

    perms_raw = data.get("permissions")
    if not isinstance(perms_raw, list):
        _fail("应为声明列表", f"{root}.permissions")
    permissions = []
    for i, item in enumerate(perms_raw):
        perm_path = f"{root}.permissions[{i}]"
        perm = _mapping(item, perm_path)
        if set(perm) != {"type", "value", "required"}:
            _fail("字段必须恰为 type/value/required", perm_path)
        ptype = perm["type"]
        if ptype not in PERMISSION_TYPES:
            _fail(f"必须为 {'/'.join(PERMISSION_TYPES)} 之一", f"{perm_path}.type")
        value = _nonempty_str(perm["value"], perm_path, "value")
        if ptype == "domain" and not DOMAIN_RE.match(value):
            _fail("必须为域名后缀", f"{perm_path}.value")
        if ptype in PERMISSION_VALUE_ENUMS and value not in PERMISSION_VALUE_ENUMS[ptype]:
            _fail(f"必须为 {'/'.join(PERMISSION_VALUE_ENUMS[ptype])} 之一", f"{perm_path}.value")
        if not isinstance(perm["required"], bool):
            _fail("必须为布尔值", f"{perm_path}.required")
        permissions.append(PermissionSpec(ptype, value, perm["required"]))

    rt = _mapping(data.get("runtime"), f"{root}.runtime")
    if set(rt) != {"adapter", "entry", "timeout_sec"}:
        _fail("字段必须恰为 adapter/entry/timeout_sec", f"{root}.runtime")
    adapter = rt["adapter"]
    if not isinstance(adapter, str) or adapter not in ADAPTER_SUFFIXES:
        _fail(f"必须为 {'/'.join(ADAPTER_SUFFIXES)} 之一", f"{root}.runtime.adapter")
    entry = _nonempty_str(rt["entry"], f"{root}.runtime", "entry")
    entry_norm = entry.replace("\\", "/")
    entry_abs = (
        entry_norm.startswith("/")
        or entry_norm.startswith("//")
        or re.match(r"^[A-Za-z]:", entry_norm)
        or ".." in PurePosixPath(entry_norm).parts
    )
    if entry_abs:
        _fail("entry 必须是积木目录内相对路径（禁止绝对路径与 .. 分量）", f"{root}.runtime.entry")
    timeout_sec = _int_in(rt["timeout_sec"], f"{root}.runtime", "timeout_sec", 1)

    reliability = None
    if data.get("reliability") is not None:
        rel = _mapping(data["reliability"], f"{root}.reliability")
        if set(rel) != {"level", "pass_rate", "samples", "measured_at", "environment"}:
            _fail("存在时字段必须恰为 level/pass_rate/samples/measured_at/environment", f"{root}.reliability")
        level = rel["level"]
        if level not in RELIABILITY_LEVELS:
            _fail(f"必须为 {'/'.join(RELIABILITY_LEVELS)} 之一", f"{root}.reliability.level")
        rate = rel["pass_rate"]
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 <= rate <= 1:
            _fail("应为 [0,1] 内数值", f"{root}.reliability.pass_rate")
        measured = rel["measured_at"]
        if isinstance(measured, datetime.datetime):
            _fail("应为 ISO 日期（YYYY-MM-DD），不接受时间戳", f"{root}.reliability.measured_at")
        if isinstance(measured, datetime.date):
            measured = measured.isoformat()
        if not isinstance(measured, str):
            _fail("应为 ISO 日期", f"{root}.reliability.measured_at")
        try:
            if len(measured) != 10:
                raise ValueError
            datetime.date.fromisoformat(measured)
        except ValueError:
            _fail("应为 ISO 日期（YYYY-MM-DD）", f"{root}.reliability.measured_at")
        reliability = ReliabilitySpec(
            level, float(rate), _int_in(rel["samples"], f"{root}.reliability", "samples", 0),
            measured, _nonempty_str(rel["environment"], f"{root}.reliability", "environment"),
        )

    _nonempty_str(data.get("ai_description"), root, "ai_description")

    default_response = data.get("default_response")
    if side_effects:
        if not isinstance(default_response, (str, dict)):
            _fail("副作用积木必须以 str/mapping 声明 default_response", f"{root}.default_response")
    elif default_response is not None:
        _fail("仅 side_effects=true 的积木允许声明", f"{root}.default_response")

    return BlockSpec(
        schema_version=2, kind=kind, name=name, version=version,
        title=data["title"], site_change_tier=tier, side_effects=side_effects,
        capabilities=tuple(capabilities), permissions=tuple(permissions),
        runtime=RuntimeSpec(adapter, entry, timeout_sec),
        reliability=reliability, ai_description=data["ai_description"],
        default_response=default_response,
    )


def load_interactions(source: str | Path) -> tuple[InteractionSpec, ...]:
    """加载并校验 interactions.yaml（顶层列表；login 必含 site）。"""
    text, label = _resolve(source, "interactions.yaml")
    data = _parse_yaml(text, label)
    if not isinstance(data, list):
        _fail("顶层应为列表（空声明写 []）", label)
    items: list[InteractionSpec] = []
    seen: set[str] = set()
    for i, item in enumerate(data):
        path = f"{label}[{i}]"
        raw = _mapping(item, path)
        allowed = {"id", "type", "title", "schema", "optional", "site"}
        extra = sorted(repr(k) for k in raw if not isinstance(k, str) or k not in allowed)
        if extra:
            _fail(f"未知字段：{', '.join(extra)}", path)
        iid = _nonempty_str(raw.get("id"), path, "id")
        if not NAME_RE.match(iid):
            _fail("必须匹配 ^[a-z][a-z0-9_]*$", f"{path}.id")
        if iid in seen:
            _fail("id 重复", f"{path}.id")
        seen.add(iid)
        itype = _nonempty_str(raw.get("type"), path, "type")
        if itype not in INTERACTION_TYPES:
            _fail(f"必须为 {'/'.join(INTERACTION_TYPES)} 之一", f"{path}.type")
        title = _nonempty_str(raw.get("title"), path, "title")
        schema = raw.get("schema")
        if schema is not None and not isinstance(schema, dict):
            _fail("应为 mapping（JSON Schema 本体）", f"{path}.schema")
        optional = raw.get("optional", False)
        if not isinstance(optional, bool):
            _fail("必须为布尔值", f"{path}.optional")
        site = raw.get("site")
        if itype == "login":
            site = _nonempty_str(site, path, "site")
        elif site is not None:
            _fail("仅 login 类型允许 site 字段", f"{path}.site")
        items.append(InteractionSpec(iid, itype, title, schema, optional, site))
    return tuple(items)


def validate_block_dir(block_dir: str | Path) -> BlockSpec:
    """目录级校验：block.yaml + interactions.yaml + entry 存在性与 adapter 后缀一致。"""
    d = Path(block_dir)
    spec = load_block(d)
    if not (d / "interactions.yaml").is_file():
        _fail("缺少 interactions.yaml", str(d))
    load_interactions(d / "interactions.yaml")
    entry = d / spec.runtime.entry
    if not entry.is_file():
        _fail(f"entry 文件不存在：{spec.runtime.entry}", str(d))
    if entry.suffix.lower() not in ADAPTER_SUFFIXES[spec.runtime.adapter]:
        _fail(
            f"adapter={spec.runtime.adapter} 要求后缀 {'/'.join(ADAPTER_SUFFIXES[spec.runtime.adapter])}",
            f"{d}.runtime.entry",
        )
    return spec

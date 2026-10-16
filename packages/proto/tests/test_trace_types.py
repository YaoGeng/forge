"""轨迹格式 v1 类型与校验器测试（M07 §4 冻结编码；C1-C7 具体化裁定钉死）。"""
import json
from pathlib import Path

import pytest
import yaml

import forge_proto
from forge_proto import (
    FormatError,
    Manifest,
    NetworkEntry,
    NetworkLog,
    RunMeta,
    Step,
    TimeSensitiveStep,
    is_compatible,
    load_manifest,
    load_network,
    load_run_meta,
    load_steps,
    validate_golden_dir,
    validate_trace_dir,
)

CORPUS = Path(__file__).resolve().parent / "corpus"
SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
from _minischema import validate as schema_validate  # noqa: E402


# ---------- 冻结字段名（Review Focus 1：proto 不得超出 M07 §4 语义） ----------

def test_frozen_field_names():
    assert Manifest.__dataclass_fields__.keys() == {
        "format_version", "site", "login_steps", "time_sensitive_steps"}
    assert Step.__dataclass_fields__.keys() == {
        "seq", "action", "target_selector", "dom_anchor", "value",
        "wait_condition", "ts_offset"}
    assert TimeSensitiveStep.__dataclass_fields__.keys() == {"seq", "tolerance_ms"}
    assert NetworkEntry.__dataclass_fields__.keys() == {
        "url", "method", "status", "mime_type", "request_body", "response_body"}
    assert NetworkLog.__dataclass_fields__.keys() == {"captured_at", "entries"}
    assert RunMeta.__dataclass_fields__.keys() == {
        "environment_fingerprint", "captured_at", "source_cert_run_id"}
    assert forge_proto.CURRENT_MAJOR == "1"


# ---------- manifest ----------

VALID_MANIFEST_YAML = """\
format_version: "1.0"
site: hn.algolia.com
login_steps: [2]
time_sensitive_steps:
  - seq: 3
    tolerance_ms: 1500
"""


def test_load_manifest_ok():
    m = load_manifest(VALID_MANIFEST_YAML)
    assert m.format_version == "1.0" and m.site == "hn.algolia.com"
    assert m.login_steps == (2,)
    assert m.time_sensitive_steps == (TimeSensitiveStep(seq=3, tolerance_ms=1500),)


def test_manifest_defaults_and_missing_required():
    m = load_manifest('format_version: "1.0"\nsite: example.com\n')
    assert m.login_steps == () and m.time_sensitive_steps == ()
    with pytest.raises(FormatError):
        load_manifest("site: example.com\n")  # 缺 format_version
    with pytest.raises(FormatError):
        load_manifest('format_version: "1.0"\n')  # 缺 site


def test_major_version_gate():
    assert is_compatible(load_manifest('format_version: "1.0"\nsite: x\n'))
    assert is_compatible(load_manifest('format_version: "1.9"\nsite: x\n'))
    assert is_compatible(load_manifest('format_version: "1"\nsite: x\n'))
    assert not is_compatible(load_manifest('format_version: "2.0"\nsite: x\n'))
    with pytest.raises(FormatError):
        load_manifest('format_version: "v1"\nsite: x\n')
    with pytest.raises(FormatError):
        load_manifest('format_version: "1.2.3"\nsite: x\n')


# ---------- steps.ndjson ----------

def _step_line(**fields) -> str:
    base = {"seq": 1, "action": "click", "target_selector": "#a1",
            "dom_anchor": "main", "value": None, "wait_condition": None,
            "ts_offset": 100}
    seq = fields.pop("seq", 1)
    base["ts_offset"] = seq * 100
    base.update(fields)
    base["seq"] = seq
    return json.dumps(base, ensure_ascii=False)


def test_load_steps_ok_with_value_omitted():
    text = "\n".join([
        _step_line(seq=1),
        _step_line(seq=2, action="input", value="python"),  # input 携带 value
        _step_line(seq=3, action="wait", target_selector=None),  # wait 无选择器 + value 缺省
    ]) + "\n"
    steps = load_steps_text(text)
    assert [s.seq for s in steps] == [1, 2, 3]
    assert steps[1].value == "python" and steps[2].value is None
    assert steps[2].target_selector is None


def load_steps_text(text: str):
    import tempfile
    from pathlib import Path as _P
    f = tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False, encoding="utf-8")
    try:
        f.write(text)
    finally:
        f.close()  # 先落盘再读（Windows 缓冲）
    return load_steps(_P(f.name))


def test_steps_ndjson_malformed_line():
    text = _step_line(seq=1) + "\n{not json\n"
    with pytest.raises(FormatError, match=":2:"):
        load_steps_text(text)  # 错误消息含「文件:行号」且行号=2


def test_steps_ndjson_blank_lines_tolerated():
    text = "\n" + _step_line(seq=1) + "\n\n" + _step_line(seq=2) + "\n\n"
    assert [s.seq for s in load_steps_text(text)] == [1, 2]


def test_steps_invalid_fields():
    cases = [
        [_step_line(seq=1), _step_line(seq=3)],                        # seq 跳号（须连续递增，C2 终审裁定）
        [_step_line(seq=1), _step_line(seq=2, ts_offset=50)],          # ts_offset 递减
        [_step_line(seq=1), _step_line(seq=2, action="type")],         # 动作不在枚举
        [json.dumps({"seq": 0, "action": "click", "ts_offset": 0})],   # seq 从 1 起
        [json.dumps({"seq": 1, "action": "click", "ts_offset": -1})],  # ts_offset 为负（Schema minimum 0）
        [_step_line(seq=1, target_selector="")],                       # 空选择器（Schema minLength 1）
    ]
    for lines in cases:
        with pytest.raises(FormatError):
            load_steps_text("\n".join(lines) + "\n")


# ---------- network.json ----------

def test_load_network_ok():
    doc = {
        "captured_at": "2026-10-15T01:00:00+00:00",
        "entries": [
            {"url": "https://x/api", "method": "GET", "status": 200,
             "mime_type": "application/json", "request_body": None,
             "response_body": "<golden:placeholder>"},
        ],
    }
    import tempfile
    from pathlib import Path as _P
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(doc, f)
    finally:
        f.close()
    log = load_network(_P(f.name))
    assert log.entries[0].method == "GET" and log.entries[0].status == 200
    doc["entries"][0]["method"] = "get"
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(doc, f)
    finally:
        f.close()
    with pytest.raises(FormatError):
        load_network(_P(f.name))  # method 必须大写（C4）


def test_network_captured_at_must_be_iso8601():
    doc = {"captured_at": "yesterday", "entries": []}
    import tempfile
    from pathlib import Path as _P
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(doc, f)
    finally:
        f.close()
    with pytest.raises(FormatError):
        load_network(_P(f.name))


# ---------- trace 目录 ----------

def _build_trace_dir(root: Path, seqs=(1, 2, 3)) -> Path:
    t = root / "trace"
    (t / "snapshots").mkdir(parents=True)
    (t / "manifest.yaml").write_text(VALID_MANIFEST_YAML, encoding="utf-8")
    (t / "steps.ndjson").write_text(
        "\n".join(_step_line(seq=i) for i in seqs) + "\n", encoding="utf-8")
    for i in seqs:
        (t / "snapshots" / f"{i:06d}.html").write_text("<html></html>", encoding="utf-8")
    (t / "network.json").write_text(json.dumps({
        "captured_at": "2026-10-15T01:00:00+00:00", "entries": []}), encoding="utf-8")
    return t


def test_validate_trace_dir_ok(tmp_path):
    assert validate_trace_dir(_build_trace_dir(tmp_path)) == []


def test_snapshots_one_to_one(tmp_path):
    t = _build_trace_dir(tmp_path)
    (t / "snapshots" / "000002.html").unlink()          # 少
    (t / "snapshots" / "000009.html").write_text("x", encoding="utf-8")  # 多
    errors = validate_trace_dir(t)
    joined = "\n".join(errors)
    assert "000002" in joined and "000009" in joined


def test_validate_trace_dir_missing_pieces(tmp_path):
    t = _build_trace_dir(tmp_path)
    (t / "manifest.yaml").unlink()
    errors = validate_trace_dir(t)
    assert any("manifest" in e for e in errors)
    (t / "steps.ndjson").unlink()
    errors = validate_trace_dir(t)
    assert any("steps" in e for e in errors)


# ---------- Schema 与 Python 校验器对齐（Review Focus 5） ----------

def _manifest_doc(**over) -> dict:
    doc = {"format_version": "1.0", "site": "x.com", "login_steps": [],
           "time_sensitive_steps": []}
    doc.update(over)
    return doc


def _step_doc(**over) -> dict:
    doc = {"seq": 1, "action": "click", "target_selector": "#a", "dom_anchor": None,
           "wait_condition": None, "ts_offset": 0}
    doc.update(over)
    return doc


def _entry_doc(**over) -> dict:
    doc = {"url": "https://x/", "method": "GET", "status": 200, "mime_type": None,
           "request_body": None, "response_body": None}
    doc.update(over)
    return doc


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


POSITIVE_DOCS = [
    ("trace.manifest.schema.json", _manifest_doc()),
    ("trace.manifest.schema.json", _manifest_doc(
        login_steps=[2], time_sensitive_steps=[{"seq": 3, "tolerance_ms": None}])),
    ("trace.steps.schema.json", _step_doc()),
    ("trace.steps.schema.json", _step_doc(action="nav", target_selector=None, value="x")),
    ("trace.network.schema.json", {"captured_at": "2026-10-15T01:00:00+00:00",
                                   "entries": [_entry_doc()]}),
    ("golden.schema.json", {"environment_fingerprint": "fp", "captured_at":
                            "2026-10-15T01:00:00+00:00", "source_cert_run_id": None}),
]

NEGATIVE_DOCS = [
    ("trace.manifest.schema.json", _manifest_doc(extra_field=1)),          # 多余字段
    ("trace.manifest.schema.json", _manifest_doc(format_version="v1")),    # 版本格式
    ("trace.steps.schema.json", _step_doc(action="type")),                 # 动作枚举
    ("trace.steps.schema.json", _step_doc(seq=0)),                         # seq 下限
    ("trace.network.schema.json", {"captured_at": "nope", "entries": []}), # 非法时间
    ("golden.schema.json", {"captured_at": "2026-10-15T01:00:00+00:00"}),  # 缺必填
]


@pytest.mark.parametrize("schema_name,doc", POSITIVE_DOCS)
def test_schema_accepts_positive_docs(schema_name, doc):
    assert schema_validate(doc, _schema(schema_name)) == []


@pytest.mark.parametrize("schema_name,doc", NEGATIVE_DOCS)
def test_schema_rejects_negative_docs(schema_name, doc):
    assert schema_validate(doc, _schema(schema_name)) != []


def test_schema_and_python_agree_on_manifest(tmp_path):
    """同一文档：Python 校验通过 ⇔ Schema 校验通过（正例 + 负例对齐抽查）。"""
    schema = _schema("trace.manifest.schema.json")
    ok_yaml = yaml.safe_load(VALID_MANIFEST_YAML)
    assert schema_validate(ok_yaml, schema) == []
    assert load_manifest(VALID_MANIFEST_YAML) is not None
    bad = _manifest_doc(format_version="v1")
    assert schema_validate(bad, schema) != []
    with pytest.raises(FormatError):
        load_manifest(yaml.dump(bad))


# ---------- 语料即验收：corpus 目录本身必须被校验器承认/拒绝（终审 Important-4） ----------

def test_corpus_valid_trace_dir():
    errors = validate_trace_dir(CORPUS / "valid" / "trace")
    assert errors == []
    steps = load_steps(CORPUS / "valid" / "trace" / "steps.ndjson")
    assert [s.seq for s in steps] == [1, 2, 3]


def test_corpus_valid_golden_dir():
    assert validate_golden_dir(CORPUS / "valid" / "golden") == []


def test_corpus_invalid_fragments_rejected():
    inv = CORPUS / "invalid"
    with pytest.raises(FormatError):
        load_steps(inv / "steps_bad_action.ndjson")
    with pytest.raises(FormatError):
        load_manifest(inv / "manifest_bad_version.yaml")
    with pytest.raises(FormatError):
        load_network(inv / "network_bad_status.json")
    with pytest.raises(FormatError):
        load_run_meta(inv / "golden_bad_meta.json")


def test_corrupt_files_surface_as_errors_not_exceptions(tmp_path):
    """终审 Important-1：目录校验中损坏文件必须进错误列表，不得抛裸异常。"""
    t = _build_trace_dir(tmp_path)
    (t / "network.json").write_text("{broken", encoding="utf-8")
    (t / "manifest.yaml").write_text("::: not yaml [", encoding="utf-8")
    errors = validate_trace_dir(t)
    assert any("network.json" in e for e in errors)
    assert any("manifest.yaml" in e for e in errors)
    g = tmp_path / "golden"
    g.mkdir()
    (g / "run_meta.json").write_text("{oops", encoding="utf-8")
    gerrors = validate_golden_dir(g)
    assert any("run_meta.json" in e for e in gerrors)


def test_schema_and_python_agree_on_corpus():
    """正例语料双向通过：manifest 文档同时满足 Schema 与 Python 加载。"""
    schema = _schema("trace.manifest.schema.json")
    doc = yaml.safe_load((CORPUS / "valid" / "trace" / "manifest.yaml").read_text(encoding="utf-8"))
    assert schema_validate(doc, schema) == []
    load_manifest(CORPUS / "valid" / "trace" / "manifest.yaml")


def test_manifest_login_steps_minimum_one():
    # 直接以最小 manifest 文本构造：login_steps 含 0 必须拒绝（Schema minimum 1）
    from forge_proto.trace import load_manifest
    import pytest
    with pytest.raises(Exception) as ei:
        load_manifest("format_version: \"1.0\"\nsite: x.com\nlogin_steps: [0, 2]\n")
    assert "≥1" in str(ei.value)

"""forge_proto：Forge 接口冻结清单的类型化定义（MS-1B：轨迹格式 v1）。

冻结基线：M07 §4（D-2，docs/05-开发计划.md 附录 A.2）。
表达细节裁定与版本纪律：docs/09-MS1B执行计划.md §3 与 packages/proto/README.md。
变更纪律：格式变更一律走 minor 并触发四方（M02/M06/M08/M09）适配评审。
"""
from .format import FormatError
from .golden import RunMeta, load_run_meta, validate_golden_dir
from .trace import (
    ACTIONS,
    CURRENT_MAJOR,
    Manifest,
    NetworkEntry,
    NetworkLog,
    Step,
    TimeSensitiveStep,
    is_compatible,
    load_manifest,
    load_network,
    load_steps,
    validate_trace_dir,
)

__all__ = [
    "ACTIONS",
    "CURRENT_MAJOR",
    "FormatError",
    "Manifest",
    "NetworkEntry",
    "NetworkLog",
    "RunMeta",
    "Step",
    "TimeSensitiveStep",
    "is_compatible",
    "load_manifest",
    "load_network",
    "load_steps",
    "load_run_meta",
    "validate_golden_dir",
    "validate_trace_dir",
]

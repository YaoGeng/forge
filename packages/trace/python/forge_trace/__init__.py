"""forge_trace：录制回放（MS-1D）。

冻结基线：M07 §4/§5（docs/03-模块设计/M07-BlockSDK与测试框架.md）；
表达细节裁定：docs/11-MS1D执行计划.md §3（C1-C11）。
回放唯一入口 replay.run（M07 §5）；Recorder 产物必须过 proto 校验零错误。
"""
from .events import INPUT_FLUSH_MS, IDLE_WAIT_MS, SCROLL_FLUSH_MS, BrowserEvent, aggregate
from .selectors import ElementFp, forge_selector
from .store import Annotation, RecordingsStore, Recording

__all__ = [
    "INPUT_FLUSH_MS",
    "IDLE_WAIT_MS",
    "SCROLL_FLUSH_MS",
    "Annotation",
    "BrowserEvent",
    "ElementFp",
    "RecordingsStore",
    "Recording",
    "aggregate",
    "forge_selector",
]

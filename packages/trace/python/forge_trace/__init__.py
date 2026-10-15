"""forge_trace：录制回放（MS-1D）。

冻结基线：M07 §4/§5（docs/03-模块设计/M07-BlockSDK与测试框架.md）；
表达细节裁定：docs/11-MS1D执行计划.md §3（C1-C11）。
回放唯一入口 replay.run（M07 §5）；Recorder 产物必须过 proto 校验零错误。
"""
from .events import INPUT_FLUSH_MS, IDLE_WAIT_MS, SCROLL_FLUSH_MS, BrowserEvent, aggregate
from .port import BrowserPort
from .recorder import RecordingSession, Recorder
from .replayer import ConsistencyReport, ReplayResult, StepResult, assert_consistent, replay
from .selectors import ElementFp, forge_selector
from .store import Annotation, RecordingsStore, Recording
from .similarity import SIMILARITY_THRESHOLD, cosine, embed, structural_similarity

__all__ = [
    "INPUT_FLUSH_MS",
    "IDLE_WAIT_MS",
    "SCROLL_FLUSH_MS",
    "SIMILARITY_THRESHOLD",
    "Annotation",
    "BrowserEvent",
    "BrowserPort",
    "ConsistencyReport",
    "ElementFp",
    "RecordingsStore",
    "Recording",
    "RecordingSession",
    "ReplayResult",
    "Recorder",
    "StepResult",
    "aggregate",
    "assert_consistent",
    "cosine",
    "embed",
    "forge_selector",
    "replay",
    "structural_similarity",
]

"""走神/专注融合层。

对外只暴露四个名字：引擎、配置、状态枚举、判决对象。上层（``monitoring``
服务）不需要知道窗口、规则、校准的内部结构。

用法::

    engine = AttentionEngine()
    verdict = engine.feed(FrameSample(t=..., face=..., ...))
    current = verdict or engine.latest      # 每帧都要有值
"""

from backend.src.mind_wandering.fusion.config import (
    DEFAULT_ATTENTION_CONFIG,
    AttentionConfig,
)
from backend.src.mind_wandering.fusion.engine import AttentionEngine
from backend.src.mind_wandering.fusion.fusion_types import (
    AttentionState,
    AttentionVerdict,
    FrameSample,
    WindowFeatures,
)

__all__ = [
    "AttentionConfig",
    "DEFAULT_ATTENTION_CONFIG",
    "AttentionEngine",
    "AttentionState",
    "AttentionVerdict",
    "FrameSample",
    "WindowFeatures",
]

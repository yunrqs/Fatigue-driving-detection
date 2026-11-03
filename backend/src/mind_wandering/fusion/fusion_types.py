"""融合层的数据契约。

三路信号的采样方式不同，必须先统一到同一时间轴再谈融合：

==================  ==============  ==================  ==========================
信号                频率            类型                来源
==================  ==============  ==================  ==========================
EAR / 眨眼          每帧(约 15-30)  连续值 + 稀疏事件   ``BlinkDetector.process_frame``
情绪概率            每帧(检出人脸)  7 维单纯形          ``EmotionRecognizer.predict``
人脸与姿态          每帧            布尔 + 角度         ``FatigueDetector.process_frame``
==================  ==============  ==================  ==========================

因此 ``FrameSample`` 以 **单调时间戳** 为主键，而不是帧序号：前端按固定间隔
上传帧，实际帧率会随网络与解码抖动，按帧计数会让 5 秒窗口漂移。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AttentionState(str, Enum):
    """注意力状态。取值与 ``mind_wandering/config.py`` 的标签名保持一致。"""

    UNKNOWN = "unknown"
    CONCENTRATION = "focused"
    DELIBERATE_MW = "deliberate_mw"
    SPONTANEOUS_MW = "spontaneous_mw"


@dataclass
class FrameSample:
    """单帧对齐后的输入。所有字段都必须来自同一帧、同一时刻。"""

    t: float                      # time.monotonic()，秒
    face: bool                    # 该帧是否检出人脸
    ear: float | None = None      # 眼宽高比（平滑后）
    threshold: float | None = None
    eye_closed: bool = False      # 状态机是否处于 CLOSED
    blink: bool = False           # 该帧是否为一次眨眼的触发帧（上升沿事件）
    emotion: str | None = None    # 平滑后的情绪标签
    confidence: float | None = None
    probs: dict[str, float] = field(default_factory=dict)  # 当前帧 7 类概率


@dataclass
class WindowFeatures:
    """一个分析窗口内的聚合特征。字段命名与论文 3.4 节的特征表对齐。"""

    start: float
    end: float
    duration: float
    frames: int
    face_frames: int
    face_ratio: float            # 有效人脸帧 / 总帧数
    blink_count: int
    blink_rate_per_min: float    # 窗口内眨眼次数折算每分钟
    eye_closed_ratio: float      # 处于 CLOSED 的帧占比
    ear_mean: float | None
    ear_std: float | None
    emotion_counts: dict[str, int]     # 平滑标签计数
    emotion_probs_mean: dict[str, float]  # 逐类概率均值
    positive_valence: float
    negative_valence: float
    neutral_valence: float
    emotion_entropy: float       # 归一化熵，衡量情绪离散程度（0-1）
    emotion_switch_rate: float   # 相邻有效帧标签切换比例
    dominant_emotion: str | None

    def as_dict(self) -> dict:
        return {
            "window_start": self.start,
            "window_end": self.end,
            "window_duration": self.duration,
            "frame_count": self.frames,
            "face_ratio": self.face_ratio,
            "blink_count": self.blink_count,
            "blink_rate_per_min": self.blink_rate_per_min,
            "eye_closed_ratio": self.eye_closed_ratio,
            "ear_mean": self.ear_mean,
            "ear_std": self.ear_std,
            "positive_valence": self.positive_valence,
            "negative_valence": self.negative_valence,
            "neutral_valence": self.neutral_valence,
            "emotion_entropy": self.emotion_entropy,
            "emotion_switch_rate": self.emotion_switch_rate,
            "dominant_emotion": self.dominant_emotion,
        }


@dataclass
class AttentionVerdict:
    """融合判决。``signals`` 保留每个分量，便于日志与答辩解释。"""

    state: AttentionState
    raw_state: AttentionState        # 持续性约束生效前的瞬时判定
    confidence: float
    scores: dict[str, float]
    signals: dict[str, float]
    reason: str
    window: WindowFeatures | None = None
    calibrated: bool = False

    def as_dict(self, include_window: bool = False) -> dict:
        """序列化。默认不含窗口明细：``analyze`` 每帧都要回传，载荷需可控。"""
        payload = {
            "state": self.state.value,
            "raw_state": self.raw_state.value,
            "confidence": round(self.confidence, 4),
            "scores": {k: round(v, 4) for k, v in self.scores.items()},
            "signals": {k: (round(v, 4) if isinstance(v, float) else v)
                        for k, v in self.signals.items()},
            "reason": self.reason,
            "calibrated": self.calibrated,
        }
        if include_window and self.window is not None:
            payload["window"] = self.window.as_dict()
        return payload

"""时序对齐：把异步的三路帧级信号归并成定长分析窗口。

设计要点（每条都对应一个实际会踩的坑）：

1. **以时间戳为主键，不以帧序号。** 前端按固定间隔上传帧，实际帧率随网络与
   解码抖动；按帧数切窗会让 5 秒窗口在低帧率下变成 10 秒以上。
2. **眨眼按事件计数，不按帧比例折算。** ``blink_detected`` 只在一次眨眼的
   触发帧为 True（状态机上升沿），若用 ``mean(blink)`` 会得到近似 0 的无意义值。
3. **断流即重建窗口。** 摄像头暂停、页面切后台都会造成长时间空档；跨空档
   求均值等于把两段无关行为混为一谈。
4. **情绪只统计有人脸的帧。** 人脸丢失时 ``predict`` 不会被调用，若把空值
   当作 neutral=1 会系统性压低负性情绪占比。
"""

from __future__ import annotations

import math
from collections import deque

from backend.src.mind_wandering.fusion.config import AttentionConfig
from backend.src.mind_wandering.fusion.fusion_types import FrameSample, WindowFeatures

_EMOTION_CLASSES = ("angry", "disgust", "fear", "happy", "sad", "surprise", "neutral")


def _normalized_entropy(counts: dict[str, float]) -> float:
    """7 类分布的归一化熵，落在 0-1。分布越分散（表情越不稳定）值越大。"""
    total = sum(v for v in counts.values() if v > 0)
    if total <= 0:
        return 0.0
    entropy = 0.0
    for value in counts.values():
        if value > 0:
            p = value / total
            entropy -= p * math.log(p)
    return entropy / math.log(len(_EMOTION_CLASSES))


def build_window(samples: list[FrameSample], cfg: AttentionConfig) -> WindowFeatures | None:
    """把一组帧样本聚合成一个窗口特征。样本不足或全部无脸时返回 None。"""
    if len(samples) < 3:
        return None
    start, end = samples[0].t, samples[-1].t
    duration = end - start
    if duration <= 0:
        return None

    face_samples = [s for s in samples if s.face]
    face_ratio = len(face_samples) / len(samples)
    if not face_samples:
        return None

    blink_count = sum(1 for s in samples if s.blink)
    # 折算每分钟需要真实时间跨度；不足 1 秒的窗口折算会放大到失真，此处保底。
    span_min = max(duration, 1.0) / 60.0
    closed = sum(1 for s in face_samples if s.eye_closed)

    ears = [s.ear for s in face_samples if s.ear is not None]
    ear_mean = sum(ears) / len(ears) if ears else None
    ear_std = None
    if len(ears) > 1 and ear_mean is not None:
        ear_std = math.sqrt(sum((e - ear_mean) ** 2 for e in ears) / len(ears))

    # 情绪：逐类概率均值只取有概率的帧。
    with_probs = [s for s in face_samples if s.probs]
    probs_mean: dict[str, float] = {}
    for name in _EMOTION_CLASSES:
        values = [float(s.probs[name]) for s in with_probs if name in s.probs]
        probs_mean[name] = sum(values) / len(values) if values else 0.0

    counts: dict[str, int] = {}
    for s in face_samples:
        if s.emotion:
            counts[s.emotion] = counts.get(s.emotion, 0) + 1

    # 标签切换率：相邻有效标签不同的比例，衡量表情波动。
    labels = [s.emotion for s in face_samples if s.emotion]
    switches = sum(1 for a, b in zip(labels, labels[1:]) if a != b)
    switch_rate = switches / (len(labels) - 1) if len(labels) > 1 else 0.0

    positive = sum(probs_mean.get(e, 0.0) for e in cfg.positive_emotions)
    negative = sum(probs_mean.get(e, 0.0) for e in cfg.negative_emotions)
    neutral = probs_mean.get("neutral", 0.0)

    return WindowFeatures(
        start=start,
        end=end,
        duration=duration,
        frames=len(samples),
        face_frames=len(face_samples),
        face_ratio=face_ratio,
        blink_count=blink_count,
        blink_rate_per_min=blink_count / span_min,
        eye_closed_ratio=closed / len(face_samples),
        ear_mean=ear_mean,
        ear_std=ear_std,
        emotion_counts=counts,
        emotion_probs_mean=probs_mean,
        positive_valence=positive,
        negative_valence=negative,
        neutral_valence=neutral,
        emotion_entropy=_normalized_entropy(probs_mean),
        emotion_switch_rate=switch_rate,
        dominant_emotion=max(counts, key=counts.get) if counts else None,
    )


class BlinkRateEstimator:
    """长窗眨眼率估计。

    5 秒窗口内眨眼通常只有 1-2 次，直接折算成次/分会成倍跳变（1 次=12 次/分，
    2 次=24 次/分），判决会在两种状态间持续抖动。这里改用事件间隔法：在
    ``blink_rate_window_sec`` 的滑动窗内取 ``(n-1) / 时间跨度``，对单次事件的
    量化误差不敏感。

    代价是滞后：状态变化后约需半个窗口才反映到估计值上。认知状态本身是分钟级
    构念，这个滞后可以接受。
    """

    def __init__(self, cfg: AttentionConfig) -> None:
        self.cfg = cfg
        self._times: deque[float] = deque()

    def add(self, t: float) -> None:
        self._times.append(t)
        cutoff = t - self.cfg.blink_rate_window_sec
        while self._times and self._times[0] < cutoff:
            self._times.popleft()

    def rate(self) -> float | None:
        """返回次/分；事件不足或跨度过短时返回 None（此时应降级而非猜测）。"""
        if len(self._times) < 2:
            return None
        span = self._times[-1] - self._times[0]
        if span < self.cfg.blink_rate_min_span_sec:
            return None
        return (len(self._times) - 1) / (span / 60.0)

    def clear(self) -> None:
        self._times.clear()


class WindowBuffer:
    """按时间维护滑动缓冲区，并按 hop 步长产出分析窗口。"""

    def __init__(self, cfg: AttentionConfig) -> None:
        self.cfg = cfg
        self._samples: deque[FrameSample] = deque()
        self._last_emit: float | None = None
        self._last_t: float | None = None
        self.reset_count = 0

    def clear(self) -> None:
        self._samples.clear()
        self._last_emit = None
        self._last_t = None

    def push(self, sample: FrameSample) -> WindowFeatures | None:
        """写入一帧；到达 hop 间隔且有足够数据时返回窗口特征，否则返回 None。"""
        # 断流检测：跨空档时丢弃旧窗口，避免把两段行为混合。
        if self._last_t is not None and sample.t - self._last_t > self.cfg.max_frame_gap_sec:
            self._samples.clear()
            self._last_emit = None
            self.reset_count += 1
        self._last_t = sample.t
        self._samples.append(sample)

        # 淘汰过期样本。
        cutoff = sample.t - self.cfg.buffer_sec
        while self._samples and self._samples[0].t < cutoff:
            self._samples.popleft()

        if self._last_emit is None:
            self._last_emit = sample.t
            return None
        if sample.t - self._last_emit < self.cfg.hop_sec:
            return None
        self._last_emit = sample.t
        return self.snapshot()

    def snapshot(self) -> WindowFeatures | None:
        """取最近 ``window_sec`` 内的样本聚合成窗口特征。"""
        if not self._samples:
            return None
        now = self._samples[-1].t
        start = now - self.cfg.window_sec
        window = [s for s in self._samples if s.t >= start]
        if len(window) < 3:
            return None
        # 窗口必须覆盖足够时长，否则只是启动初期的半窗。
        if window[-1].t - window[0].t < self.cfg.window_sec * self.cfg.min_window_fill:
            return None
        return build_window(window, self.cfg)

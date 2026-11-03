"""融合引擎：帧进 → 状态出。

承担三件不属于单帧逻辑的事：

1. **个体基线校准**。论文 3.6 节 Fig.7 说明被试间差异显著，固定阈值必然失效。
   引擎在会话开头采集 ``baseline_sec`` 秒，用实测眨眼率替代经验值。
2. **持续性约束**。单窗口判决会抖，连续 ``persistence_windows`` 个窗口同向
   才切换状态（对应论文 2.6 节的 5-s state-persistence）。
3. **降级**。未校准、人脸缺失、窗口不足时明确返回降级状态，而不是硬给一个
   看起来正常的标签。
"""

from __future__ import annotations

from collections import deque

from backend.src.mind_wandering.fusion.config import (
    DEFAULT_ATTENTION_CONFIG,
    AttentionConfig,
)
from backend.src.mind_wandering.fusion.fusion_types import (
    AttentionState,
    AttentionVerdict,
    FrameSample,
)
from backend.src.mind_wandering.fusion.rules import decide
from backend.src.mind_wandering.fusion.window import BlinkRateEstimator, WindowBuffer


class AttentionEngine:
    """有状态的融合引擎。一个会话一个实例，由 ``AnalysisSession`` 持有。"""

    def __init__(self, cfg: AttentionConfig | None = None) -> None:
        self.cfg = cfg or DEFAULT_ATTENTION_CONFIG
        self._buffer = WindowBuffer(self.cfg)
        self._blink_rate = BlinkRateEstimator(self.cfg)
        self._calib_start: float | None = None
        self._calib_blinks = 0
        self._baseline_rate: float | None = None
        self._recent: deque[AttentionState] = deque(maxlen=max(1, self.cfg.persistence_windows))
        self._state: AttentionState = AttentionState.UNKNOWN
        self._latest: AttentionVerdict | None = None
        self._windows_emitted = 0

    # ---- 只读状态 ----

    @property
    def latest(self) -> AttentionVerdict | None:
        """最近一次判决；前端每帧都要有值，不能等下一个窗口。"""
        return self._latest

    @property
    def state(self) -> AttentionState:
        return self._state

    @property
    def baseline_rate(self) -> float | None:
        return self._baseline_rate

    @property
    def calibrated(self) -> bool:
        return self._baseline_rate is not None

    @property
    def windows_emitted(self) -> int:
        return self._windows_emitted

    def calibration_progress(self, now: float | None = None) -> dict:
        """校准进度，供界面显示"再坚持 x 秒"。"""
        if self._baseline_rate is not None:
            return {"calibrated": True, "progress": 1.0, "remaining_sec": 0.0}
        if self._calib_start is None or now is None:
            return {"calibrated": False, "progress": 0.0, "remaining_sec": self.cfg.baseline_sec}
        elapsed = max(0.0, now - self._calib_start)
        progress = min(1.0, elapsed / self.cfg.baseline_sec)
        return {
            "calibrated": False,
            "progress": round(progress, 3),
            "remaining_sec": round(max(0.0, self.cfg.baseline_sec - elapsed), 1),
            "blinks": self._calib_blinks,
        }

    def reset(self) -> None:
        self._buffer.clear()
        self._blink_rate.clear()
        self._calib_start = None
        self._calib_blinks = 0
        self._baseline_rate = None
        self._recent.clear()
        self._state = AttentionState.UNKNOWN
        self._latest = None
        self._windows_emitted = 0

    # ---- 主入口 ----

    def feed(self, sample: FrameSample) -> AttentionVerdict | None:
        """写入一帧。到达分析窗口时返回新判决，否则返回 None。"""
        if sample.blink:
            self._blink_rate.add(sample.t)
        self._update_calibration(sample)
        window = self._buffer.push(sample)
        if window is None:
            return None

        # 眨眼率用长窗稳定估计，情绪特征用 5 秒窗口：两者时间常数不同。
        verdict = decide(
            window, self.cfg, self._baseline_rate,
            blink_rate_per_min=self._blink_rate.rate(),
        )
        verdict = self._apply_persistence(verdict)
        self._windows_emitted += 1
        self._latest = verdict
        return verdict

    # ---- 内部 ----

    def _update_calibration(self, sample: FrameSample) -> None:
        if self._baseline_rate is not None:
            return
        if self._calib_start is None:
            self._calib_start = sample.t
        if sample.blink:
            self._calib_blinks += 1
        elapsed = sample.t - self._calib_start
        if elapsed < self.cfg.baseline_sec:
            return
        rate = self._blink_rate.rate()
        if rate is not None and self._calib_blinks >= self.cfg.baseline_min_blinks:
            self._baseline_rate = rate

    def _apply_persistence(self, verdict: AttentionVerdict) -> AttentionVerdict:
        """连续同向才切换，抑制单窗口抖动。"""
        if verdict.raw_state is AttentionState.UNKNOWN:
            self._recent.clear()
            self._state = AttentionState.UNKNOWN
            return verdict

        self._recent.append(verdict.raw_state)
        if (
            len(self._recent) == self._recent.maxlen
            and len(set(self._recent)) == 1
        ):
            self._state = self._recent[0]

        if self._state is not verdict.raw_state:
            verdict.state = self._state
            if self._state is not AttentionState.UNKNOWN:
                verdict.reason = f"{verdict.reason}（持续性约束中，暂维持 {self._state.value}）"
        return verdict

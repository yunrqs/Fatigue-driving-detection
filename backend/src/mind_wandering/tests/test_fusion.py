"""融合层测试：窗口聚合、规则判决、引擎编排。

采用合成数据，每条用例只变动一个信号，便于定位失败原因。
"""

import unittest

from backend.src.mind_wandering.fusion.config import AttentionConfig
from backend.src.mind_wandering.fusion.engine import AttentionEngine
from backend.src.mind_wandering.fusion.fusion_types import (
    AttentionState,
    FrameSample,
    WindowFeatures,
)
from backend.src.mind_wandering.fusion.rules import decide
from backend.src.mind_wandering.fusion.window import WindowBuffer, build_window

_RESTING_PROBS = {"neutral": 0.8, "happy": 0.05, "surprise": 0.05,
                  "angry": 0.02, "disgust": 0.02, "fear": 0.03, "sad": 0.03}
_NEGATIVE_PROBS = {"neutral": 0.15, "happy": 0.02, "surprise": 0.03,
                   "angry": 0.3, "disgust": 0.2, "fear": 0.15, "sad": 0.15}


def _samples(count: int, dt: float = 0.1, start: float = 0.0,
             blink_every: int = 0, probs=None, face: bool = True,
             emotion: str = "neutral") -> list[FrameSample]:
    out = []
    for i in range(count):
        is_blink = blink_every > 0 and i % blink_every == 0 and i > 0
        out.append(FrameSample(
            t=start + i * dt,
            face=face,
            ear=0.28,
            eye_closed=False,
            blink=is_blink,
            emotion=emotion if face else None,
            confidence=0.9,
            probs=dict(probs) if (probs and face) else {},
        ))
    return out


def _window(**overrides) -> WindowFeatures:
    base = dict(
        start=0.0, end=5.0, duration=5.0, frames=50, face_frames=50, face_ratio=1.0,
        blink_count=1, blink_rate_per_min=12.0, eye_closed_ratio=0.02,
        ear_mean=0.28, ear_std=0.01, emotion_counts={"neutral": 50},
        emotion_probs_mean=_RESTING_PROBS, positive_valence=0.10,
        negative_valence=0.10, neutral_valence=0.80, emotion_entropy=0.25,
        emotion_switch_rate=0.05, dominant_emotion="neutral",
    )
    base.update(overrides)
    return WindowFeatures(**base)


class WindowTests(unittest.TestCase):
    def test_blink_counted_by_event_not_by_frame_ratio(self):
        # 10 秒 100 帧，每 20 帧一次眨眼 => 4 次事件。
        window = build_window(_samples(100, dt=0.1, blink_every=20), AttentionConfig())
        self.assertIsNotNone(window)
        self.assertEqual(window.blink_count, 4)
        # 4 次 / (9.9s/60) ≈ 24.2 次/分
        self.assertAlmostEqual(window.blink_rate_per_min, 4 / (9.9 / 60.0), places=1)

    def test_valence_sums_from_mean_probabilities(self):
        window = build_window(_samples(30, probs=_RESTING_PROBS), AttentionConfig())
        self.assertAlmostEqual(window.neutral_valence, 0.8, places=3)
        self.assertAlmostEqual(window.positive_valence, 0.10, places=3)

    def test_no_face_yields_no_window(self):
        self.assertIsNone(build_window(_samples(30, face=False), AttentionConfig()))

    def test_too_few_samples_rejected(self):
        self.assertIsNone(build_window(_samples(2), AttentionConfig()))


class WindowBufferTests(unittest.TestCase):
    def setUp(self):
        self.cfg = AttentionConfig(window_sec=5.0, hop_sec=1.0, min_window_fill=0.5)

    def test_gap_discards_buffer(self):
        buffer = WindowBuffer(self.cfg)
        for sample in _samples(30, dt=0.1, start=0.0):
            buffer.push(sample)
        # 断流 10 秒后继续，旧样本必须被丢弃。
        for sample in _samples(5, dt=0.1, start=10.0):
            buffer.push(sample)
        self.assertEqual(buffer.reset_count, 1)
        window = buffer.snapshot()
        # 重建后窗口只含新样本，跨度不足 5 秒 => 拒绝出窗。
        self.assertIsNone(window)

    def test_emits_only_after_hop(self):
        buffer = WindowBuffer(self.cfg)
        emitted = 0
        for sample in _samples(80, dt=0.1):
            if buffer.push(sample) is not None:
                emitted += 1
        # 8 秒数据、1 秒步长，首个 hop 在 t=1.0 仅记录不产出，之后约 7 次。
        self.assertGreaterEqual(emitted, 5)


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.cfg = AttentionConfig()

    def test_low_blink_and_stable_face_is_deliberate(self):
        window = _window(blink_rate_per_min=6.0, emotion_entropy=0.15,
                         neutral_valence=0.7, positive_valence=0.2)
        verdict = decide(window, self.cfg, baseline_blink_rate=15.0)
        self.assertEqual(verdict.state, AttentionState.DELIBERATE_MW)

    def test_high_negative_and_scattered_face_is_spontaneous(self):
        window = _window(blink_rate_per_min=26.0, emotion_entropy=0.85,
                         negative_valence=0.65, neutral_valence=0.15,
                         positive_valence=0.05, emotion_probs_mean=_NEGATIVE_PROBS,
                         dominant_emotion="angry",
                         emotion_counts={"angry": 30, "sad": 20})
        verdict = decide(window, self.cfg, baseline_blink_rate=15.0)
        self.assertEqual(verdict.state, AttentionState.SPONTANEOUS_MW)

    def test_baseline_blink_is_concentration(self):
        window = _window(blink_rate_per_min=15.2, emotion_entropy=0.2,
                         neutral_valence=0.8)
        verdict = decide(window, self.cfg, baseline_blink_rate=15.0)
        self.assertEqual(verdict.state, AttentionState.CONCENTRATION)

    def test_low_face_ratio_forces_unknown(self):
        window = _window(face_ratio=0.2)
        verdict = decide(window, self.cfg, baseline_blink_rate=15.0)
        self.assertEqual(verdict.state, AttentionState.UNKNOWN)
        self.assertEqual(verdict.confidence, 0.0)

    def test_uncalibrated_lowers_confidence(self):
        window = _window(blink_rate_per_min=15.0)
        calibrated = decide(window, self.cfg, baseline_blink_rate=15.0)
        pending = decide(window, self.cfg, baseline_blink_rate=None)
        self.assertFalse(pending.calibrated)
        self.assertLess(pending.confidence, calibrated.confidence)


class EngineTests(unittest.TestCase):
    def setUp(self):
        # 缩短窗口与校准期，保证测试在毫秒级完成。
        self.cfg = AttentionConfig(window_sec=2.0, hop_sec=0.5, buffer_sec=4.0,
                                   baseline_sec=2.0, baseline_min_blinks=2,
                                   persistence_windows=2,
                                   blink_rate_window_sec=10.0,
                                   blink_rate_min_span_sec=1.0)

    def test_calibration_completes_and_sets_baseline(self):
        engine = AttentionEngine(self.cfg)
        samples = _samples(60, dt=0.1, blink_every=10, probs=_RESTING_PROBS)
        for sample in samples:
            engine.feed(sample)
        self.assertTrue(engine.calibrated)
        self.assertIsNotNone(engine.baseline_rate)
        # 60 帧/6 秒，每 10 帧一次 => 6 次眨眼 => 约 60 次/分。
        self.assertAlmostEqual(engine.baseline_rate, 6 / (5.9 / 60.0), delta=6.0)

    def test_reset_clears_calibration(self):
        engine = AttentionEngine(self.cfg)
        for sample in _samples(40, dt=0.1, blink_every=10, probs=_RESTING_PROBS):
            engine.feed(sample)
        engine.reset()
        self.assertFalse(engine.calibrated)
        self.assertEqual(engine.state, AttentionState.UNKNOWN)
        self.assertIsNone(engine.latest)

    def test_state_requires_consecutive_windows(self):
        engine = AttentionEngine(self.cfg)
        seen = []
        for sample in _samples(120, dt=0.1, blink_every=15, probs=_RESTING_PROBS):
            verdict = engine.feed(sample)
            if verdict is not None:
                seen.append(verdict)
        # 持续性约束下，首次切换必须发生在第二个窗口之后。
        self.assertGreater(len(seen), 2)
        self.assertEqual(seen[0].state, AttentionState.UNKNOWN)

    def test_latest_survives_between_windows(self):
        engine = AttentionEngine(self.cfg)
        for sample in _samples(60, dt=0.1, blink_every=15, probs=_RESTING_PROBS):
            engine.feed(sample)
        self.assertIsNotNone(engine.latest)
        self.assertGreaterEqual(engine.windows_emitted, 1)


if __name__ == "__main__":
    unittest.main()

"""融合层仿真：不接摄像头也能复现状态迁移。

用途有两个：
1. 回归——改权重或阈值后，确认三态仍能按预期分离；
2. 汇报——生成状态迁移序列，直接作为效果佐证。

跑法（在项目根目录）::

    backend/.venv/Scripts/python.exe -m backend.src.mind_wandering.fusion.demo_simulate
"""

from __future__ import annotations

import argparse

from backend.src.mind_wandering.fusion.config import AttentionConfig
from backend.src.mind_wandering.fusion.engine import AttentionEngine
from backend.src.mind_wandering.fusion.fusion_types import AttentionState, FrameSample

# 三档合成信号：(眨眼率基线倍数, 情绪概率分布)
_SCENARIOS = {
    "focused": (1.00, {"neutral": 0.80, "happy": 0.06, "surprise": 0.04,
                       "angry": 0.02, "disgust": 0.02, "fear": 0.03, "sad": 0.03}),
    "deliberate_mw": (0.55, {"neutral": 0.55, "happy": 0.18, "surprise": 0.12,
                             "angry": 0.03, "disgust": 0.03, "fear": 0.04, "sad": 0.05}),
    "spontaneous_mw": (1.75, {"neutral": 0.16, "happy": 0.03, "surprise": 0.05,
                              "angry": 0.28, "disgust": 0.16, "fear": 0.17, "sad": 0.15}),
}


def _emit_segment(engine: AttentionEngine, start: float, seconds: float,
                  rate_multiplier: float, probs: dict, fps: float = 10.0,
                  base_rate: float = 15.0, log: list | None = None) -> float:
    """按给定信号模型喂入一段数据，返回结束时刻。"""
    dt = 1.0 / fps
    # 由目标眨眼率反推触发间隔：base_rate * multiplier 次/分 → 每次间隔的帧数。
    rate_per_min = max(base_rate * rate_multiplier, 1.0)
    interval_frames = max(1, round(fps * 60.0 / rate_per_min))
    total = int(seconds * fps) + 1  # +1 帧确保覆盖满 seconds，避免校准差半个步长
    for i in range(total):
        sample = FrameSample(
            t=start + i * dt,
            face=True,
            ear=0.28,
            eye_closed=False,
            blink=(i > 0 and i % interval_frames == 0),
            emotion=max(probs, key=probs.get),
            confidence=0.9,
            probs=probs,
        )
        verdict = engine.feed(sample)
        if verdict is not None and log is not None:
            log.append((sample.t, verdict.state.value, round(verdict.confidence, 3),
                        verdict.reason))
    return start + total * dt


def run(calibration_sec: float = 30.0, segment_sec: float = 20.0) -> dict:
    cfg = AttentionConfig(baseline_sec=calibration_sec)
    engine = AttentionEngine(cfg)
    log: list[tuple] = []

    now = 0.0
    # 第 1 段：以专注状态完成个体基线校准。
    now = _emit_segment(engine, now, calibration_sec, 1.0, _SCENARIOS["focused"][1], log=log)
    baseline = engine.baseline_rate

    # 第 2~4 段：依次进入三种状态。
    for name in ("focused", "deliberate_mw", "spontaneous_mw"):
        multiplier, probs = _SCENARIOS[name]
        now = _emit_segment(engine, now, segment_sec, multiplier, probs, log=log)

    counts: dict[str, int] = {}
    for _, state, _, _ in log:
        counts[state] = counts.get(state, 0) + 1

    return {"baseline_rate": baseline, "windows": len(log), "counts": counts, "log": log}


def main() -> None:
    parser = argparse.ArgumentParser(description="融合层合成信号仿真")
    parser.add_argument("--calibration-sec", type=float, default=30.0)
    parser.add_argument("--segment-sec", type=float, default=30.0)
    parser.add_argument("--verbose", action="store_true", help="逐窗口打印")
    args = parser.parse_args()

    result = run(args.calibration_sec, args.segment_sec)
    print(f"个体基线眨眼率: {result['baseline_rate']:.1f} 次/分")
    print(f"判决窗口数: {result['windows']}")
    print(f"状态分布: {result['counts']}")
    if args.verbose:
        print()
        print(f"{'t(s)':>8}  {'state':<16}{'conf':>6}  reason")
        for t, state, conf, reason in result["log"]:
            print(f"{t:>8.1f}  {state:<16}{conf:>6.3f}  {reason[:46]}")


if __name__ == "__main__":
    main()

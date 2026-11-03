"""决策层规则融合：眨眼、情绪、人脸可用度 → 三态注意力判定。

为什么做**决策层**融合而不是特征层拼接：
现有数据里没有"带探针标签的视频"，特征层融合需要训练标签；决策层规则可以
零训练直接上线，并且天然产出带时间戳的伪标签，反过来为后续有监督训练积累
样本。这是当前约束下的唯一可行序，不是退而求其次。

**对称性约束**（本文件的核心设计约束）：
三态各自独立打分后取最高者，因此任何只出现在部分状态里的项都会造成结构性
偏置。原实现有三处这样的偏置，已修正：

1. 情绪项原用绝对占比（中性 vs 负性）。中性在真实 FER 输出里常占 0.50-0.95，
   负性常占 0.05-0.20，于是"专注"凭中性占比先天领先 0.35，超过眨眼项上限
   0.30，``spontaneous_mw`` 分支事实上不可达（眨眼率飙到基线 2 倍仍判专注）。
   现改为一律取对数几率 ``log(A/B)``：``log(中性/负性)`` 与 ``log(负性/中性)``
   互为相反数，经 tanh 压到 0-1 后两项之和恒为 1，偏置被消除。
2. 熵项同理，改为镜像对 ``_squash(mid - H)`` / ``_squash(H - mid)``。
3. 人脸覆盖率是三项共模项，对 argmax 恒无贡献却占 0.15 权重。现移出打分，
   只用于置信度折扣。

判据的论文依据（IEICE E109-D No.7, 2026）：
- 3.6 节：眨眼频率与情绪**无显著相关** → 二者互补而非冗余，适合决策层组合。
- 4 节：``neutral``/``sad``/``surprised`` 是强指示；**负性情绪是区分有意/无意
  走神的关键**；无意走神情绪变异更大，有意走神表情更受控。
- 2.5 节：个体自适应基线优于固定阈值 → 眨眼率一律相对个体基线归一化。

重要限定：论文的 99% 是"探针标签训练的 RF 在随机划分下的准确率"，**规则法
本身在论文中从未被评估**。本文件的权重与阈值全部标 [先验]，不构成精度承诺。
"""

from __future__ import annotations

import math

from backend.src.mind_wandering.fusion.config import AttentionConfig
from backend.src.mind_wandering.fusion.fusion_types import (
    AttentionState,
    AttentionVerdict,
    WindowFeatures,
)

# 未完成个体校准时使用的兜底静息眨眼率（次/分），仅作降级，不作精度承诺。
_FALLBACK_BLINK_RATE = 15.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _log_odds(a: float, b: float, floor: float) -> float:
    """``log(a/b)``，加下界避免 ``log(0)``。交换参数取相反数，对称性由此而来。"""
    return math.log((a + floor) / (b + floor))


def _squash(x: float, scale: float) -> float:
    """把 ``(-inf, inf)`` 压到 ``(0, 1)``：``x=0`` 得 0.5，且 ``squash(-x)=1-squash(x)``。"""
    return 0.5 + 0.5 * math.tanh(x / max(scale, 1e-6))


def decide(
    window: WindowFeatures,
    cfg: AttentionConfig,
    baseline_blink_rate: float | None = None,
    blink_rate_per_min: float | None = None,
) -> AttentionVerdict:
    """对单个窗口给出瞬时判决（未加持续性约束）。

    ``blink_rate_per_min`` 应传入**长窗稳定估计**（见 ``BlinkRateEstimator``）。
    窗口自身的 ``blink_count / blink_rate_per_min`` 只作诊断：5 秒窗内眨眼
    仅 1-2 次，直接折算会产生成倍跳变，不足以支撑判决。
    """
    baseline = baseline_blink_rate if baseline_blink_rate else _FALLBACK_BLINK_RATE
    calibrated = baseline_blink_rate is not None
    tolerance = cfg.blink_ratio_tolerance

    # 眨眼率是否来自长窗估计。取不到时退回窗口值，但必须体现在置信度上，
    # 而不是静默用一个统计上不可靠的数字参与判决。
    rate_available = blink_rate_per_min is not None
    rate = blink_rate_per_min if rate_available else window.blink_rate_per_min
    blink_ratio = rate / max(baseline, cfg.baseline_rate_floor)
    deviation = abs(blink_ratio - 1.0)

    # 眨眼分量：接近基线 / 低于基线 / 偏离基线，三者互补。
    near_baseline = _clamp(1.0 - deviation / tolerance)
    below_baseline = _clamp((1.0 - blink_ratio) / tolerance)
    above_baseline = _clamp((blink_ratio - 1.0) / tolerance)

    positive = _clamp(window.positive_valence)
    negative = _clamp(window.negative_valence)
    neutral = _clamp(window.neutral_valence)
    entropy = _clamp(window.emotion_entropy)
    face = _clamp(window.face_ratio)

    # 情绪项：一律对数几率，专注与无意走神严格互补。
    emo_focus = _squash(_log_odds(neutral, negative, cfg.prob_floor), cfg.emotion_log_scale)
    emo_spontaneous = _squash(_log_odds(negative, neutral, cfg.prob_floor), cfg.emotion_log_scale)
    # 有意走神：表情受控（低负性），偏中性或微正性（4 节）。
    emo_deliberate = _squash(
        _log_odds(0.5 * (positive + neutral), negative, cfg.prob_floor),
        cfg.emotion_log_scale,
    )

    # 熵项：低熵支持"专注/受控"，高熵支持"无意走神"，同样互为镜像。
    stab_focus = _squash(cfg.entropy_mid - entropy, cfg.entropy_scale)
    stab_spontaneous = _squash(entropy - cfg.entropy_mid, cfg.entropy_scale)

    # 专注：眨眼率贴合基线 + 中性主导 + 表情稳定。
    focus = (
        cfg.w_blink * near_baseline
        + cfg.w_emotion * emo_focus
        + cfg.w_stability * stab_focus
    )
    # 有意走神：眨眼率低于基线（内部思考时眨眼受抑制）+ 表情受控。
    deliberate = (
        cfg.w_blink * below_baseline
        + cfg.w_emotion * emo_deliberate
        + cfg.w_stability * stab_focus
    )
    # 无意走神：眨眼率升高或剧烈偏离 + 负性情绪 + 情绪离散。
    spontaneous = (
        cfg.w_blink * above_baseline
        + cfg.w_emotion * emo_spontaneous
        + cfg.w_stability * stab_spontaneous
    )

    scores = {
        AttentionState.CONCENTRATION.value: focus,
        AttentionState.DELIBERATE_MW.value: deliberate,
        AttentionState.SPONTANEOUS_MW.value: spontaneous,
    }
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    winner_name, winner_score = ranked[0]
    runner_up_score = ranked[1][1]
    margin = winner_score - runner_up_score

    state = AttentionState(winner_name)

    # 置信度 = Hill 函数 margin/(margin+tau)：渐近趋 1、永不饱和，避免原实现
    # 「margin 常超 0.32 就顶到 1.0」的梯度丢失。再按三项可信度折损。
    confidence = margin / (margin + cfg.confidence_tau) if margin > 0 else 0.0
    confidence *= cfg.face_conf_floor + (1.0 - cfg.face_conf_floor) * face
    if not rate_available:
        confidence *= cfg.conf_no_blink_rate
    if not calibrated:
        confidence *= cfg.conf_uncalibrated

    # 三个走神分支共有多少阳性证据。全部接近 0 时，"专注"只是没有反证的
    # 默认假设，而非被证实的结论——此时必须封顶，否则会出现"信息越少越确信"。
    evidence = max(above_baseline, below_baseline, emo_spontaneous, stab_spontaneous)
    evidence_capped = False
    if state is AttentionState.CONCENTRATION and evidence < cfg.weak_evidence:
        if confidence > cfg.conf_ceiling_default_focus:
            confidence = cfg.conf_ceiling_default_focus
            evidence_capped = True

    signals = {
        # 眨眼
        "blink_ratio": blink_ratio,
        "blink_rate_per_min": rate,
        "window_blink_count": window.blink_count,
        "baseline_blink_rate": baseline,
        "near_baseline": near_baseline,
        "below_baseline": below_baseline,
        "above_baseline": above_baseline,
        "blink_rate_available": 1.0 if rate_available else 0.0,
        # 情绪（对数几率压缩后的分量）
        "positive_valence": positive,
        "negative_valence": negative,
        "neutral_valence": neutral,
        "emotion_entropy": entropy,
        "emo_focus": emo_focus,
        "emo_deliberate": emo_deliberate,
        "emo_spontaneous": emo_spontaneous,
        # 稳定度
        "stab_focus": stab_focus,
        "stab_spontaneous": stab_spontaneous,
        # 决策
        "score_margin": margin,
        "evidence": evidence,
        "evidence_capped": 1.0 if evidence_capped else 0.0,
        "face_ratio": face,
        "eye_closed_ratio": window.eye_closed_ratio,
    }

    reason = _explain(state, signals, calibrated, evidence_capped)

    if face < cfg.min_valid_face:
        return AttentionVerdict(
            state=AttentionState.UNKNOWN,
            raw_state=AttentionState.UNKNOWN,
            confidence=0.0,
            scores=scores,
            signals=signals,
            reason=f"人脸覆盖不足（{face:.2f} < {cfg.min_valid_face}），不予判定",
            window=window,
            calibrated=calibrated,
        )

    # 未完成个体校准时基线是经验值，三态判决不可信：只保留瞬时倾向（raw_state）
    # 供调试与界面提示，对外一律 UNKNOWN。
    if not calibrated:
        return AttentionVerdict(
            state=AttentionState.UNKNOWN,
            raw_state=state,
            confidence=confidence * 0.3,
            scores=scores,
            signals=signals,
            reason="个体基线尚未校准完成，暂不判定（保持自然状态约 30 秒即可完成）",
            window=window,
            calibrated=False,
        )

    # 三态分数过于接近时不判定。典型情形：眨眼率明显偏离基线、但表情完全
    # 中性——此时 focused 与 deliberate 的各项分量几乎相同，差异在浮点噪声
    # 量级，继续输出状态等于让随机数决定结论。
    if margin < cfg.min_decidable_margin:
        return AttentionVerdict(
            state=AttentionState.UNKNOWN,
            raw_state=state,
            confidence=confidence,
            scores=scores,
            signals=signals,
            reason=(
                f"三态分数过于接近（间隔 {margin:.3f} < {cfg.min_decidable_margin}），"
                "证据不足以区分，暂不判定"
            ),
            window=window,
            calibrated=calibrated,
        )

    return AttentionVerdict(
        state=state,
        raw_state=state,
        confidence=confidence,
        scores=scores,
        signals=signals,
        reason=reason,
        window=window,
        calibrated=calibrated,
    )


def _explain(
    state: AttentionState,
    signals: dict[str, float],
    calibrated: bool,
    evidence_capped: bool,
) -> str:
    """生成可读理由，供界面与日志直接展示。"""
    parts: list[str] = []
    if state is AttentionState.CONCENTRATION:
        parts.append("眨眼率贴合个体基线")
        if signals["neutral_valence"] >= 0.4:
            parts.append("中性表情主导")
        if evidence_capped:
            parts.append("但缺少走神阳性证据，置信度已封顶")
    elif state is AttentionState.DELIBERATE_MW:
        parts.append(f"眨眼率降至基线的 {signals['blink_ratio']:.0%}")
        parts.append("表情波动小")
    else:
        parts.append(f"眨眼率偏离基线至 {signals['blink_ratio']:.0%}")
        if signals["negative_valence"] > 0.25:
            parts.append(f"负性情绪占 {signals['negative_valence']:.0%}")
        if signals["emotion_entropy"] > 0.5:
            parts.append("情绪波动大")
    if signals["blink_rate_available"] < 0.5:
        parts.append("眨眼率采样不足，置信度已下调")
    if not calibrated:
        parts.append("个体基线未完成校准，结果仅供参考")
    return "；".join(parts)

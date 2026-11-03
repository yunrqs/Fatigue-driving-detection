"""走神/专注融合的集中配置。

遵循项目既有约定（见 ``blink_detection/config.py`` 的说明）：所有可调参数
集中在单一 dataclass，业务代码只读取 ``config.xxx``，不在函数内散落 magic
number。

权重与阈值的出处分两类，代码里逐项标注：
- **[论文]** IEICE Trans. Inf. & Syst. Vol.E109-D No.7 (2026) 的对应章节；
- **[先验]** 无数据可校准的工程取值，属于待验证假设，后续必须用实测数据替换。
"""

from dataclasses import dataclass, field


@dataclass
class AttentionConfig:
    # ---- 时序对齐 ----
    # [论文] 3.4 节：以 5 秒为固定分析窗口。
    window_sec: float = 5.0
    # [先验] 窗口步长 1 秒，形成重叠窗口以提升响应速度；论文未规定。
    hop_sec: float = 1.0
    # [先验] 窗口内累计帧数占比低于该值时不出结论，避免半窗误判。
    min_window_fill: float = 0.5
    # [先验] 窗口内检出人脸的比例下限；低于则判为 UNKNOWN。
    min_valid_face: float = 0.6
    # [先验] 相邻帧间隔超过该值视为采集断流，重建窗口。
    max_frame_gap_sec: float = 1.5
    # [先验] 缓冲区保留时间，需大于 window_sec。
    buffer_sec: float = 8.0

    # ---- 眨眼率估计（与情绪窗口解耦）----
    # [先验] 眨眼是 0.2-0.3 Hz 的低频事件：5 秒窗口内通常只有 1-2 次，折算成
    #        次/分会因单次事件在 12 与 24 之间跳变，统计上不可用。因此眨眼率
    #        单独用更长的滑动窗估计，情绪仍走 5 秒窗。
    #        代价是眨眼率变化有约半个窗口的滞后，对分钟级的认知状态可接受。
    blink_rate_window_sec: float = 30.0
    # [先验] 估计眨眼率所需的最短观测时长，短于此不给出率值。
    blink_rate_min_span_sec: float = 8.0

    # ---- 个体基线校准 ----
    # [论文] 3.6 节以 Fig.7 明确指出被试间差异，2.5 节用个体自适应基线
    #        替代固定阈值；此处对眨眼率做同样处理。
    baseline_sec: float = 30.0
    # [先验] 校准期内至少累计的眨眼次数，不足则不认为基线可用。
    baseline_min_blinks: int = 5
    # [先验] 基线眨眼率的保底值，防止校准期几乎不眨眼导致除零。
    baseline_rate_floor: float = 2.0

    # ---- 眨眼率归一化 ----
    # [先验] 眨眼率相对基线的容差；|ratio-1| 超过该值视为显著偏离。
    blink_ratio_tolerance: float = 0.35

    # ---- 情绪分组 ----
    # 与 mind_wandering/config.py 的 valence 定义保持一致。
    positive_emotions: tuple[str, ...] = ("happy", "surprise")
    negative_emotions: tuple[str, ...] = ("angry", "disgust", "fear", "sad")

    # ---- 打分权重（三态各自独立打分后取最高者）----
    # [先验] 三项权重之和为 1.0，仅表示相对重要性，不含精度承诺。
    # 人脸覆盖率**不参与打分**：它是三态共模项，对 argmax 恒无影响，只通过
    # 置信度折扣起作用（见 rules.py）。原来给它 0.15 权重是名义上的。
    # 眨眼与情绪等权：论文只说二者都是强指示，未给出相对重要性。
    w_blink: float = 0.40
    w_emotion: float = 0.40
    w_stability: float = 0.20

    # ---- 情绪项对称化 ----
    # [先验] 三态的情绪项统一取对数几率 log(A/B) 再经 tanh 压到 0-1。
    #        绝对占比不可比：中性常占 0.50-0.95、负性常占 0.05-0.20，直接
    #        相减会让"专注"凭中性占比先天领先，无意走神分支事实上不可达。
    #        log(A/B) 与 log(B/A) 互为相反数，故专注与无意走神的情绪项之和
    #        恒为 1，结构性偏置被消除。
    emotion_log_scale: float = 2.0
    # [先验] 概率下界，仅用于避免 log(0)。
    prob_floor: float = 1e-3

    # ---- 熵项对称化 ----
    # [先验] 与情绪项同理：低熵支持"专注/表情受控"，高熵支持"无意走神"。
    #        entropy_mid 取中性主导场景的典型熵，作为二者的中位点。
    entropy_mid: float = 0.35
    entropy_scale: float = 0.15

    # ---- 置信度 ----
    # [先验] Hill 函数 margin/(margin+tau)：渐近趋 1 但永不饱和，
    #        margin 恰等于 tau 时置信度为 0.5。
    confidence_tau: float = 0.15
    # [先验] 人脸覆盖对置信度的折损系数：floor + (1-floor)*face。
    face_conf_floor: float = 0.40
    # [先验] 眨眼率估计不可用（事件数不足）时的置信度折损。
    conf_no_blink_rate: float = 0.70
    # [先验] 个体基线未校准时的置信度折损。
    conf_uncalibrated: float = 0.60

    # ---- 缺席证据封顶 ----
    # [先验] 三个走神分支都没有阳性证据时，focused 只是"排除法结论"，
    #        不应与有明确证据的判定同等确信。否则会出现"信息越少越确信"。
    weak_evidence: float = 0.50
    conf_ceiling_default_focus: float = 0.60

    # ---- 可判性门槛 ----
    # [先验] top1 与 top2 的分数差低于该值时，三态之间没有实质区分度
    #        （典型情形：眨眼率偏离但表情完全中性，focused 与 deliberate
    #        各项几乎并列）。此时拒绝判定，不用浮点噪声决定状态。
    min_decidable_margin: float = 0.02

    # ---- 持续性约束 ----
    # [论文] 2.6 节：rule-based 5-s state-persistence scheme。
    persistence_windows: int = 2

    # ---- 应用层节流 ----
    # [先验] 供前端展示的状态最短刷新间隔，避免每帧抖动。
    emit_interval_sec: float = 0.5

    def positive_set(self) -> set[str]:
        return set(self.positive_emotions)

    def negative_set(self) -> set[str]:
        return set(self.negative_emotions)


DEFAULT_ATTENTION_CONFIG = AttentionConfig()

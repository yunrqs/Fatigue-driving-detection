// 字段名与 FastAPI 返回的 JSON 保持一致，便于对照前后端代码。
import type { FatigueStatus } from '../bodyrecognition/types';

export type Emotion = 'angry' | 'disgust' | 'fear' | 'happy' | 'sad' | 'surprise' | 'neutral';

export interface HealthResponse {
  ok: boolean;
  ready: boolean;
}

/** 后端注意力融合层的三态判定；`unknown` 并非「出错」，而是证据不足。 */
export type AttentionState = 'focused' | 'deliberate_mw' | 'spontaneous_mw' | 'unknown';

/** 三态各自的分数，用于解释「为什么判成这一类」。 */
export interface AttentionScores {
  focused: number;
  deliberate_mw: number;
  spontaneous_mw: number;
}

/** 融合层各分量的中间量，保留下来便于解释判定依据。 */
export interface AttentionSignals {
  blink_ratio: number;
  score_margin: number;
  negative_valence: number;
}

/**
 * 一次窗口判决。注意 `confidence` 是判定强度（Hill 函数映射后的分差），
 * 不是概率，界面不能按百分比呈现，否则会被读成准确率。
 */
export interface AttentionResult {
  state: AttentionState;
  /** 持续性约束生效前的瞬时判定。 */
  raw_state: AttentionState;
  confidence: number;
  scores: AttentionScores;
  signals: AttentionSignals;
  reason: string;
  calibrated: boolean;
}

/**
 * 个体基线校准进度。`blinks` 仅在校准未完成时由后端返回，
 * 已校准时整个键缺失，因此标为可选。
 */
export interface AttentionCalibration {
  calibrated: boolean;
  /** 0 到 1 之间的比例。 */
  progress: number;
  remaining_sec?: number;
  blinks?: number;
}

export interface AnalysisResult extends FatigueStatus {
  frame_width: number;
  frame_height: number;
  face_detected: boolean;
  face_box: [number, number, number, number] | null;
  ear: number | null;
  threshold: number | null;
  eye_state: string;
  blink_detected: boolean;
  blink_count: number;
  blink_rate_per_min: number;
  valid_face_ratio: number;
  emotion: Emotion | null;
  emotion_confidence: number | null;
  emotion_probabilities: Partial<Record<Emotion, number>>;
  /** 首个分析窗口产出前后端显式返回 null，键本身一定存在。 */
  attention: AttentionResult | null;
  /** 旧版后端可能整键缺失，因此可选；缺失时整个注意力面板不渲染。 */
  attention_calibration?: AttentionCalibration;
}

export interface ChartPoint {
  ear: number | null;
  threshold: number | null;
}

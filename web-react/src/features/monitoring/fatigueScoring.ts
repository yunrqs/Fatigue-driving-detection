import type { AnalysisResult, Emotion, FatigueAssessment, FatigueLevel, Sensitivity } from './types';

// 情绪对疲劳的权重，与后端 service.py 的 EMOTION_FATIGUE_WEIGHTS 保持一致：
// 前端用同一份权重把情绪概率折成 0~1 的困倦分，参与疲劳评分（单一事实来源，避免两边漂移）。
export const EMOTION_FATIGUE_WEIGHTS: Record<Emotion, number> = {
  angry: 0.1,
  disgust: 0.1,
  fear: 0.0,
  happy: 0.7,
  sad: 1.0,
  surprise: 0.0,
  neutral: 0.7,
};

// 情绪概率按权重加权，得到 0~1 的困倦近似分（概率和为 1、权重最大为 1，故值域 [0,1]）。
export function emotionWeightedScore(probabilities?: Partial<Record<Emotion, number>>): number {
  if (!probabilities) return 0;
  let score = 0;
  (Object.keys(EMOTION_FATIGUE_WEIGHTS) as Emotion[]).forEach((label) => {
    score += (probabilities[label] ?? 0) * EMOTION_FATIGUE_WEIGHTS[label];
  });
  return Math.min(1, score);
}

// 分级阈值：灵敏度决定「持续多久、触发几个信号」才升级，以及视线偏离的判定时长。
export interface FatigueLevelConfig {
  moderateSeconds: number;
  severeSeconds: number;
  severeSignalCount: number;
  gazeOutsideSeconds: number;
}

export const SENSITIVITY_CONFIG: Record<Sensitivity, FatigueLevelConfig> = {
  calm: { moderateSeconds: 6, severeSeconds: 12, severeSignalCount: 3, gazeOutsideSeconds: 4 },
  standard: { moderateSeconds: 4, severeSeconds: 8, severeSignalCount: 2, gazeOutsideSeconds: 3 },
  strict: { moderateSeconds: 3, severeSeconds: 6, severeSignalCount: 2, gazeOutsideSeconds: 2 },
};

/**
 * 综合疲劳评估：0~100 评分 + 分级 + 当前触发信号。
 * 评分由各信号布尔加权、情绪连续分与持续时间缓升三部分构成，用最小值/最大值收敛到 [0,100]。
 */
export function assessFatigue(
  result: AnalysisResult | null,
  gazeDrowsy: boolean,
  fatigueSeconds: number,
  config: FatigueLevelConfig,
): FatigueAssessment {
  const eye = result?.eye_drowsy ?? false;
  const yawn = result?.is_drowsy ?? false;
  const emotionDrowsy = result?.emotion_drowsy ?? false;
  const gaze = gazeDrowsy;
  const emotionScore = emotionWeightedScore(result?.emotion_probabilities);

  const activeSignals: string[] = [];
  if (eye) activeSignals.push('闭眼');
  if (yawn) activeSignals.push('打哈欠');
  if (emotionDrowsy) activeSignals.push('情绪');
  if (gaze) activeSignals.push('视线偏离');

  let score = 0;
  if (eye) score += 30;
  if (yawn) score += 25;
  if (gaze) score += 25;
  score += emotionScore * 20;
  score += Math.min(15, fatigueSeconds);
  score = Math.round(Math.min(100, Math.max(0, score)));

  const activeCount = activeSignals.length;
  let level: FatigueLevel = 'none';
  if (activeCount > 0) {
    if (activeCount >= config.severeSignalCount || fatigueSeconds >= config.severeSeconds) level = 'severe';
    else if (fatigueSeconds >= config.moderateSeconds) level = 'moderate';
    else level = 'mild';
  }

  return { score, level, activeSignals, emotionScore };
}

// 把秒数格式化成「x 小时 y 分 / x 分 y 秒 / x 秒」，用于连续驾驶时长展示。
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h} 小时 ${m} 分`;
  if (m > 0) return `${m} 分 ${sec} 秒`;
  return `${sec} 秒`;
}

// 连续驾驶超过该秒数（4 小时，交规常见上限）时给出强提醒。
export const LONG_DRIVE_SECONDS = 4 * 3600;
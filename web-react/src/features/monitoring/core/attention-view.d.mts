// 与 attention-view.mjs 配套的类型声明。tsconfig 未开启 allowJs，
// TS 会优先解析同名 .d.mts，因此这里必须与实现逐项对齐。
import type { AnalysisResult, AttentionCalibration, AttentionResult } from '../types';

export type AttentionMode = 'unavailable' | 'calibrating' | 'inconclusive' | 'decided';

export const ATTENTION_STATE_LABELS: Readonly<Record<string, string>>;
export const CONFIDENCE_HIGH: number;
export const CONFIDENCE_MEDIUM: number;
export const CALIBRATING_NOTICE: string;
export const INCONCLUSIVE_NOTICE: string;

export function attentionStateLabel(state: string | null | undefined): string;
export function confidenceLevel(confidence: number | null | undefined): string;
export function attentionMode(
  attention: AttentionResult | null | undefined,
  calibration: AttentionCalibration | null | undefined,
): AttentionMode;
export function attentionNotice(mode: AttentionMode, reason?: string | null): string;
export function hasAttentionData(
  result: Pick<AnalysisResult, 'attention' | 'attention_calibration'> | null | undefined,
): boolean;
export function readAttention(
  result: Pick<AnalysisResult, 'attention' | 'attention_calibration'> | null | undefined,
): { attention: AttentionResult; calibration: AttentionCalibration; mode: AttentionMode } | null;

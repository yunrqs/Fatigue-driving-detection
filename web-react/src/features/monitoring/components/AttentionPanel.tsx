import type { AnalysisResult, AttentionState } from '../types';
import {
  attentionNotice,
  attentionStateLabel,
  confidenceLevel,
  readAttention,
} from '../core/attention-view.mjs';

interface Props {
  result: AnalysisResult | null;
}

// 三态的色调：走神用蓝/琥珀，专注用青色；刻意不用 --danger，红色在疲劳面板里已经代表危险。
const stateTone: Record<AttentionState, string> = {
  focused: 'is-focused',
  deliberate_mw: 'is-deliberate',
  spontaneous_mw: 'is-spontaneous',
  unknown: 'is-inconclusive',
};

/** 注意力融合结论：纯展示，判定与文案全部来自后端字段与 attention-view 的映射。 */
export default function AttentionPanel({ result }: Props) {
  // attention 为 null（首个窗口产出前）或 calibration 整键缺失（旧版后端）时整块隐藏。
  const view = readAttention(result);
  if (!view) return null;

  const { attention, calibration, mode } = view;
  const progress = Number.isFinite(calibration.progress)
    ? Math.min(1, Math.max(0, calibration.progress))
    : 0;
  const remaining = calibration.remaining_sec;
  const reason = typeof attention.reason === 'string' ? attention.reason.trim() : '';

  return (
    <article className="panel attention-panel">
      <div className="panel-heading">
        <div><h2>注意力状态</h2></div>
        <span className="model-tag">情绪 + 眨眼融合</span>
      </div>

      {mode === 'calibrating' ? (
        <>
          {/* 校准期只讲进度与做法，绝不提前给出三态标签。 */}
          <p className="attention-hint">{attentionNotice(mode)}</p>
          <div
            className="attention-progress"
            role="progressbar"
            aria-label="个体基线校准进度"
            aria-valuemin={0}
            aria-valuemax={1}
            aria-valuenow={progress}
          >
            <i style={{ transform: `scaleX(${progress})` }} />
          </div>
          <div className="attention-meta">
            <span>{remaining != null ? `剩余约 ${Math.ceil(remaining)} 秒` : '正在采集基线数据'}</span>
            {calibration.blinks != null && <span>已记录 {calibration.blinks} 次眨眼</span>}
          </div>
        </>
      ) : (
        <>
          <div className="attention-verdict">
            <span className={`attention-state ${stateTone[attention.state] ?? stateTone.unknown}`}>
              {attentionStateLabel(attention.state)}
            </span>
            <span className="attention-level">判定强度 {confidenceLevel(attention.confidence)}</span>
          </div>
          {/* 刻意不以百分比呈现：confidence 是分差映射，没有概率含义。 */}
          <p className="attention-level-note">等级只表示本次判定有多确定，不代表准确率。</p>
          {mode === 'inconclusive' ? (
            // 成因由后端 reason 给出（人脸覆盖不足 / 分数间隔过小），前端不自作断言。
            // 这里已承载理由文本，下方不再重复渲染，避免同一段话出现两次。
            <p className="attention-hint">{attentionNotice(mode, attention.reason)}</p>
          ) : (
            reason && <p className="attention-reason">{attention.reason}</p>
          )}
        </>
      )}
    </article>
  );
}

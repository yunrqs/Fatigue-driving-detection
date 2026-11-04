import type { FatigueLevel, TripSummary } from '../types';
import { formatDuration } from '../fatigueScoring';

const LEVEL_LABEL: Record<FatigueLevel, string> = {
  none: '无',
  mild: '轻度',
  moderate: '中度',
  severe: '重度',
};

// 一次行程结束后的总结报告，以居中弹窗呈现，关闭后回到空白的监测状态。
export default function TripSummaryModal({ summary, onClose }: { summary: TripSummary; onClose: () => void }) {
  return (
    <div className="trip-modal-backdrop" role="dialog" aria-modal="true" aria-label="行程总结">
      <div className="trip-modal">
        <div className="trip-modal-head">
          <div>
            <h2>行程总结</h2>
            <p>{summary.startedAt} — {summary.endedAt}</p>
          </div>
          <button type="button" className="trip-close" onClick={onClose} aria-label="关闭">×</button>
        </div>
        <div className="trip-kpis">
          <div className="trip-kpi"><span>驾驶时长</span><b>{formatDuration(summary.durationSeconds)}</b></div>
          <div className="trip-kpi"><span>疲劳事件</span><b>{summary.fatigueEventCount} 次</b></div>
          <div className="trip-kpi"><span>最高疲劳等级</span><b>{LEVEL_LABEL[summary.maxLevel]}</b></div>
        </div>
        <p className="trip-modal-foot">监测已结束，统计数据已重置，可开始下一次行程。</p>
        <button type="button" className="trip-confirm" onClick={onClose}>关闭</button>
      </div>
    </div>
  );
}
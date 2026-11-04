import { useState } from 'react';
import type { AnalysisResult, ChartPoint, DriverEvent, Emotion, FatigueAssessment, FatigueLevel } from '../types';
import { formatDuration } from '../fatigueScoring';
import EarChart from './EarChart';
import AttentionPanel from './AttentionPanel';
import FatiguePanel from '../../bodyrecognition/components/FatiguePanel';

const emotionMeta: Record<Emotion, [string, string]> = {
  angry: ['愤怒', '!'],
  disgust: ['厌恶', '×'],
  fear: ['恐惧', '△'],
  happy: ['愉悦', '+'],
  sad: ['悲伤', '–'],
  surprise: ['惊讶', '○'],
  neutral: ['中性', '·'],
};

const LEVEL_LABEL: Record<FatigueLevel, string> = {
  none: '正常',
  mild: '轻度',
  moderate: '中度',
  severe: '重度',
};

function number(value: number | null | undefined, digits: number, fallback = '—'): string {
  return value != null && Number.isFinite(value) ? value.toFixed(digits) : fallback;
}

function scoreTier(score: number | null): 'low' | 'mid' | 'high' {
  if (score == null) return 'low';
  if (score >= 80) return 'high';
  if (score >= 50) return 'mid';
  return 'low';
}

interface Props {
  result: AnalysisResult | null;
  history: ChartPoint[];
  gazeDrowsy?: boolean;
  assessment: FatigueAssessment | null;
  events: DriverEvent[];
  driveSeconds: number;
}

export default function ResultPanels({ result, history, gazeDrowsy = false, assessment, events, driveSeconds }: Props) {
  const emotion = result?.emotion;
  const meta = emotion ? emotionMeta[emotion] : null;

  const confidence = meta && result?.emotion_confidence != null
    ? `${(result.emotion_confidence * 100).toFixed(1)}%`
    : '—';

  const isFatigued = (result?.is_fatigued ?? false) || gazeDrowsy;
  const signals = [
    { key: 'eye', label: '闭眼', active: result?.eye_drowsy ?? false },
    { key: 'yawn', label: '打哈欠/肢体', active: result?.is_drowsy ?? false },
    { key: 'emotion', label: '情绪', active: result?.emotion_drowsy ?? false },
    { key: 'gaze', label: '视线', active: (result?.gaze_drowsy ?? false) || gazeDrowsy },
  ];

  const score = assessment?.score ?? null;
  const level = assessment?.level ?? 'none';

  // 时间线默认折叠，只展示最近几条；超过阈值时提供展开/收起。
  const [timelineExpanded, setTimelineExpanded] = useState(false);
  const visibleEvents = timelineExpanded ? events : events.slice(0, 5);

  return (
    <>
      <article className="panel verdict-panel">
        <div className="panel-heading">
          <div><h2>疲劳判定</h2></div>
          <span className="model-tag">多信号融合</span>
        </div>
        <div className={`verdict-banner${isFatigued ? ' fatigued' : ''}`}>
          <span className="verdict-mark">{isFatigued ? '!' : '✓'}</span>
          <div>
            <strong>{isFatigued ? '疑似疲劳驾驶' : '状态正常'}</strong>
            <p>{result ? (isFatigued ? '检测到疲劳信号，请及时休息。' : '未检测到明显疲劳信号。') : '开启识别后显示判定结果'}</p>
          </div>
        </div>
        <div className="verdict-metrics">
          <div className="vmetric">
            <span>疲劳评分</span>
            <b className={`score-${scoreTier(score)}`}>{score ?? '—'}</b>
          </div>
          <div className="vmetric">
            <span>疲劳分级</span>
            <b className={`level-${level}`}>{LEVEL_LABEL[level]}</b>
          </div>
          <div className="vmetric">
            <span>连续驾驶</span>
            <b>{formatDuration(driveSeconds)}</b>
          </div>
        </div>
        <div className="verdict-signals">
          {signals.map((signal) => (
            <span key={signal.key} className={`signal-chip${signal.active ? ' active' : ''}`}>{signal.label}</span>
          ))}
        </div>
      </article>

      <article className="panel state-panel">
        <div className="panel-heading">
          <div><h2>情绪状态</h2></div>
          <span className="confidence-label">置信度 {confidence}</span>
        </div>
        <div className="emotion-focus">
          <div className="emotion-orbit">
            {meta ? (
              <span>{meta[1]}</span>
            ) : (
              <svg width="52" height="52" viewBox="0 0 48 48" fill="none" aria-hidden="true">
                <circle cx="24" cy="24" r="19" stroke="currentColor" strokeWidth="2" />
                <circle cx="18" cy="20" r="2" fill="currentColor" />
                <circle cx="30" cy="20" r="2" fill="currentColor" />
                <path d="M16 28C20 34 28 34 32 28" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            )}
          </div>
          <div>
            <p>主要情绪</p>
            <h3>{emotion || (result ? '未识别' : '等待分析')}</h3>
            <span>{meta?.[0] || (result ? '请保持面部位于画面中央' : '开启识别后显示结果')}</span>
          </div>
        </div>
      </article>

      <article className="panel blink-panel">
        <div className="panel-heading">
          <div><h2>眨眼动态</h2></div>
          <span className="model-tag">EAR</span>
        </div>
        {/* 与眼睛有关的六项指标统一放在眨眼面板中。 */}
        <div className="blink-kpis">
          <div className="kpi">
            <span>EAR</span>
            <strong><b>{number(result?.ear, 3)}</b></strong>
          </div>
          <div className="kpi">
            <span>眼部状态</span>
            <strong><b>{result?.eye_state || '—'}</b></strong>
          </div>
          <div className="kpi">
            <span>累计眨眼</span>
            <strong><b>{result?.blink_count ?? 0}</b><small>次</small></strong>
          </div>
          <div className="kpi">
            <span>眨眼频率</span>
            <strong><b>{number(result?.blink_rate_per_min, 1, '0.0')}</b><small>次/分钟</small></strong>
          </div>
          <div className="kpi">
            <span>动态阈值</span>
            <strong><b>{number(result?.threshold, 3)}</b></strong>
          </div>
          <div className="kpi">
            <span>有效人脸帧</span>
            <strong><b>{Math.round((result?.valid_face_ratio || 0) * 100)}</b><small>%</small></strong>
          </div>
        </div>
        <div className="chart-wrap">
          <div className="chart-label">
            <span>EAR 时间序列</span>
            <span><i />EAR <i className="threshold-key" />阈值</span>
          </div>
          <EarChart history={history} />
        </div>
      </article>

      <FatiguePanel status={result} />

      <AttentionPanel result={result} />

      <article className="panel timeline-panel">
        <div className="panel-heading">
          <div><h2>事件时间线</h2></div>
          <div className="timeline-actions">
            <span className="model-tag">{events.length > 0 ? `${events.length} 条记录` : '空'}</span>
            {events.length > 5 && (
              <button type="button" className="timeline-toggle" aria-expanded={timelineExpanded}
                onClick={() => setTimelineExpanded((value) => !value)}>
                {timelineExpanded ? '收起' : `展开全部（${events.length}）`}
              </button>
            )}
          </div>
        </div>
        {events.length === 0 ? (
          <p className="timeline-empty">暂无事件。开始识别后，疲劳与分心提醒会按时间记录在这里。</p>
        ) : (
          <ol className="timeline">
            {visibleEvents.map((event) => (
              <li key={event.id} className={`timeline-item kind-${event.kind}`}>
                <span className="timeline-time">{event.time}</span>
                <span className="timeline-dot" aria-hidden="true" />
                <span className="timeline-label">{event.label}</span>
              </li>
            ))}
          </ol>
        )}
      </article>
    </>
  );
}
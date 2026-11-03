import type { AnalysisResult, ChartPoint, Emotion } from '../types';
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

function number(value: number | null | undefined, digits: number, fallback = '—'): string {
  return value != null && Number.isFinite(value) ? value.toFixed(digits) : fallback;
}

interface Props {
  result: AnalysisResult | null;
  history: ChartPoint[];
  gazeDrowsy?: boolean;
}

export default function ResultPanels({ result, history, gazeDrowsy = false }: Props) {
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
    </>
  );
}

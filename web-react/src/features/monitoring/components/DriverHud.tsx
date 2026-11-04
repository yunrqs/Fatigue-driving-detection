import type { FatigueAssessment } from '../types';
import { formatDuration, LONG_DRIVE_SECONDS } from '../fatigueScoring';

/**
 * 摄像头页的「驾驶 HUD」：为真实驾驶场景设计的一眼反馈层。
 * 驾驶员开车时不能读表格，因此只呈现：
 *   1. 一个大字状态 + 一句明确指令（该做什么）
 *   2. 触发告警的具体信号（闭眼 / 打哈欠 / 情绪 / 视线偏离）
 *   3. 疲劳评分（0~100）与连续驾驶时长（超 4 小时提醒）
 * 颜色用青(正常)/琥珀(需注意)/红(危险)三级编码，不展示任何需要盯着读的数值。
 */
interface DriverHudProps {
  assessment: FatigueAssessment | null;
  distracted: boolean;
  faceDetected: boolean;
  driveSeconds: number;
  analyzing: boolean;
}

type HudLevel = 'idle' | 'safe' | 'caution' | 'danger';

interface HudView {
  level: HudLevel;
  title: string;
  instruction: string;
  reasons: string[];
  score: number | null;
}

function deriveHud(props: DriverHudProps): HudView {
  const { assessment, distracted, faceDetected, driveSeconds, analyzing } = props;
  if (!analyzing) {
    return { level: 'idle', title: '待启动', instruction: '开始识别后实时监测', reasons: [], score: null };
  }

  const level = assessment?.level ?? 'none';

  if (level === 'severe' || level === 'moderate') {
    return {
      level: 'danger',
      title: '疲劳驾驶',
      instruction: '请立即靠边停车休息',
      reasons: assessment?.activeSignals ?? [],
      score: assessment?.score ?? null,
    };
  }
  if (level === 'mild') {
    return {
      level: 'caution',
      title: '轻度疲劳',
      instruction: '请保持专注，注意休息',
      reasons: assessment?.activeSignals ?? [],
      score: assessment?.score ?? null,
    };
  }

  if (distracted) {
    return { level: 'caution', title: '注意力分散', instruction: '请集中注意力，注视前方', reasons: ['分心'], score: assessment?.score ?? null };
  }
  if (!faceDetected) {
    return { level: 'caution', title: '未检测到人脸', instruction: '请正对摄像头', reasons: [], score: assessment?.score ?? null };
  }
  if (driveSeconds >= LONG_DRIVE_SECONDS) {
    return { level: 'caution', title: '连续驾驶较久', instruction: '建议尽快休息', reasons: ['疲劳驾驶'], score: assessment?.score ?? null };
  }

  return { level: 'safe', title: '状态正常', instruction: '保持专注，谨慎驾驶', reasons: [], score: assessment?.score ?? null };
}

export default function DriverHud(props: DriverHudProps) {
  const hud = deriveHud(props);
  const ariaLabel = hud.reasons.length > 0 ? `触发信号：${hud.reasons.join('、')}` : hud.title;

  return (
    <div className={`driver-hud is-${hud.level}`} role="status" aria-live="polite" aria-label={ariaLabel}>
      <span className="hud-dot" aria-hidden="true" />
      <div className="hud-main">
        <strong>{hud.title}</strong>
        <p>{hud.instruction}</p>
      </div>
      <div className="hud-stats">
        <div className="hud-score">
          <span>疲劳</span>
          <b>{hud.score != null ? hud.score : '—'}</b>
        </div>
        <div className="hud-time">
          <span>驾驶</span>
          <b>{formatDuration(props.driveSeconds)}</b>
        </div>
      </div>
      {hud.reasons.length > 0 && (
        <div className="hud-reasons">
          {hud.reasons.map((reason) => <span key={reason}>{reason}</span>)}
        </div>
      )}
    </div>
  );
}
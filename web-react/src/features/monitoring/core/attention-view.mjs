// 注意力结果的展示映射。抽成纯函数是为了让规格里每条分支都能被 node --test 断言，
// 组件本身只做渲染。命名与后端 fusion_types.py 的 as_dict 保持一一对应。

/** 三态 + 证据不足的中文标签。unknown 单独映射，因为它有两种来源（校准中 / 分数接近）。 */
export const ATTENTION_STATE_LABELS = Object.freeze({
  focused: '专注',
  deliberate_mw: '有意走神',
  spontaneous_mw: '无意走神',
  unknown: '证据不足',
});

/** 等级阈值。0.75 使「高」约只覆盖前 10%，0.45 以下视为分差过小的模糊区间。 */
export const CONFIDENCE_HIGH = 0.75;
export const CONFIDENCE_MEDIUM = 0.45;

/** 校准中的引导语：告诉用户该做什么，而不是给出一个看似确定的结论。 */
export const CALIBRATING_NOTICE = '正在建立你的个体基线，请保持自然状态，不要刻意睁眼或眯眼。';
/**
 * 已校准但无法给出判定时的兜底说明。
 * 刻意不指向任何具体成因：后端返回 unknown 有三种成因（人脸覆盖不足、未校准、分数间隔过小），
 * 前端写死成「分数过于接近」会把人脸丢失说成状态模糊，指引就错了。真实成因以后端 reason 为准。
 */
export const INCONCLUSIVE_NOTICE = '当前证据不足以区分三种状态，暂不给出判定。';

const STATE_LABEL_FALLBACK = '证据不足';

/** 状态码 → 中文标签；未知取值一律降级为「证据不足」，避免界面出现空字符串。 */
export function attentionStateLabel(state) {
  return ATTENTION_STATE_LABELS[state] ?? STATE_LABEL_FALLBACK;
}

/**
 * 判定强度 → 四档等级。
 * 刻意不返回小数或百分比：confidence 是 Hill 函数映射后的分差，没有概率含义。
 */
export function confidenceLevel(confidence) {
  if (typeof confidence !== 'number' || !Number.isFinite(confidence)) return STATE_LABEL_FALLBACK;
  if (confidence >= CONFIDENCE_HIGH) return '高';
  if (confidence >= CONFIDENCE_MEDIUM) return '中';
  if (confidence > 0) return '低';
  return STATE_LABEL_FALLBACK;
}

/**
 * 决定面板该渲染哪种形态。
 * - unavailable：字段缺失或 attention 为 null，整体不渲染
 * - calibrating：基线未建立，只显示进度，不能出现三态标签
 * - inconclusive：已校准但三态分数接近
 * - decided：三态之一
 * 已校准的 unknown 优先于「校准中」判断，因为 attention 可能停留在旧值。
 */
export function attentionMode(attention, calibration) {
  if (!attention || !calibration) return 'unavailable';
  if (attention.state === 'unknown' && attention.calibrated === true) return 'inconclusive';
  if (calibration.calibrated === false) return 'calibrating';
  if (attention.state === 'unknown') return 'inconclusive';
  return 'decided';
}

/**
 * 形态 → 提示语。
 * inconclusive 优先透传后端 reason：它区分了「人脸覆盖不足」与「分数间隔过小」，
 * 前者要用户调整坐姿或光照，后者才是状态本身模糊，指引完全不同。
 */
export function attentionNotice(mode, reason) {
  if (mode === 'calibrating') return CALIBRATING_NOTICE;
  if (mode === 'inconclusive') {
    const text = typeof reason === 'string' ? reason.trim() : '';
    return text || INCONCLUSIVE_NOTICE;
  }
  return '';
}

/** 响应是否含可用的注意力数据：缺 attention 键、其为 null，或缺 calibration，都视为不可渲染。 */
export function hasAttentionData(result) {
  if (!result) return false;
  return Boolean(result.attention) && Boolean(result.attention_calibration);
}

/**
 * 一次性取出组件真正需要的东西：可渲染时返回判定、校准与形态，不可渲染时返回 null。
 * 组件据此提前 return null，既满足「字段缺失时整块隐藏」，也让调用方拿到已收窄的字段。
 */
export function readAttention(result) {
  if (!hasAttentionData(result)) return null;
  const { attention, attention_calibration: calibration } = result;
  return { attention, calibration, mode: attentionMode(attention, calibration) };
}

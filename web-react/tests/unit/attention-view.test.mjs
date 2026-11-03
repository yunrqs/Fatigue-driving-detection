import test from 'node:test';
import assert from 'node:assert/strict';
import {
  attentionMode,
  attentionNotice,
  attentionStateLabel,
  confidenceLevel,
  hasAttentionData,
  readAttention,
} from '../../src/features/monitoring/core/attention-view.mjs';

// 三态必须能一眼区分，否则面板等同于只说「走神」。
test('三种确定状态映射为互不相同的中文标签', () => {
  const labels = ['focused', 'deliberate_mw', 'spontaneous_mw'].map(attentionStateLabel);
  assert.deepEqual(labels, ['专注', '有意走神', '无意走神']);
  assert.equal(new Set(labels).size, 3);
  assert.equal(attentionStateLabel('unknown'), '证据不足');
});

// 阈值边界全部取到，防止后续改常量时无意挪动分档。
test('判定强度按 0.75 / 0.45 分为四档', () => {
  assert.equal(confidenceLevel(0.8), '高');
  assert.equal(confidenceLevel(0.75), '高');
  assert.equal(confidenceLevel(0.6), '中');
  assert.equal(confidenceLevel(0.45), '中');
  assert.equal(confidenceLevel(0.3), '低');
  assert.equal(confidenceLevel(0), '证据不足');
  assert.equal(confidenceLevel(null), '证据不足');
});

// 同一句「未知」会让用户不知道该等校准还是该换个状态，因此两种来源必须是不同文案。
test('已校准与未校准的 unknown 分流为不同形态与不同文案', () => {
  const calibratedUnknown = { state: 'unknown', calibrated: true, confidence: 0.1, reason: '' };
  const uncalibratedUnknown = { state: 'unknown', calibrated: false, confidence: 0.1, reason: '' };

  const inconclusive = attentionMode(calibratedUnknown, { calibrated: true, progress: 1 });
  const calibrating = attentionMode(uncalibratedUnknown, { calibrated: false, progress: 0.42, blinks: 3 });

  assert.equal(inconclusive, 'inconclusive');
  assert.equal(calibrating, 'calibrating');
  assert.notEqual(attentionNotice(inconclusive), attentionNotice(calibrating));
  assert.match(attentionNotice(calibrating), /自然状态/);
  // reason 为空时只能用兜底文案，且不得指认具体成因。
  assert.doesNotMatch(attentionNotice(inconclusive), /分数过于接近/);
  // 证据不足时不能出现「专注」，否则用户会把它读成一个确定结论。
  assert.ok(!attentionNotice(inconclusive).includes('专注'));
});

// 后端 unknown 有三种成因，前端固定指认「分数过于接近」会把「人脸丢失」误报成「状态模糊」，
// 用户该调整坐姿却被告知状态不清。因此 inconclusive 必须透传后端 reason。
test('证据不足的成因以后端 reason 为准而非前端断言', () => {
  const faceCase = '人脸覆盖不足（0.17 < 0.6），不予判定';
  const marginCase = '三态分数间隔过小（0.011 < 0.02），不予判定';

  const faceNotice = attentionNotice('inconclusive', faceCase);
  assert.match(faceNotice, /人脸覆盖不足/);
  assert.doesNotMatch(faceNotice, /分数/);

  assert.equal(attentionNotice('inconclusive', marginCase), marginCase);

  // reason 为空白或无意义内容时退回兜底，且兜底不指认成因。
  for (const empty of ['', '   ', null, undefined, 123]) {
    const notice = attentionNotice('inconclusive', empty);
    assert.equal(notice, attentionNotice('inconclusive'));
    assert.doesNotMatch(notice, /分数过于接近/);
  }

  // 校准中不采用 reason：此时后端 reason 是校准提示，界面已有更明确的引导语。
  assert.match(attentionNotice('calibrating', faceCase), /自然状态/);
});

// attention 为 null、缺键、缺 calibration 三种输入都只能「不渲染」，不能抛错。
test('注意力字段缺失时判定为不可渲染且不抛异常', () => {
  const calibration = { calibrated: false, progress: 0.42, remaining_sec: 17.5, blinks: 3 };
  const attention = { state: 'focused', calibrated: true, confidence: 0.6, reason: '眨眼率贴合个体基线' };
  const cases = [
    { attention: null, attention_calibration: calibration },
    { attention_calibration: calibration },
    {},
  ];

  for (const result of cases) {
    assert.doesNotThrow(() => hasAttentionData(result));
    assert.equal(hasAttentionData(result), false);
    assert.equal(readAttention(result), null);
    assert.equal(attentionMode(result.attention, result.attention_calibration), 'unavailable');
  }

  assert.equal(hasAttentionData({ attention, attention_calibration: calibration }), true);
  // 校准完成后才可能给出确定态，这里的 calibration 必须是已校准的，否则会被分流到「校准中」。
  assert.equal(attentionMode(attention, { calibrated: true, progress: 1, remaining_sec: 0 }), 'decided');
});

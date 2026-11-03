// 跨语言校验：把后端真实 as_dict() + calibration_progress() 的输出喂给前端映射层。
// 单元测试用的是手写桩，这里用的是真字段名，能抓到 Python 与 TS 两侧命名不一致。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  attentionMode,
  attentionNotice,
  attentionStateLabel,
  confidenceLevel,
  readAttention,
} from '../../src/features/monitoring/core/attention-view.mjs';

const payload = JSON.parse(
  readFileSync(new URL('../../../.workbuddy/tmp/attention_payload.json', import.meta.url), 'utf8'),
);

test('后端真实载荷能被前端映射层完整消费', () => {
  const seen = {};

  for (const [stage, snapshot] of Object.entries(payload)) {
    // 后端每帧返回的最小形状：两个键都必须存在。
    assert.ok('attention' in snapshot, `${stage} 缺少 attention 键`);
    assert.ok('attention_calibration' in snapshot, `${stage} 缺少 attention_calibration 键`);

    const view = readAttention(snapshot);
    assert.ok(view, `${stage} 被判为不可渲染，但后端确实返回了数据`);

    const { attention, calibration, mode } = view;
    // 字段名必须逐项命中，任一拼错都会在这里变成 undefined。
    assert.equal(typeof attention.state, 'string', `${stage}.state 不可读`);
    assert.equal(typeof attention.confidence, 'number', `${stage}.confidence 不可读`);
    assert.equal(typeof attention.reason, 'string', `${stage}.reason 不可读`);
    assert.equal(typeof attention.calibrated, 'boolean', `${stage}.calibrated 不可读`);
    assert.equal(typeof calibration.progress, 'number', `${stage}.progress 不可读`);

    seen[stage] = {
      mode,
      label: attentionStateLabel(attention.state),
      level: confidenceLevel(attention.confidence),
      notice: attentionNotice(mode),
    };
  }

  // 校准早期：后端 attention 已非 null 但 calibrated=false，必须归为 calibrating 而非三态。
  assert.equal(seen.calibrating.mode, 'calibrating', '校准期不得展示三态');
  assert.equal(seen.calibrating.label, '证据不足');
  assert.ok(seen.calibrating.notice.length > 0, '校准期必须给引导文案');

  assert.equal(seen.focused.mode, 'decided');
  assert.equal(seen.focused.label, '专注');

  assert.equal(seen.spontaneous.mode, 'decided');
  assert.equal(seen.spontaneous.label, '无意走神');
  // attention.calibration 在已校准时不带 blinks 键，前端必须不依赖它。
  assert.equal('blinks' in payload.spontaneous.attention_calibration, false);

  console.log('\n后端真实载荷 → 前端映射结果：');
  for (const [stage, row] of Object.entries(seen)) {
    console.log(`  ${stage.padEnd(20)} mode=${row.mode.padEnd(12)} label=${row.label.padEnd(6)} level=${row.level}`);
  }
});

test('后端真实载荷的数值落在等级阈值上时映射正确', () => {
  const focused = readAttention(payload.focused);
  // 实测 confidence ≈ 0.7411，应落在「中」而非「高」。
  assert.equal(confidenceLevel(focused.attention.confidence), '中');
  assert.ok(focused.attention.confidence < 0.75);

  const spontaneous = readAttention(payload.spontaneous);
  assert.equal(confidenceLevel(spontaneous.attention.confidence), '高');
  assert.ok(spontaneous.attention.confidence >= 0.75);
});

test('首帧 attention 为 null 时整块隐藏', () => {
  const firstFrame = { attention: null, attention_calibration: { calibrated: false, progress: 0, remaining_sec: 30.0 } };
  assert.equal(readAttention(firstFrame), null);
  assert.equal(attentionMode(null, firstFrame.attention_calibration), 'unavailable');
});

test('旧版后端整键缺失时整块隐藏且不抛错', () => {
  assert.equal(readAttention({ frame_width: 640 }), null);
  assert.equal(readAttention(null), null);
});

// 用真实载荷的字段结构验证「成因透传」：只改 state 与 reason，其余字段保持后端原样，
// 确保真实场景下（人脸丢失）前端不会把成因说成「分数过于接近」。
test('后端真实字段结构下，证据不足的成因被正确透传', () => {
  const faceLoss = {
    ...payload.focused,
    attention: {
      ...payload.focused.attention,
      state: 'unknown',
      raw_state: 'unknown',
      confidence: 0,
      reason: '人脸覆盖不足（0.17 < 0.6），不予判定',
    },
  };

  const view = readAttention(faceLoss);
  assert.ok(view);
  assert.equal(view.mode, 'inconclusive');
  assert.equal(attentionStateLabel(view.attention.state), '证据不足');

  const notice = attentionNotice(view.mode, view.attention.reason);
  assert.match(notice, /人脸覆盖不足/);
  assert.doesNotMatch(notice, /分数/);
  assert.ok(!notice.includes('专注'));
});

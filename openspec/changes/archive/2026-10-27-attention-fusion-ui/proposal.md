# Proposal

## Why

后端已完成注意力融合层并接入 `POST /api/analyze`，每帧返回 `attention` 与 `attention_calibration` 两个字段，但前端从未消费它们。结果是：一个已跑通、已通过 15 项单元测试的能力，在界面上完全不可见；`ResultPanels.tsx` 甚至仍硬编码着「走神分类暂未接入」这句已经失效的说明。用户能看到的只有情绪与眨眼，看不到这两路信号融合后的结论。

## What Changes

- `web-react/src/features/monitoring/types.ts` 新增 `AttentionState`、`AttentionResult`、`AttentionCalibration` 三个类型，`AnalysisResult` 追加两个字段（`attention` 可为 `null`，`attention_calibration` 可选）。
- 新增 `web-react/src/features/monitoring/components/AttentionPanel.tsx`，覆盖四种展示形态：未校准（进度条 + 剩余秒数）、三态判定（专注 / 有意走神 / 无意走神）、已校准但证据不足、后端字段缺失（整块隐藏）。
- `ResultPanels.tsx` 挂载新面板，并移除已失效的「走神分类暂未接入」提示卡。
- `web-react/src/styles/global.css` 为仪表盘新增一个具名栅格区域，并补齐面板样式。

明确不做：后端任何改动、`EarChart` 时序图、伪标签落盘与数据导出、`requirements.txt` 依赖修复、注意力历史趋势图。

## Capabilities

### New Capabilities

- `attention-fusion-ui`：把后端注意力融合结果呈现为可理解的界面状态，包括三态判定、判定强度等级、判定理由、个体基线校准引导，以及在证据不足或数据缺失时的显式降级。

### Modified Capabilities

（无。`openspec/specs/` 当前仅有占位文件，尚无既有能力的需求被改动。）

## Impact

**受影响代码**

- `web-react/src/features/monitoring/types.ts` — 类型扩展
- `web-react/src/features/monitoring/components/AttentionPanel.tsx` — 新增
- `web-react/src/features/monitoring/components/ResultPanels.tsx` — 挂载面板、移除失效提示
- `web-react/src/styles/global.css` — 新增栅格区域与面板样式

**接口**

只读消费既有 `POST /api/analyze` 响应，不新增、不修改任何后端接口。

**关键约束**

- 仪表盘是固定命名栅格，`grid-template-areas` 在主布局（第 177 行）与响应式断点（第 353 行）各定义一次，新增面板必须两处同步，否则面板会被挤到隐式行列。
- `attention` 在首个分析窗口产出前为 `null`；`attention_calibration.blinks` 仅在未校准时存在。两者都必须容忍，否则首帧渲染即崩溃。
- `confidence` 是判定强度（胜出分数与次高分之差经 Hill 函数映射），不是概率。界面若以百分比呈现，会被读成准确率。

**依赖**

无新增依赖。

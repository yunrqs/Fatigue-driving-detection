# Design

## Context

参见 `proposal.md` — Why。

设计前已核实的三项现状事实，直接决定了下面每个决策：

1. **后端输出的形状**（`backend/src/mind_wandering/fusion/`）：
   - `attention` 在首个分析窗口产出前为 `null`（`service.py:157`）。
   - `attention_calibration` 始终存在，但 `blinks` 键仅在未校准时出现（`engine.py:calibration_progress`）。
   - `confidence` 由 Hill 函数 `margin/(margin+0.15)` 产生，实测达到 1.0 的比例为 0%，中位数约 0.60——它是判定强度，与准确率无关。
2. **仪表盘是固定命名栅格**：`global.css:177` 定义 `grid-template-areas: "camera camera" "fatigue emotion" "blink gaze"`，`global.css:353` 在响应式断点重定义一次。新增面板必须两处同步。
3. **样式体系为深色主题变量**（`--bg #07101d`、`--text #edf6ff`、`--cyan`、`--blue`、`--amber`、`--danger`），既有面板复用 `.panel` / `.kpi` / `.notice-card` 等类。

## Goals / Non-Goals

**Goals**

- 后端字段到界面元素一一对应，不引入前端侧推断逻辑（等级换算除外，见决策 2）。
- 所有降级路径在实现前就被枚举清楚，避免运行期崩溃。

**Non-Goals**

- 不在前端重算或修正后端判定。
- 不做注意力时序趋势图（需新增历史缓冲，超出本次范围）。
- 不改 `EarChart`、不改后端、不改 `AnalysisResult` 既有字段语义。

## Decisions

### 决策 1：面板作为独立组件挂进 `ResultPanels`，而非并入情绪面板

`ResultPanels` 目前渲染情绪、眨眼、疲劳三块，注意力是第四个独立语义单元。并列而非合并的理由：情绪面板已有「主要情绪 + 置信度」结构，注意力需要状态标签 + 等级 + 理由 + 校准进度四段，塞进去会让该面板承担两种判读逻辑。

*备选*：改造情绪面板的 `notice-card` 原地替换为注意力内容。否决原因：该提示卡的语义是「当前不判断」，与「展示判断」相反，原地替换会让组件职责变得隐晦。

### 决策 2：置信度映射为四档等级，阈值取 0.75 / 0.45 / >0

实测分布为：中位数 0.60、p90 0.741、达 1.0 比例 0%。选 0.75 作为「高」的门槛，使「高」保持稀缺（约前 10%），避免面板长期显示「高」而失去信息量；0.45 以下为「低」，覆盖分数接近的模糊区间。

*备选*：直接显示两位小数。否决原因：`0.60` 会被读成 60% 准确率，而该值没有任何概率含义，这是本次设计要主动规避的误读。

### 决策 3：`unknown` 按 `calibrated` 分流为两种文案，不复用同一个「未知」

后端存在两种语义完全不同的 `unknown`：未校准（还不知道你的基线）与已校准但分数过于接近（看清了但分不开）。两者对用户的行动指引相反——前者要求「保持自然状态等 30 秒」，后者要求「当前状态本身模糊」。用同一文案会让用户无法判断该做什么。

判定条件：`state === 'unknown'` 且 `calibrated === true` → 证据不足；`attention_calibration.calibrated === false` → 校准中。前者优先于后者判断，因为 `attention` 可能停留在旧值。

**实现期修正**：最初把「证据不足」一律归因为「三态分数接近」，这是错的。后端 `rules.py` 有三处返回 `unknown`——人脸覆盖不足（第 187 行）、未校准（第 201 行）、分数间隔过小（第 216 行）。已用真实引擎验证：人脸丢失后人脸覆盖率降到 0.17 时，返回 `state=unknown, calibrated=true, reason="人脸覆盖不足（0.17 < 0.6），不予判定"`。若前端固定显示「三态分数过于接近」，结论与指引都会错——用户该调整坐姿，却被告知状态模糊。因此该形态一律展示后端 `reason` 原文，缺失时才用不指向具体成因的通用说明。

### 决策 4：新增具名栅格区域 `attention`，位置放在 `blink` 之后

主布局改为 `"camera camera" "fatigue emotion" "blink gaze" "attention attention"`，跨两列的整行。理由：注意力是融合结论，逻辑上统摄情绪与眨眼两路输入，横向整行放在其后符合「输入在上、融合结论在下」的阅读顺序；跨两列可容纳理由文本而不折行。

*备选*：插入为 `"fatigue emotion" "attention attention" "blink gaze"`。否决原因：会把两路输入信号挤到结论下方，因果顺序颠倒。

响应式断点（`local max-width` 段）追加 `"attention"` 到单列序列末尾，与主布局顺序保持一致。

### 决策 5：类型定义区分「可空」与「可缺失」

```ts
attention: AttentionResult | null          // 后端显式返回 null，键一定存在
attention_calibration?: AttentionCalibration // 旧版后端可能整键缺失
```

两者语义不同：`null` 表示「本帧尚无判定」，缺键表示「后端不支持」。组件对前者隐藏判定区但可显示校准，对后者整体隐藏。若把两者都写成可选，会丢掉「有校准进度但还没判定」这个真实中间态。

### 决策 6：展示映射逻辑抽为 `.mjs` 纯函数，用 `node --test` 覆盖

项目无 React 测试库，`package.json` 只有 `test:unit`（`node --test tests/unit/*.test.mjs`）与 playwright。已有先例：`src/features/gaze/core/regression.mjs` 提供纯逻辑，被 `gazeService.ts` 导入，并由 `tests/unit/gaze-regression.test.mjs` 覆盖。

沿用该约定：把「状态 → 标签」「confidence → 等级」「unknown 分流」「字段缺失判定」四类映射抽到 `src/features/monitoring/core/attention-view.mjs`，组件只负责渲染。这样规格里每条关于文案与降级的行为都能写成真实断言，而不是只能靠肉眼。

*备选*：直接把逻辑写在组件里，仅靠 `npm run build` 与人工目测验收。否决原因：规格中的六条 Requirement 几乎全是分支判断，肉眼无法稳定复验，尤其在「已校准 unknown」与「未校准」这对易混分支上。

### 决策 7：不引入状态管理或请求层改动

面板是纯展示组件，输入为 `AnalysisResult`，无内部状态、无副作用、无额外请求。`pages/Monitor/index.tsx` 无需改动——`ResultPanels` 已接收完整 `result`，透传即可。这与 proposal「不做后端改动」一致，也避免动到 `Monitor` 里已有的帧循环逻辑。

## Risks / Trade-offs

- **[栅格漏改]** 只改 `global.css:177` 而漏掉 `:353`，面板会被挤进隐式行导致布局错位 → 实现时两处同时改，验收阶段用窄视口人工核对。
- **[等级阈值可能与真实分布不符]** 0.75/0.45 基于合成信号蒙特卡洛，真人数据可能整体偏低，导致长期显示「中」→ 阈值集中在一处常量，便于后续按实测调整；本次不追求分布完美。
- **[`attention` 滞后于其他字段]** 融合层按窗口产出，首帧到首个窗口之间 `attention` 恒为 `null`，界面会先出现校准条再出现三态，属于预期行为 → 在组件中以「校准中」承载这段时间，不显示空判定框。
- **[移除失效提示卡可能被误读为功能声明]** 删掉「走神分类暂未接入」后，用户可能认为走神判定已完全可靠 → 面板内保留等级说明文案，并在理由区展示后端原文，让判定依据始终可见。
- **[`blinks` 可选键]** 已校准时该键缺失，若按必需字段处理会在校准时崩溃 → 类型上标可选，渲染时按存在性判断。
- **[`.mjs` 与 TS 混用]** 新模块与既有 `regression.mjs` 依赖同一解析路径，若 TS 解析报错会同时影响 `typecheck` → 类型以 JSDoc 或同名 `.d.ts` 声明补齐，实现后立刻跑 `npm run build` 确认，不与组件改动混在一次编辑里。

## Migration Plan

纯前端增量，无数据迁移、无接口版本变更。

1. 扩展类型 → 2. 新增组件 → 3. 挂载并移除失效提示 → 4. 补样式（两处栅格）。
2. 回滚策略：删除组件文件并还原 `ResultPanels.tsx` 与 `global.css` 即可，后端不受影响；因后端字段独立于前端消费，回滚后行为等同当前状态。

## Open Questions

- 等级阈值 0.75/0.45 是否需在真人长会话后调整——可延后，因为阈值集中为常量，调整不影响组件结构与规格。

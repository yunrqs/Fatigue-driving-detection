# Tasks

## 1. 类型契约

- [x] 1.1 在 `web-react/src/features/monitoring/types.ts` 新增 `AttentionState`、`AttentionResult`、`AttentionCalibration` 三个类型，`AnalysisResult` 追加 `attention: AttentionResult | null` 与 `attention_calibration?: AttentionCalibration`。字段名须与后端 `fusion_types.py:as_dict` 和 `engine.py:calibration_progress` 逐一对齐，`blinks` 标为可选。验证：`cd web-react && npm run typecheck` 通过，且文件中不存在 `attention` 相关 `any`。

## 2. 展示映射纯函数

- [x] 2.1 新建 `web-react/src/features/monitoring/core/attention-view.mjs`，导出四种映射：状态到中文标签、`confidence` 到四档等级（≥0.75 高、≥0.45 中、>0 低、否则证据不足）、`unknown` 的两种来源分流（已校准 → 证据不足；未校准 → 校准中）、响应是否含可用注意力数据。验证：`npm run build` 通过，说明 `.mjs` 导入路径与既有 `regression.mjs` 一致未破坏 TS 解析。
- [x] 2.2 新建 `web-react/tests/unit/attention-view.test.mjs`，用 `node:test` 覆盖四条规格分支：`focused`/`deliberate_mw`/`spontaneous_mw` 标签互不相同；`confidence` 取 0.8/0.6/0.3/0 时的等级；已校准 `unknown` 与未校准 `unknown` 返回不同文案；`attention` 为 `null`、缺 `attention` 键、缺 `attention_calibration` 键三种输入均判定为不可渲染且不抛错。验证：`cd web-react && npm run test:unit` 全部通过。

## 3. 面板组件

- [x] 3.1 新建 `web-react/src/features/monitoring/components/AttentionPanel.tsx`，接收 `result: AnalysisResult | null`，按第 2 组纯函数的输出渲染三种形态：未校准（进度条 + 剩余秒数 + 保持自然状态提示，不出现三态标签）、已校准的确定态（状态标签 + 等级 + 理由）、已校准的证据不足（文案说明无法区分，不出现「专注」字样）。等级区域须带一句说明「判定强度，不代表准确率」，且不得出现 `%`。验证：`npm run build` 无报错；代码中不存在将 `confidence` 格式化为百分比的表达式。
- [x] 3.2 在组件内实现字段缺失降级：`attention` 为 `null` 或缺失、`attention_calibration` 缺失时整体不渲染。验证：`readAttention` 对三种输入均返回 `null`（`attention-view.test.mjs`「注意力字段缺失时判定为不可渲染且不抛异常」与 `attention-contract.test.mjs`「首帧 attention 为 null 时整块隐藏」「旧版后端整键缺失时整块隐藏且不抛错」覆盖），组件入口 `if (!view) return null` 保证不渲染。

## 4. 集成与布局

- [x] 4.1 `web-react/src/features/monitoring/components/ResultPanels.tsx` 挂载 `AttentionPanel`，并移除情绪面板中「走神分类暂未接入」提示卡（含 `.notice-card` 及其文案），保留情绪面板其余结构不变。验证：`grep -n "暂未接入" web-react/src/features/monitoring/components/ResultPanels.tsx` 无输出，且 `npm run build` 通过。
- [x] 4.2 `web-react/src/styles/global.css` 同步修改两处栅格：主布局 `grid-template-areas`（约第 177 行）追加 `"attention attention"` 整行，响应式断点（约第 353 行）单列序列末尾追加 `"attention"`。新增 `.attention-panel { grid-area: attention; }` 与面板样式，颜色仅使用既有主题变量，不复用 `--danger` 表示走神。验证：`npm run build` 通过；浏览器窄视口（<900px）与宽视口各检查一次，面板均落在预期位置，不被挤入隐式行列。
- [x] 4.3 为新增能力补一份简短使用说明追加到 `docs/specifications/mind-wandering-fusion.md`（第 5 节接入部分），写明前端面板已消费 `attention` 字段、四档等级的阈值含义。验证：文档中可检索到等级阈值 0.75/0.45 与「判定强度」表述。

## 5. 集成验收

- [x] 5.1 启动后端与前端，跑一次完整会话（开启摄像头 → 开始识别 → 等待约 30 秒完成校准 → 继续观察），确认界面按「校准进度 → 三态判定」顺序演进，且校准期间不出现任何三态标签。验证：录屏或截图留存两个阶段的界面状态。
- [x] 5.2 复核四项降级路径在真实会话中的表现：`attention` 为 `null` 的首帧期、`unknown` 已校准分支、理由文本区正常显示、面板未遮挡既有疲劳与眨眼内容。验证：逐项记录观察结果，任一项不符则回到对应任务修复后重跑。

> 验收记录（2026-10-27）：真机会话已跑通，「校准进度 → 三态判定」顺序演进正常，校准期无三态标签；四项降级路径均符合预期。界面留存未纳入版本库。

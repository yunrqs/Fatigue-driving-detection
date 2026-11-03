# attention-fusion-ui Specification

## Purpose

让用户看到后端注意力融合层的判定结果：当前是专注还是走神、走神属于哪一类、判定有多确定、依据是什么，并在个体基线尚未建立或证据不足时明确说明原因，而不是给出一个看似确定的结论。

## Requirements

### Requirement: 展示注意力三态判定

面板 SHALL 把后端返回的 `attention.state` 映射为四种可区分的中文状态：`focused` 显示「专注」，`deliberate_mw` 显示「有意走神」，`spontaneous_mw` 显示「无意走神」，`unknown` 显示「证据不足」。三种确定状态 MUST 在视觉上互相可区分，且 MUST NOT 复用疲劳面板的红/绿语义表示「危险/正常」。

#### Scenario: 处于专注状态

- **WHEN** 后端返回 `attention.state` 为 `focused` 且 `attention.calibrated` 为 `true`
- **THEN** 面板显示「专注」标签
- **AND** 面板不出现任何表示疲劳或危险的颜色语义

#### Scenario: 两类走神可区分

- **WHEN** 后端先后返回 `deliberate_mw` 与 `spontaneous_mw`
- **THEN** 面板对两者显示不同文案
- **AND** 两者的视觉标识互不相同

### Requirement: 判定强度以等级呈现

面板 SHALL 把 `attention.confidence` 呈现为等级而非百分比。等级 MUST 为「高」「中」「低」「证据不足」四档之一，并在面板内提供一句话说明该等级表示判定强度、不代表准确率。

#### Scenario: 高判定强度

- **WHEN** `attention.confidence` 大于等于 0.75
- **THEN** 面板显示等级「高」

#### Scenario: 低判定强度

- **WHEN** `attention.confidence` 大于 0 且小于 0.45
- **THEN** 面板显示等级「低」

#### Scenario: 不出现百分比

- **WHEN** 面板渲染任意 `attention` 结果
- **THEN** 判定强度区域不出现 `%` 字符

### Requirement: 展示判定理由

面板 SHALL 原样展示 `attention.reason` 文本，使用户能读到本次判定的依据。理由文本缺失或为空时，面板 MUST 隐藏该区域而非显示空占位。

#### Scenario: 有理由文本

- **WHEN** `attention.reason` 为非空字符串
- **THEN** 面板显示该文本

#### Scenario: 理由文本为空

- **WHEN** `attention.reason` 为空字符串或缺失
- **THEN** 面板不渲染理由区域

### Requirement: 未校准时展示校准引导

当 `attention_calibration.calibrated` 为 `false` 时，面板 SHALL 展示校准进度、剩余秒数与「保持自然状态」提示，且 MUST NOT 展示三态标签。进度 SHALL 以 0 到 1 之间的比例渲染为进度条；`remaining_sec` 存在时 SHALL 以秒为单位展示剩余时间。

#### Scenario: 校准进行中

- **WHEN** `attention_calibration.calibrated` 为 `false` 且 `progress` 为 0.42
- **THEN** 面板显示约 42% 的进度条
- **AND** 面板不显示「专注」「有意走神」「无意走神」中的任何一个

#### Scenario: 校准完成

- **WHEN** `attention_calibration.calibrated` 为 `true`
- **THEN** 面板隐藏校准进度条
- **AND** 面板按判定结果展示状态

#### Scenario: 校准阶段的眨眼次数可选

- **WHEN** `attention_calibration` 不含 `blinks` 键
- **THEN** 面板正常渲染校准进度，不报错也不显示空白字段

### Requirement: 区分证据不足的成因

后端输出 `unknown` 有三种成因，其中两种在已校准时也可能出现：分数间隔过小、人脸覆盖不足。当 `attention.state` 为 `unknown` 且 `attention.calibrated` 为 `true` 时，面板 SHALL 展示「证据不足」，并 MUST 展示 `attention.reason` 以说明实际成因，MUST NOT 断言成因为分数接近。理由文本缺失时，面板 SHALL 使用不指向任何具体成因的通用说明。该状态 MUST NOT 显示为「专注」。

#### Scenario: 已校准但分数接近

- **WHEN** `attention.state` 为 `unknown`、`attention.calibrated` 为 `true`，且 `attention.reason` 为分数接近的说明
- **THEN** 面板显示「证据不足」
- **AND** 面板显示该理由文本
- **AND** 面板不出现「专注」字样

#### Scenario: 已校准但人脸覆盖不足

- **WHEN** `attention.state` 为 `unknown`、`attention.calibrated` 为 `true`，且 `attention.reason` 说明人脸覆盖不足
- **THEN** 面板显示「证据不足」
- **AND** 面板显示人脸覆盖不足的理由文本
- **AND** 面板不出现「三态分数过于接近」或等效表述

#### Scenario: 理由文本缺失时的通用说明

- **WHEN** `attention.state` 为 `unknown`、`attention.calibrated` 为 `true`，且 `attention.reason` 为空
- **THEN** 面板显示「证据不足」与一段不指向具体成因的说明
- **AND** 面板不出现「三态分数过于接近」或等效表述

### Requirement: 后端字段缺失时降级

当响应中缺少 `attention` 字段、其值为 `null`，或缺少 `attention_calibration` 字段时，面板 SHALL 隐藏自身内容且不抛出异常，仪表盘其余部分 MUST 保持正常渲染。

#### Scenario: 首帧尚无判定结果

- **WHEN** 后端返回 `attention` 为 `null`
- **THEN** 面板不渲染任何判定内容
- **AND** 页面其余面板正常显示

#### Scenario: 旧版后端不含注意力字段

- **WHEN** 响应中完全没有 `attention` 与 `attention_calibration` 键
- **THEN** 面板不渲染
- **AND** 页面不出现错误提示或崩溃

### Requirement: 移除已失效的走神说明

情绪面板中声明「走神分类暂未接入」的提示 SHALL 移除，因为注意力判定已在该界面呈现。

#### Scenario: 情绪面板不再声称未接入

- **WHEN** 用户查看监控页面
- **THEN** 情绪面板中不出现「走神分类暂未接入」或等效表述

## Why

用户进一步明确：text 限定的是 Solver 的回答格式，不是策略开关或独立运行架构。此前独立 TextReasoningRuntime 改变了审核和调度，不符合这一边界。需要新增复用原 JSON ReasoningRuntime 的运行器，只解除 Solver 的复杂 JSON 输出负担。

## What Changes

- 新增继承 ReasoningRuntime 的 SolverTextReasoningRuntime，只覆盖 Solver 请求与文本提案包装。
- 分类、形式化、策略预处理、Critic、Repair、Replanner、候选验证和 Finalizer 均沿用原 JSON 协议和方法。
- 程序将自然语言原文包装为当前任务的粗粒度待审核提案，不新增转 JSON 的模型调用，不自动接受。
- text 入口切换到新运行器，旧独立 TextReasoningRuntime 暂留历史模块与测试，不再由配置选中。
- 最终仍由程序组装字典；非证明题仅 boxed 最终结果，证明题保留证明。平台诊断不公开原始模型响应。
- 保留 JSON 默认、原调度和预算语义；不把原策略是否启用、任务拆分数量或工具机制绑定到 text。

## Capabilities

### New Capabilities

- `custom2-natural-language-runtime`: 复用原 JSON Runtime 的 Solver 自然语言回答适配。

### Modified Capabilities

无；原 JSON 调度不修改。

## Impact

新增 Solver 文本运行器和离线测试，调整 Custom2Agent 入口和文档。复用既有解析工具、状态结构和客户端包装，不增加依赖，不调用真实 API 评测，不修改数据集或已有策略材料变更。

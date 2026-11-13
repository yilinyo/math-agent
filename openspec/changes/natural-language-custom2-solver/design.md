## Context

本轮以用户澄清为准：text 是 Solver 回答格式。先前独立文本任务调度不再作为此配置的实现；原策略预处理、任务调度和纠错汇总保持原 JSON ReasoningRuntime。

## Goals / Non-Goals

目标是模型专注当前任务的数学推导，程序接入既有状态协议。非目标是重写任务图、自然语言审核、改变重规划预算、添加计算闭环或承诺提分。

## Decisions

1. 新类 SolverTextReasoningRuntime 继承 ReasoningRuntime，只覆盖构造和 `_solve_step`。`run`、高效调度、逐步调度及所有非 Solver 角色使用原方法。text 入口选择新类，json 入口仍选择原类。
2. Solver 输入保留原题、当前任务、策略、可靠状态和失败记忆，仅替换输出指令。任务范围由原策略和调度决定，可以是整题或子任务。无需状态 JSON 或局部 boxed；有效 ReasoningStep JSON 仍兼容。
3. 程序把完整正文作为一个待审核 ResultProposal，绑定当前任务，并保守依赖当前全部 verified 输入。所有结论保持原文，不推断精确数学依赖；关闭当前任务只是申请，request_finalization 为 false。审核接受前不修改 authoritative state。
4. 采用粗粒度提案，不额外请求模型做结构化转换。因此减少 Solver 格式负担，但部分接受粒度变粗；原 JSON Repair 可细分提案。没有结论标题也能保存草稿；空响应和截断响应不能进入正常验收。
5. 仅从明确的“整题候选答案”末段提取候选，不将局部 boxed 或末尾数字当整题答案。解析不确定时保留正文并由原流程继续处理，不增加格式重解调用。候选仍进入原独立验证和集合完备性验证。
6. Critic、StepVerifier、Repair、Replanner、Finalizer 提示词和输出结构不变。尤其 Repair 仍输出 ReasoningStep JSON。原 best-effort、局部额度和预算行为保留，不夹带此前独立文本运行器的严格最终门禁。
7. Finalizer 继续返回 answer/reasoning_summary JSON，程序从 answer 字段整理最终平台输出。非证明题答案单独 boxed、多问保留全部结果；证明题保留正文，无法提取时明确失败。诊断只返回安全摘要字段。
8. `CUSTOM2_TEXT_THINKING_MODE` 仅影响文本 Solver，默认 false，default 不传参数。其他原有角色思考配置不变。原输出预算与客户端调用方式复用，不创建替代客户端。
9. 原 TextReasoningRuntime、任务账本与自然语言审核暂留历史测试，不再由 text 配置选择；其中程序检查和预算恢复等实验参数不迁移到新流程。共享 skill2 材料修改保持原状，不声称与仓库基线材料完全一致。

## Risks / Trade-offs

- 粗粒度全文提案不等同于 JSON Solver 主动选择多个 claim，A/B 差异不能只解释为标点格式。
- 原流程的审核误判、best-effort 和上下文截断风险仍存在，本次不顺带改变这些机制。
- 只标记候选不代表数学正确；模型审核和有限离线测试均不证明提分。

## Migration Plan

显式设置 CUSTOM2_SOLVER_PROTOCOL=text 运行新类；设回 json 回滚。固定模型、思考开关、材料和预算做后续真实 A/B。离线测试核对方法继承、文本接入、原策略多任务、JSON 修复与重规划、平台契约和诊断边界。

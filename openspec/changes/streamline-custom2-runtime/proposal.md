## Why

当前 custom2 状态机能够严格维护事实、任务和候选状态，但微步骤求解、全有或全无的验证、独立候选验证以及严格 final gate 消耗了大量模型调用。正式评测按单题 20 分钟计时，这种设计容易在形成完整答案前耗尽预算，最终进入 emergency finalize 或输出不够直接的结果。

## What Changes

- 保留状态机的记忆、宏任务调度、预算、失败路线和候选冲突管理能力，弱化其对每个数学微步骤的审批职责。
- 将策略节点生成的任务改为 2 至 4 个可独立完成证明阶段的宏任务，允许 Solver 单次产生多个定义、结论和候选答案。
- 引入完整草稿驱动的 `Draft -> Critique -> Repair -> Finalize` 主流程；短题可进入 `Direct Solve -> Final Audit` 快速路径。
- 将协议和依赖检查交给程序完成；LLM Verifier 聚焦数学正确性，并支持 `accept`、`repair`、`reject_route` 和部分结论保留。
- 合并常规候选验证与最终答案审查，仅在候选冲突时保留独立 CandidateVerifier。
- 将严格收口和尽力收口分离：证据完整时严格 finalize，预算临界或证明未完全闭合时仍基于最可信候选输出可判分答案。
- 使用墙钟时间预算并预留最终整理时间；限制模型 Replanner 次数，重规划时替换失败路线而不是持续追加任务。
- 压缩 Solver 上下文，避免同时重复传递完整历史和 authoritative state。

## Capabilities

### New Capabilities

- `custom2-efficient-runtime`: 定义面向限时评测的轻量状态机、宏任务求解、批量审查与修复、时间预算、受限重规划和双级收口行为。

### Modified Capabilities

无。

## Impact

- 主要影响 `reasoning_agent/custom2/` 下的状态模型、策略提示词、Solver 上下文、Verifier 协议、路由、Replanner 和 Finalizer。
- 保持 `user_agent.py`、`ReasoningAgent.__init__`、`ReasoningAgent.solve` 及返回值中的 `final_response` 平台契约不变。
- 不引入新的外部依赖，不改变平台注入 client 的调用归属。
- 需要更新 deterministic 单元测试，覆盖宏任务、部分接受、候选冲突、时间预算、replan 上限和 best-effort finalize。

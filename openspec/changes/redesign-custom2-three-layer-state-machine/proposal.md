## Why

`custom2` 当前把 Subgoal 同时作为计划、运行记忆和最终完成判断，导致任务调度、上下文注入和 final gate 互相耦合。复杂题中一旦初始 Subgoal 方向错误、状态卡住或候选答案未按协议产生，Runtime 容易出现“有推理进展但无法收敛”的失败。

## What Changes

- 将 `custom2` 的状态模型重设计为三层：Evidence Layer、Requirement Layer、Task Layer。
- Evidence Layer 只保存已经通过 verifier 的 authoritative 数学事实，包括 ProblemFact、Definition、DerivedResult、Construction、CaseResult、CandidateAnswer。
- 新增 CompletionRequirement，用独立 requirement 判断是否可以 final，不再依赖 required Subgoal 全部 done。
- 将 Subgoal 降级为动态 Task 队列，只负责“下一步做什么”，支持 split、replace、invalidate、blocked、repair、replan。
- 新增 Progress Auditor，在每次 accepted step 后检查是否推进了 requirement、是否重复、是否需要新增或废弃 task。
- 新增 Replanner，在连续 reject、无可执行 task、长期无 requirement 变化或 finalizer 失败时，只输出任务变更，不输出数学结论。
- 调整 solver / verifier / finalizer prompt 和 schema，使 solver 只能 proposal evidence 和 task intent，不能直接关闭最终完成条件。
- 保留现有平台入口 `ReasoningAgent.solve(problem, metadata) -> dict` 和 `final_response` 输出契约。

## Capabilities

### New Capabilities

- `custom2-three-layer-runtime`: 定义 `custom2` 三层状态机、独立完成条件、动态任务调度、进度审计和重规划行为。

### Modified Capabilities

- 无。

## Impact

- 影响 `reasoning_agent/custom2/` 下的 models、schemas、state_manager、context、runner、prompts、verifier 等模块。
- 影响 custom2 本地调试日志中的 state 结构，但不改变正式评测入口和返回格式。
- 需要新增 deterministic 单元测试覆盖 requirement final gate、task 调度、progress auditor、replanner 触发条件和状态不变量。
- 不引入新的外部运行依赖。

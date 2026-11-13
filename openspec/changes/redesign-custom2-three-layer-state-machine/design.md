## Context

见 `proposal.md` - Why。当前 `custom2` 的状态模型把任务、记忆和完成判断耦合在一起，导致调度层和收敛层相互拖拽。这个设计只讨论如何重构状态模型，不重新定义平台入口或输出协议。

## Goals / Non-Goals

**Goals:**
- 将权威数学证据、完成条件和任务调度分离。
- 让 final gate 只依赖完成条件，而不是依赖任务清空。
- 支持动态重规划、任务失效和局部修复。
- 保持已验证步骤可审计、可追踪、可回放。

**Non-Goals:**
- 不重写平台级 `ReasoningAgent` 接口。
- 不改变外部输入输出格式。
- 不追求一次性改造所有题型的最优策略，只保证状态模型可扩展。

## Decisions

1. **保留证据层为单向追加的权威状态。**
   - 选择原因：已验证事实需要稳定、可审计、可回放，适合做后续推理的唯一事实源。
   - 备选方案：允许任务层直接修改证据层。该方案会破坏可追溯性，也会让 verifier 变得难以判定。

2. **把完成判断抽象为独立的 Requirement 集合。**
   - 选择原因：不同题型对“完成”的定义不同，尤其是证明题、极值题、构造题和分类题，不能用统一的“任务全 done”表示。
   - 备选方案：继续用 required task/subgoal 作为 final gate。该方案实现简单，但会把调度错误放大成收敛失败。

3. **把 Subgoal 收缩成纯 Task。**
   - 选择原因：Task 只回答“下一步做什么”，可以被替换或废弃，不需要承担完成判断。
   - 备选方案：保留现有 Subgoal 多重职责并加更多标志位。该方案短期改动小，但语义会继续膨胀。

4. **将 Progress Auditor 设计成推进审计器，而不是第二个 verifier。**
   - 选择原因：auditor 关注的是“是否推进 requirement”，不是重新证明数学结论。
   - 备选方案：让 verifier 同时负责 progress check。该方案会让 verifier 过重，也会混淆数学正确性与状态推进两类判断。

5. **将 Replanner 限定为任务变更器。**
   - 选择原因：重规划只应影响任务队列，不应直接写入新数学结论，否则会绕过验证流程。
   - 备选方案：允许 replanner 直接生成新的证据。该方案会破坏证据层的权威性。

## Risks / Trade-offs

- [Risk] 任务与完成条件拆分后，状态对象会更大。 → Mitigation: 将 requirement 和 task 的摘要控制为最小必要字段，并只把高价值状态注入本轮提示词。
- [Risk] Replanner 触发过于频繁会造成任务抖动。 → Mitigation: 只在连续拒绝、无可执行任务、长期无进展等明确条件下触发。
- [Risk] Requirement 设计过细会造成规则爆炸。 → Mitigation: 先为高频题型定义少量硬约束，再按题型扩展。
- [Risk] 历史消息与运行状态分离后，模型可能丢失部分局部上下文。 → Mitigation: 将已验证步骤回灌为历史消息，同时每轮注入压缩状态摘要。

## Migration Plan

1. 先保留现有证据对象与验证器，只新增 requirement 视图。
2. 将 final gate 从任务状态迁移到 requirement 状态。
3. 将现有 Subgoal 语义收缩为 Task 语义，并逐步移除其完成判断职责。
4. 引入 Progress Auditor 与 Replanner，先在本地调试路径验证，再接回正式运行路径。
5. 完成后补充针对状态不变量、final gate 和重规划触发条件的确定性测试。

## Open Questions

- 各题型最小 requirement 集合应精确到什么粒度，后续可以在 spec 归档前继续细化。
- 是否需要把 construction / case result 进一步拆成更细的 evidence 子类，取决于后续验证器能力。

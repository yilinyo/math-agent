## 1. 状态模型与数据结构

- [x] 1.1 新增 CompletionRequirement 与 Task 的权威数据结构，明确状态、依赖、来源证据和可审计字段
- [x] 1.2 将现有 Subgoal 的职责收缩为纯 Task 语义，移除其对 final gate 的直接影响
- [x] 1.3 扩展 AgentState，增加 requirements、tasks、progress_audits、replan_records 等运行状态容器

## 2. 完成条件与任务调度

- [x] 2.1 实现题型到 completion requirements 的推断逻辑
- [x] 2.2 将 final gate 改为仅基于 requirements、candidate 冲突和无效证据判断
- [x] 2.3 实现任务选择、阻塞、失效、替换和恢复的调度逻辑
- [x] 2.4 实现无可执行任务时的自动重规划入口

## 3. 运行时审计与重规划

- [x] 3.1 实现 Progress Auditor，检查每次 accepted step 是否真正推进某个 requirement
- [x] 3.2 实现 Replanner 的任务变更输出格式，禁止其直接生成数学结论
- [x] 3.3 将连续拒绝、无新证据、长期无 requirement 变化和 finalizer 失败接入重规划触发条件
- [x] 3.4 保留并记录任务废弃、替换和重建的审计痕迹

## 4. 消息组装与上下文注入

- [x] 4.1 将已验证的推理步骤继续作为 assistant 历史回灌，保留连续推理上下文
- [x] 4.2 将 requirements、当前 task、error_memory 和压缩状态作为每轮临时 prompt 注入
- [x] 4.3 移除把压缩 state 重复追加进 messages 的做法，避免历史污染
- [x] 4.4 保证 verifier、finalizer 和 solver 的提示词分别表达各自职责边界

## 5. 验证器与不变量

- [x] 5.1 调整 step verifier，确保任务完成申请不能绕过 evidence 验证
- [x] 5.2 调整 candidate verifier 与 finalizer gate，使其只依赖权威证据和 requirements
- [x] 5.3 增加状态不变量检查，覆盖证据权威性、requirements 一致性和 task 生命周期合法性

## 6. 测试与回归

- [x] 6.1 增加 requirement final gate 的确定性单元测试
- [x] 6.2 增加 task 重规划与失效切换的单元测试
- [x] 6.3 增加消息回灌与临时状态注入的回归测试
- [x] 6.4 增加进度审计失败与重规划触发的单元测试

## Context

见 `proposal.md`。当前 custom2 已有 P/D/R/C authoritative state、CompletionRequirement、Task、错误记忆、模型 Replanner 和 Finalizer；主要问题不是缺少状态，而是路由把状态当成微步骤审批系统。每次局部 Solver 输出都进入独立数学验证，一处错误会导致整步丢弃，候选还需额外验证，最终又受全量 requirement gate 约束。

正式评测单题总时限为 20 分钟，底层 client、限流和单次超时由平台控制。Agent 能控制的是是否发起下一次调用、上下文大小、调用类型和为最终答案保留多少预算。

## Goals / Non-Goals

**Goals:**

- 保留现有状态对象和审计能力，降低重构风险。
- 将常规题的模型调用目标压缩到 5 至 8 次，复杂题也优先在预留 final 调用前收口。
- 让 Solver 每次完成宏任务或完整草稿，而不是只推进一个微小结论。
- 让 Verifier 支持部分接受和定向修复，减少有效推理被整体丢弃。
- 通过时间预算、受限 Replanner 和双级 finalize 提高可判分答案的产出率。

**Non-Goals:**

- 不删除 P/D/R/C 或把 custom2 改回无状态单轮生成。
- 不改变平台 `ReasoningAgent` 初始化、`solve` 签名或注入 client 模式。
- 不为特定题目、答案、数据索引或评测样例添加硬编码路径。
- 不保证 best-effort finalize 的证明达到 strict finalize 的同等完备度。
- 不在本次变更中引入外部数学引擎或新的第三方依赖。

## Decisions

### 1. 在现有状态上增加草稿层，而不是重写状态模型

保留 problem facts、definitions、derived results、requirements、tasks、candidates 和 error memory。新增或明确以下运行态信息：

- `execution_mode`: `direct | draft | macro`
- `solution_draft`: 当前完整解答草稿及版本
- `accepted_claims`: Verifier 明确可保留的草稿结论引用
- `repair_count`: 当前草稿已修复次数
- `model_replan_count`: 实际模型重规划次数
- `started_at`、`deadline_at`、`finalize_reserve_seconds`
- `finalize_mode`: `strict | best_effort`

P/D/R/C 继续承载可复用的结构化证据，solution draft 承载自然语言完整解答。这样 Repair 可以修改完整证明，而不需要把所有语句拆成细粒度实体。

替代方案是创建全新的简化状态类。该方案迁移成本高，容易破坏现有 invariant、trace 和测试，因此不采用。

### 2. StrategyPlanner 选择执行模式并生成宏任务

StrategyPlanner 输出增加 `execution_mode` 和最多 4 个 macro task。程序负责规范化和限制数量：

- `direct`: 选择题、填空、短计算或可一次闭合的题目；
- `draft`: 普通证明和推导题，先生成完整草稿；
- `macro`: 明显需要上下界、构造、分类讨论等多个证明阶段的题目。

宏任务 objective 必须描述可审查的阶段性成果，例如“证明通用上界并给出完整依据”，不得只描述“定义变量”或“尝试使用某方法”。

替代方案是继续使用现有 Task，仅修改 prompt。仅改 prompt 无法阻止 Planner 产生过细任务，也无法让路由识别快速路径，因此需要 schema 与程序约束共同实施。

### 3. 使用 Draft–Critique–Repair 作为主要闭环

常规流程调整为：

```text
preprocess
  -> solve_direct | solve_draft | solve_macro
  -> critique
  -> accept | repair | reject_route
  -> final_audit
  -> finalize
```

`repair` 最多执行配置次数，默认 1 次。Repair 输入包括当前草稿、有效结论、无效结论和最小修复指令，不重复注入完整历史。

`reject_route` 只用于核心方法错误，不用于局部算术或格式问题。它会记录 route fingerprint，并在尚有时间和 replan 配额时进入 Replanner。

替代方案是保留每个 ReasoningStep 的 Generate–Verify。该方案正是调用膨胀和高拒绝率来源，因此不作为主路径。

### 4. 确定性协议校验先于数学 Critique

在发起数学审查前，程序执行：

- JSON/schema 规范化；
- task、dependency 和 evidence ID 存在性；
- 重复定义、空 proposal、非法关闭任务；
- candidate 和 task 的基本状态约束。

可确定修复的协议问题通过本地规范化或一次 Solver JSON regeneration 处理，不调用数学 Verifier。数学 Critique 只评估等价变形、论证缺口、量词、上下界闭合、候选与证明一致性。

替代方案是让一个 Verifier 同时处理协议和数学问题。该方案输出复杂、容易把格式错误误判为路线错误，并浪费高价值调用。

### 5. Critique 采用部分接受协议

新增批量审查输出，核心字段包括：

```json
{
  "verdict": "accept | repair | reject_route",
  "accepted_claims": [],
  "invalid_claims": [],
  "candidate_assessment": "supported | uncertain | conflict | absent",
  "reason": "...",
  "repair_instruction": "...",
  "failed_route_summary": "..."
}
```

`accepted_claims` 只有在其依赖不包含无效 claim 时才进入 authoritative state。局部错误后的结论不自动保留。Repair 后重新审查修改部分以及依赖它的结论。

替代方案是直接让 Verifier 改写答案。Verifier 同时审查和生成会模糊职责，也不利于追踪哪些内容真正经过验证，因此改写仍由 Repair Solver 完成。

### 6. 单候选走 Final Audit，冲突候选才独立验证

当存在一个受支持或高可信候选且无 conflict 时，Final Audit 一次完成：

- 检查候选与可靠结论的一致性；
- 补齐最终答案所需的关键表达；
- 生成最终 answer 和 reasoning summary。

存在多个不等价候选时才调用 CandidateVerifier，输出选择、冲突或均不可信。这样保留冲突控制，但删除常规路径上的固定额外调用。

### 7. 双级 finalize 保证收口

保留 strict gate，但增加 best-effort gate：

- strict：必要 requirements 满足、候选一致、无 invalid/conflict authoritative evidence；
- best-effort：存在候选或可提炼结论，且无已知候选 conflict；或已经进入时间保留区间。

best-effort Finalizer 必须输出非空直接答案，并在内部基于可靠证据优先级组织关键步骤。若没有显式候选，允许从 solution draft 和 accepted claims 中提炼最可信结论。trace 记录收口模式和原因，不把“不完整”文案放入最终答案。

替代方案是在预算耗尽后才 emergency finalize。该方案无法保证仍有足够时间完成最后一次请求，因此改为提前收口。

### 8. 墙钟时间成为一级路由信号

配置提供总预算和 final reserve。默认按正式 20 分钟限制预留至少 120 秒；本地运行可通过配置覆盖。路由在每次准备发起模型调用前检查剩余时间：

- 正常区间：允许 solve、critique、repair；
- 收敛区间：禁止创建低优先级新宏任务，只允许完成当前草稿或 Final Audit；
- final reserve：禁止 Replanner 和 Repair，下一调用必须 finalize。

调用次数继续作为保险丝，但不再是唯一预算。Agent 不尝试中断平台 client 的在途请求，只控制是否启动下一次请求。

### 9. Replanner 最多两次并替换路线

模型 Replanner 默认上限为 2。每条失败路线生成规范化 fingerprint，来源包括方法摘要、关键变换和 Verifier 分类。新任务若与近期 fingerprint 高度重复，则由程序过滤。

Replan commit 时：

1. 将 blocked task 和同路线 open tasks 标为 invalid；
2. 保存仍有效的 accepted claims；
3. 用 1 至 3 个新宏任务替换失败路线；
4. 将第一个新宏任务设为下一执行任务。

达到上限后不再请求模型规划，路由改为完整草稿修复或 best-effort finalize。

### 10. Solver 上下文使用状态快照而非重复历史

Solver 请求只包含：原题、分类、Strategy Guidance、当前宏任务、可靠结论摘要、当前草稿或候选、最近失败路线、剩余预算。完整 accepted assistant JSON 不再同时保留在 `solver_history_messages` 和 runtime state 中。

只在协议 regeneration 时追加上一响应的短 excerpt。上下文构造设置每类内容的数量或字符上限，并优先保留当前路线相关证据。

### 11. Trace 保持稳定并增加效率诊断

稳定 trace 新增或调整事件：

- `execution_mode_selected`
- `macro_task_started`
- `draft_proposed`
- `critique_completed`
- `repair_started`
- `route_rejected`
- `finalize_started`，包含 `mode` 和 `reason`

trace 仅保存摘要、ID、计数和 verdict。原始模型响应继续只允许进入受配置控制的 debug trace，并受字符上限约束。

## Risks / Trade-offs

- [部分接受可能错误保留依赖无效结论的 claim] → commit 前做 claim dependency closure；依赖无效 claim 的结论一律不保留。
- [宏任务输出更长，单次错误影响范围更大] → 使用批量 Critique 和一次定向 Repair，并限制 Solver 输出结构和 max tokens。
- [best-effort finalize 可能输出证明不完备的答案] → 仅在 strict 条件不满足或时间临界时启用，优先选择无冲突且支持度最高的候选。
- [时间估算无法控制已发出的慢请求] → 提前设置 final reserve，并在每次调用前而非调用后做路由判断。
- [路线 fingerprint 过强可能误杀合理修复] → fingerprint 只过滤核心方法和关键错误均相同的任务，局部修复不视为重复路线。
- [迁移期间新旧步骤协议并存增加复杂度] → 先增加兼容适配层和 feature flag，测试稳定后再删除微步骤默认路径。

## Migration Plan

1. 在现有状态模型中增加草稿、执行模式、时间预算和 replan 计数字段，保留旧字段默认值和 JSON 可序列化行为。
2. 增加宏任务和 Critique schema，并为旧 ReasoningStep 提供转换适配，使测试可分阶段迁移。
3. 实现时间路由、strict/best-effort gate 和 Final Audit，但先通过配置开关启用新流程。
4. 更新 Strategy、Solver、Verifier、Replanner 和 Finalizer prompt，启用 direct/draft/macro 三种路径。
5. 增加确定性测试和平台 contract 回归；用本地输出比较调用数、拒绝率、replan 数和收口模式。
6. 新流程稳定后设为 custom2 默认；保留旧流程开关用于一次版本周期的回滚。

回滚时关闭新流程 feature flag，恢复旧 route 和 step verifier；新增状态字段保留但不参与路由，不需要迁移已有持久化数据。

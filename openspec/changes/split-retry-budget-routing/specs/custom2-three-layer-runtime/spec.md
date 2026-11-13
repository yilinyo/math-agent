## ADDED Requirements

### Requirement: 协议失败必须与数学拒绝分流
系统 MUST 将 HTTP 400、空响应、JSON 解析失败和 schema 校验失败识别为协议失败或传输失败，而不是数学推理拒绝。此类失败 MUST 不增加 `local_retry_count`，且系统 MUST 以纠错重试消息或调度动作处理，而不是记入数学 `error_memory` 作为局部推理错误。

#### Scenario: 解析失败需要纠错重试
- **WHEN** Solver 返回的内容无法解析为合法 JSON
- **THEN** 系统 MUST 发送面向当前协议的纠错重试消息，并继续当前任务或触发重规划
- **AND** MUST NOT 将该失败计入数学局部拒绝次数

#### Scenario: HTTP 400 不算数学拒绝
- **WHEN** 模型请求返回 HTTP 400 或等价的协议层错误
- **THEN** 系统 MUST 将其视为协议失败并记录为调度信号
- **AND** MUST NOT 将其当作 StepVerifier 的逻辑拒绝处理

### Requirement: local_retry_count 只能统计已验证步骤的逻辑拒绝
系统 MUST 仅在 Solver 输出了合法的局部推理步骤且该步骤被 StepVerifier 拒绝时递增 `local_retry_count`。协议失败、schema 失败、空输出或请求错误 MUST NOT 递增该计数。

#### Scenario: 合法步骤被 verifier 拒绝时计数增加
- **WHEN** Solver 输出合法的 ReasoningStep JSON，但 StepVerifier 判定该步骤在逻辑、依赖或完成性上不成立
- **THEN** 系统 MUST 递增 `local_retry_count`

#### Scenario: 格式错误不触发 local retry
- **WHEN** Solver 输出的内容不是合法 ReasoningStep JSON
- **THEN** 系统 MUST NOT 递增 `local_retry_count`

### Requirement: local_retry_count 达到上限后必须先换路而不是直接终止整题
系统 MUST 将 `local_retry_count` 视为当前局部路线的连续失败信号。达到上限时，系统 MUST 优先标记当前 task 为 blocked、触发 replan、或切换到其他可执行 task；只有在不存在可执行 task 且重规划后仍无路径，或全局预算已耗尽时，才允许结束本题。

#### Scenario: 同一 task 连续数学拒绝后换路
- **WHEN** 当前 task 的合法步骤连续被 StepVerifier 拒绝且 `local_retry_count` 达到上限
- **THEN** 系统 MUST 先尝试生成 repair/replan task 或切换到其他开放 task
- **AND** MUST NOT 因此直接把整题标记为终止

#### Scenario: 无可执行任务时才允许终止
- **WHEN** 当前没有任何可执行 task，且重规划后仍没有可执行路径
- **THEN** 系统 MAY 结束本题并返回 incomplete

### Requirement: task 级协议失败必须触发调度纠偏
系统 MUST 为同一 task 维护协议失败相关的调度信号。连续协议失败达到阈值时，系统 MUST 将该 task 标记为 blocked 或 invalid，并生成 repair/replan task、降级 prompt，或切换到其他任务，而不是继续重复同一路线。

#### Scenario: 连续 schema 失败后暂停当前 task
- **WHEN** 同一 task 连续发生多次协议失败或 schema 失败
- **THEN** 系统 MUST 阻塞该 task 并触发重规划

#### Scenario: 其他任务可执行时优先切换
- **WHEN** 当前 task 出现协议失败，但仍有其他满足依赖的开放 task
- **THEN** 系统 MUST 优先切换到其他 task

### Requirement: 全局预算与局部路线预算必须独立解释
系统 MUST 保留 `solver_call_count` 作为全局模型调用预算，并将其与 `local_retry_count` 的语义分离。前者用于防止整轮推理无限调用，后者仅描述当前局部路线的可继续性；任一计数到上限时的行为 MUST 由路由策略独立决定，而不是共享同一终止语义。

#### Scenario: 全局预算耗尽时终止
- **WHEN** `solver_call_count` 达到上限
- **THEN** 系统 MUST 结束本题并返回 incomplete

#### Scenario: 局部预算耗尽时优先调度
- **WHEN** `local_retry_count` 达到上限但全局预算仍有剩余
- **THEN** 系统 MUST 优先触发换路、阻塞当前 task 或重规划

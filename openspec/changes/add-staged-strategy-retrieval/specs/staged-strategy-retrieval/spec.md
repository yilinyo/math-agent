## Purpose

为默认 custom2 staged 解题运行时提供可复用、可审计且可降级的本地策略案例检索，使其在不牺牲当前题独立推导与审核门槛的前提下利用相似题方法参考。

## ADDED Requirements

### Requirement: 一致的 staged 策略混合检索

当 staged 策略检索启用且本地资源可用时，系统 SHALL 在题目分类完成后、实际 Solver 调用前，针对原题只生成一次结构化检索 query。检索 SHALL 使用仓库公共检索语义，包括受校验的领域、目标、对象、显式约束和数学结构字段，本地 Qwen3-Embedding-0.6B 的归一化 1024 维向量，以及 `0.2 × 原题分数 + 0.8 × 结构分数` 的降序混合排名。默认返回数量 SHALL 为 Top-2，且调用方可用合法正整数覆盖。系统 SHALL 默认跳过额外的模型路线规划请求；调用方可显式启用该请求用于实验。

#### Scenario: 成功检索默认数量的策略

- **WHEN** staged runtime 已得到有效分类且策略检索启用
- **THEN** 系统在继续当前题实际 Solver 调用前检索至多两条按混合分数降序排列的策略条目，且默认不再发起模型路线规划请求

#### Scenario: 结构化 query 无效

- **WHEN** 结构化 query 缺失必需字段或不符合允许格式
- **THEN** 系统记录受限诊断，跳过案例注入，并继续既有 staged 策略与求解流程

#### Scenario: 覆盖返回数量

- **WHEN** 调用方设置合法的 staged 策略检索 Top-K
- **THEN** 系统按该值限制结果数量，同时保持相同向量协议和混合排序语义

### Requirement: 分层案例上下文与独立审核

系统 SHALL 将命中策略构造成摘要卡和完整案例卡。当前题策略生成和 emergency finalizer SHALL 只接收名称、标签、描述、适用条件和步骤组成的摘要卡；主 Solver 和压缩恢复 Solver SHALL 接收受字符上限约束的完整案例卡，完整卡额外包含 `example.problem` 与 `example.solution`。案例 SHALL 被标记为待核验的方法参考，不得作为当前题事实或结论。风险审查、目标审查、最终仲裁与答案整理 SHALL 不接收案例正文；emergency finalizer SHALL 仅将摘要作为整合线索，仍以原题、当前草稿和已审核证据决定结论。

#### Scenario: Solver 使用完整案例

- **WHEN** staged Solver 开始当前题推导且存在未裁剪的命中案例
- **THEN** 它接收完整案例并被要求核验适用条件、独立推出当前题结论，不得复制案例变量、数值或答案

#### Scenario: 案例超过上下文限制

- **WHEN** 完整案例卡超过配置的字符上限
- **THEN** 系统按排名保留完整高优先级案例，并仅在案例边界裁去低优先级案例，不截断原题、当前策略或已审核结论

#### Scenario: 审核与终局阶段隔离案例

- **WHEN** Solver 输出引用或模仿策略案例的推导
- **THEN** 审核与终局阶段只根据原题、Solver 当前输出和当前题的已审核证据判定结果，不因案例相似而自动接受

#### Scenario: emergency finalizer 获得摘要线索

- **WHEN** emergency finalizer 因 Solver 草稿缺失或不完整而启动，且存在命中策略
- **THEN** 它接收不含例题和例解的摘要卡，并只能将其作为整合方法线索，不得把摘要内容当作当前题已证明事实

### Requirement: 预算归属、资源降级与并发安全

策略 query 请求 SHALL 计入 staged runtime 的模型调用与墙钟预算；本地向量编码 SHALL 受策略检索阶段预算约束。索引、模型、向量维度、编码、资源读取或预算发生失败时，系统 SHALL 记录短诊断并继续无案例的既有 staged 流程，且最终仍返回非空结果。并发处理多题时，系统 SHALL 复用同一资源与设备匹配的 embedding 模型，并串行化本地编码，避免重复加载和并发设备执行失败。

#### Scenario: 资源或协议不可用

- **WHEN** 本地策略索引、embedding 模型或其 1024 维协议不可用
- **THEN** 系统不使用不匹配向量、不下载替代资源，并继续没有案例的 staged 解题流程

#### Scenario: 检索预算不足

- **WHEN** 发起策略 query 或编码会违反 staged 的调用、阶段或最终整理保留预算
- **THEN** 系统不发起该步骤，记录预算降级，并继续原有流程

### Requirement: 受限且可复现的 staged 检索 trace

成功检索时，稳定 trace SHALL 记录受字符上限约束的结构化 query、每条条目的 rank、id、混合分数、原题分数、结构分数，以及实际注入策略生成和 Solver 的卡片与各自截断标记。失败时 trace SHALL 记录有限的降级类别。trace SHALL 不包含 embedding 向量、完整模型响应、密钥或本地绝对路径。

#### Scenario: 检索成功可审计

- **WHEN** staged runtime 成功注入至少一个策略案例
- **THEN** trace 可以显示产生该上下文的 query、排名分数及两层实际注入卡片

#### Scenario: trace 达到上限

- **WHEN** 检索案例使 trace 事件超过允许长度
- **THEN** 系统保留 query、排名和分数，并在完整卡片边界裁去低排名案例且标记截断状态

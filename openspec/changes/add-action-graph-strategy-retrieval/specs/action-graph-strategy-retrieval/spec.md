## Purpose

为 Action Graph 提供与既有本地策略检索脚本语义一致的相似题策略案例，使规划与单动作执行能够获得受限的案例参考，同时保持题目独立推导、审核隔离和资源故障降级。

## ADDED Requirements

### Requirement: 一致的结构化混合策略检索
当启用策略检索且本地资源可用时，系统 SHALL 对当前题面生成结构化检索 query，并 SHALL 使用与 `scripts/query_strategy_with_client.py` 一致的提示词语义、输出格式校验和混合排序规则检索策略。系统 SHALL 使用本地 Qwen3-Embedding-0.6B 生成归一化的 1024 维 query 向量，并 SHALL 验证其与策略索引元数据的模型及维度一致。排序 SHALL 以原题相似度的 0.2 权重和结构化 query 相似度的 0.8 权重综合确定；返回结果 SHALL 按分数降序限制为配置的 Top-K，默认 Top-K SHALL 为 2。

#### Scenario: 生成有效的结构化 query
- **WHEN** 当前题目完成 Profile 且即将进入 Strategy/Skill Selector，并且策略检索已启用
- **THEN** 系统仅分析题目的领域、目标、对象、显式约束和数学结构，不求解题目、不生成候选方法或最终答案，并使用经校验的 query 检索策略

#### Scenario: 结构化 query 无效
- **WHEN** 模型返回的结构化 query 缺少必需字段或不符合允许格式
- **THEN** 系统记录有界失败诊断并跳过策略案例注入，继续原有的动作图求解流程

#### Scenario: 覆盖默认 Top-K
- **WHEN** 调用方为策略检索设置合法的正整数 Top-K
- **THEN** 系统使用该值替代默认的 2，并仍按混合分数降序返回不超过该数量的策略条目

#### Scenario: embedding 协议不匹配
- **WHEN** 本地模型、索引元数据或 query 向量的维度不是 Qwen3-Embedding-0.6B 所需的 1024 维协议
- **THEN** 系统记录受控资源降级并继续不含策略案例的动作图流程，不使用不匹配的向量进行排序

### Requirement: 分层策略案例上下文
系统 SHALL 从每个命中的策略条目构造策略卡，包含策略名称、标签、描述、适用条件和步骤。Planner SHALL 只接收摘要策略卡；Executor SHALL 接收受字符上限约束的摘要策略卡以及参考例题 `example.problem` 和参考解法 `example.solution`。系统 SHALL 明确将所有策略卡标记为待核验的方法参考，而非当前题事实或已证明结论。

#### Scenario: Planner 获得摘要案例
- **WHEN** 已检索到至少一个策略条目
- **THEN** Planner 只能看到策略摘要和适用条件，并据此选择当前题的一个动作，不接收参考例题或参考解法正文

#### Scenario: Executor 获得完整案例
- **WHEN** Executor 处理一个动作节点且上下文预算允许
- **THEN** 它接收已选策略的参考例题和参考解法，并被要求先核验适用条件、独立推导当前题的数字、边界和结论，不得直接复制案例中的变量、数值或答案

#### Scenario: 案例超过上下文上限
- **WHEN** 策略卡、参考例题和参考解法的总长度超过当前节点的策略案例字符上限
- **THEN** 系统按排名保留完整的高优先级案例，并在案例边界处裁去低优先级案例，记录截断摘要且不截断当前题、当前目标或已接受结论

### Requirement: 策略案例不得改变正确性门槛
系统 SHALL 将策略案例与当前题的数学证据分离。Reflector SHALL 不接收策略案例的例题或例解，并 SHALL 只根据当前题面、当前节点输出和已接受结论决定接受、修复或否决路线。

#### Scenario: 案例与当前题相似
- **WHEN** Executor 使用一个策略案例生成节点输出
- **THEN** Reflector 不得因案例存在或结论相似而自动接受该输出，仍须核验当前题的推导和边界条件

### Requirement: 策略资源的可选降级与预算归属
策略资源、策略 query 请求和本地编码 SHALL 受 Action Graph 的开关、总调用上限、阶段时间池和墙钟预算约束。资源不存在、不可读取、加载或编码失败、或预算不足时，系统 SHALL 跳过策略案例并继续既有领域技能和通用数学流程；不得下载资源、构造替代 API 客户端或让策略检索错误阻断非空最终返回。

#### Scenario: 资源缺失或加载失败
- **WHEN** 策略索引或本地 embedding 模型不可用，或加载过程抛出受控异常
- **THEN** 系统记录资源降级事件，仍允许 Planner、Executor、Reflector 和 Finalizer 完成原有流程

#### Scenario: 策略 query 预算不足
- **WHEN** 发起结构化 query 会违反当前阶段池、总调用上限或最终整理保留窗口
- **THEN** 系统不发起该请求，记录预算降级事件，并继续不含策略案例的流程

#### Scenario: 同一进程并发检索
- **WHEN** 同一个本地 Agent 进程并发处理多道启用策略检索的题目
- **THEN** 系统复用一份与资源和设备匹配的 embedding 模型，并串行化本地向量编码，避免重复加载模型或并发 MPS 编码崩溃

### Requirement: 可审计且受限的策略检索诊断
系统 SHALL 在稳定 trace 中记录策略检索的结构化 query、命中数量、每条命中的排名、标识、混合分数、原题分数、结构分数，以及实际构造的 Planner 摘要策略卡和 Executor 完整策略卡。策略卡记录 SHALL 与实际注入内容一致，并分别保留案例裁剪状态。每个字段和整个事件 SHALL 受配置的 trace 字符上限约束；超限时系统 SHALL 在策略卡或案例边界处裁剪并显式标记。trace 与 debug trace SHALL 不包含 embedding 向量、完整模型响应、密钥或本地绝对路径。

#### Scenario: 成功检索策略
- **WHEN** 策略检索成功并选择一个或多个策略案例
- **THEN** trace 记录经长度限制的结构化 query、每条结果的三类分数和实际注入的 Planner/Executor 策略卡，以便复现该题的策略上下文

#### Scenario: 策略 trace 超出上限
- **WHEN** 结构化 query、结果或策略卡使单个 trace 字段或整个事件超过配置上限
- **THEN** 系统只在策略卡或案例边界处裁剪低优先级内容，保留排名、三类分数和截断标记，不截断 JSON 结构或写入 embedding 向量

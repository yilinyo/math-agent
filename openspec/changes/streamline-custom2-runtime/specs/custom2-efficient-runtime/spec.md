## Purpose

本能力用于让 custom2 在单题限时评测中保留结构化记忆、失败路线和候选冲突控制，同时减少微步骤审批、重复验证和无效重规划造成的调用浪费，稳定产出直接、完整且可独立判分的最终答案。

## ADDED Requirements

### Requirement: 状态机采用轻量调度职责
系统 SHALL 保留题目事实、策略、宏任务、可靠结论、解答草稿、候选答案、失败路线、预算和冲突状态，但不得要求每个数学微步骤都单独通过模型审批后才能继续求解。

#### Scenario: 单次求解产生多个结论
- **WHEN** Solver 在一次调用中完成当前宏任务并产生多个相互依赖的结论和候选答案
- **THEN** 系统应将它们作为同一批次交给数学审查，而不是拆成多个新的 Solver 调用

#### Scenario: 状态仍可用于修复
- **WHEN** 解答草稿被判定需要修复
- **THEN** 系统应向 Repair 提供已接受结论、失败路线、当前候选和明确修复要求

### Requirement: 策略生成有限数量的宏任务
StrategyPlanner SHALL 默认生成 2 至 4 个面向完整证明阶段或完整计算阶段的宏任务，并 SHALL 避免只做符号重命名、机械转写、未闭合猜想或单一微小操作的任务。

#### Scenario: 证明型题目生成宏任务
- **WHEN** 题目需要上下界、构造或多阶段证明
- **THEN** 策略应按可独立审查的证明阶段生成宏任务，并允许单个宏任务包含多个推导结论

#### Scenario: 短题进入快速路径
- **WHEN** 分类和策略判断题目可通过一次完整求解形成候选答案及必要依据
- **THEN** 系统应选择 Direct Solve 路径，不得强制创建多个宏任务

### Requirement: Solver 优先形成完整草稿或完整证明段
Solver SHALL 尽可能完成整个当前宏任务，并 MAY 在一次输出中提交多个定义、推导结果、任务关闭申请和候选答案。Solver SHALL 在能够形成完整解答时直接提交完整草稿，不得为了满足步骤协议而刻意缩小推理粒度。

#### Scenario: 当前宏任务可一次完成
- **WHEN** Solver 已具备完成当前宏任务所需的题目事实、策略和可靠结论
- **THEN** Solver 应输出可独立审查的完整证明段并申请关闭宏任务

#### Scenario: 已可形成最终答案
- **WHEN** Solver 在完成宏任务时已得到受支持的最终候选
- **THEN** Solver 应同时提交候选和完整解答草稿，使系统能够进入最终审查

### Requirement: 验证支持批量审查和部分接受
数学 Verifier SHALL 对完整草稿或证明段进行批量审查，并 SHALL 区分 `accept`、`repair` 和 `reject_route`。当输出中同时存在有效与无效内容时，Verifier SHALL 标识可保留内容和待修复内容，不得默认丢弃整个批次。

#### Scenario: 局部错误不抹除有效结论
- **WHEN** 草稿中的前置推导正确但后续代数步骤存在可局部修复的错误
- **THEN** Verifier 应返回 `repair`，列出可保留结论和最小修复要求

#### Scenario: 核心路线无效
- **WHEN** 草稿依赖错误等价、循环论证或已重复失败的核心方法
- **THEN** Verifier 应返回 `reject_route` 并提供可记录的失败路线摘要

#### Scenario: 协议错误由程序处理
- **WHEN** 输出仅存在 JSON、标识符、依赖引用或任务状态协议错误
- **THEN** 系统应优先通过确定性程序检查处理，不得为纯协议问题消耗一次数学 Verifier 调用

### Requirement: 修复流程复用有效工作
系统 SHALL 在 `repair` 后创建定向修复请求，复用已接受结论和当前草稿，并 SHALL 避免要求 Solver 从原题重新开始。单个草稿的定向 Repair 次数 SHALL 受到配置上限约束。

#### Scenario: 定向修复代数缺口
- **WHEN** Verifier 已指出一个局部代数错误并接受此前结论
- **THEN** Repair 请求应只要求替换错误部分并重新闭合候选答案

#### Scenario: 修复次数耗尽
- **WHEN** 同一草稿达到 Repair 上限仍未通过
- **THEN** 系统应根据剩余时间进入受限重规划或尽力收口，不得无限重试

### Requirement: 候选验证与最终审查合并
当不存在相互冲突的候选答案时，系统 SHALL 使用一次最终答案审查完成候选一致性检查、必要修复和最终文本生成；只有存在多个实质冲突候选时，系统才 SHALL 调用独立 CandidateVerifier。

#### Scenario: 单一受支持候选
- **WHEN** 状态中只有一个受支持候选且不存在 conflict
- **THEN** 路由应直接进入最终答案审查，不得先进行独立候选验证

#### Scenario: 多个冲突候选
- **WHEN** 状态中存在两个或以上不等价的候选答案
- **THEN** 系统应先执行候选冲突验证，再选择或修复最终候选

### Requirement: 系统支持严格收口和尽力收口
系统 SHALL 提供 strict finalize 和 best-effort finalize 两级收口。strict finalize 用于必要证据均已满足的情况；best-effort finalize 用于存在最可信候选但证明未完全闭合、调用预算临界或剩余时间不足的情况。两种收口均 SHALL 返回非空、直接且可独立判分的 `final_response`。

#### Scenario: 证据完整时严格收口
- **WHEN** 必要完成条件已满足、候选一致且无无效 authoritative evidence
- **THEN** 系统应进入 strict finalize 并输出完整答案

#### Scenario: 时间不足时尽力收口
- **WHEN** 剩余时间低于最终整理保留阈值且状态中存在候选或可提炼的结论
- **THEN** 系统应停止新建求解与重规划调用，进入 best-effort finalize

#### Scenario: 证明未完全闭合
- **WHEN** 候选具有部分可靠支持但仍有未满足的非冲突完成条件
- **THEN** Finalizer 应基于最可信证据补全可合理补全的关键步骤并输出直接答案，不得返回 `incomplete`、`unknown` 或空字符串

### Requirement: 路由使用墙钟时间并预留最终调用
系统 SHALL 跟踪单题已用墙钟时间和估算剩余时间，并 SHALL 为至少一次最终答案整理调用预留时间。时间进入收口区间后，路由不得再启动新的 Replanner 或低优先级宏任务。

#### Scenario: 正常求解区间
- **WHEN** 剩余时间高于收口保留阈值
- **THEN** 路由可继续执行宏任务、批量审查或定向修复

#### Scenario: 进入收口区间
- **WHEN** 剩余时间达到或低于收口保留阈值
- **THEN** 下一模型调用应为最终审查或尽力收口调用

### Requirement: 重规划受限且替换失败路线
模型 Replanner 的调用次数 SHALL 受每题配置上限约束，默认不得超过 2 次。重规划成功时，系统 SHALL 失效被拒路线及其重复任务，并将新宏任务置为下一执行目标，而不是持续向旧任务队列追加同类任务。

#### Scenario: 第二次数学拒绝触发换路
- **WHEN** 同一宏任务经过一次定向修复后再次因核心数学路线错误被拒
- **THEN** 系统应记录失败路线并允许一次模型重规划

#### Scenario: 达到重规划上限
- **WHEN** 模型 Replanner 已达到每题上限
- **THEN** 系统不得再次调用 Replanner，并应选择现有最可信路线进行完整草稿修复或尽力收口

#### Scenario: 新路线替换旧路线
- **WHEN** Replanner 返回有效新宏任务
- **THEN** 与失败路线等价的旧任务应被标记为不可执行，且下一次 Solver 调用应执行新宏任务

### Requirement: Solver 上下文避免重复历史
Solver 上下文 SHALL 包含原题、当前策略、当前宏任务、关键可靠结论、当前候选、最近失败路线和预算信息，并 SHALL 避免同时重复传递完整历史消息和同内容的 authoritative state。

#### Scenario: 已接受步骤进入摘要
- **WHEN** 一个证明段已被接受并写入状态
- **THEN** 后续 Solver 应读取其结构化摘要，不得再次接收相同内容的完整历史响应副本

### Requirement: 平台接口和审计输出保持兼容
改造后系统 MUST 保持平台初始化和 `solve(problem, metadata)` 调用契约，并 SHALL 返回包含非空字符串 `final_response` 的 JSON 可序列化字典。稳定 trace SHALL 记录执行模式、宏任务、审查结论、修复、重规划和收口类型，但不得暴露完整提示词、原始模型响应、密钥或本地路径。

#### Scenario: 平台调用兼容
- **WHEN** 平台使用注入 client 初始化 `ReasoningAgent` 并调用 `solve`
- **THEN** 系统应在不构造替代 client 的情况下返回合法结果字典

#### Scenario: 尽力收口可审计
- **WHEN** 系统使用 best-effort finalize
- **THEN** trace 应记录收口原因和使用的候选标识，但不得包含原始 prompt 或完整模型响应

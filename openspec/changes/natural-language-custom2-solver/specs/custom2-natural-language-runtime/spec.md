## Purpose

将 Solver 自然语言回答接入原 JSON ReasoningRuntime，不把回答格式与策略、任务规划或其他角色协议绑定。

## ADDED Requirements

### Requirement: 原调度复用与兼容开关
系统 SHALL 通过新的继承运行器实现 text，仅改变 Solver 调用和文本接入，非 Solver 方法和 JSON 默认保持原样。

#### Scenario: 切换 Solver 协议
- **WHEN** CUSTOM2_SOLVER_PROTOCOL 为 text
- **THEN** 入口选择 SolverTextReasoningRuntime，不运行旧独立 TextReasoningRuntime

#### Scenario: 原策略选择任务范围
- **WHEN** 原策略选择 direct、draft 或 macro
- **THEN** 新运行器沿用原任务和调度，不强制固定任务数量，也不因 text 跳过策略

### Requirement: 自然语言提案接入
系统 SHALL 保存完整 Solver 文本并程序化包装当前任务的待审核提案，不要求模型填写状态字段，不新增结构化转换模型调用，不自动提交结果。

#### Scenario: 普通推导没有格式字段
- **WHEN** Solver 返回无 JSON、无 boxed、无结论标题的完整数学正文
- **THEN** 原文进入当前任务审核，不触发 ReasoningStep JSON repair

#### Scenario: 文本尚未经过审核
- **WHEN** 程序已生成待审核提案
- **THEN** authoritative 结果和任务状态保持不变，须经过原审核与提交机制才能接受

#### Scenario: 输出为空或截断
- **WHEN** Solver 返回空文本或 finish_reason 为 length
- **THEN** 系统记录响应问题并回到原失败调度，不把残缺正文作为已验证结论

### Requirement: 非 Solver 角色保留 JSON
系统 SHALL 继续使用原分类、形式化、策略、Critic、StepVerifier、Repair、Replanner、候选验证及 Finalizer 的 JSON 协议和方法。

#### Scenario: 审核要求修复
- **WHEN** JSON Critic 返回 repair
- **THEN** 原 Repair 输出 ReasoningStep JSON，原审核及提交逻辑处理修复结果

#### Scenario: 路线需要调整
- **WHEN** 原调度要求重规划
- **THEN** 原 Replanner 生成 ReplanOutput JSON，保留原路线额度与时间约束

### Requirement: 候选与最终输出边界
系统 SHALL 将候选与最终平台答案分开，局部结果不直接成为整题答案；Finalizer 保持 JSON，由程序整理最终 answer 字段。

#### Scenario: 子任务出现 boxed
- **WHEN** Solver 的局部结果包含 boxed 或未标记数字
- **THEN** 程序不据此自动注册整题候选，不直接提交平台

#### Scenario: 明确整题候选
- **WHEN** Solver 在整题候选答案段给出完整结果
- **THEN** 程序保守提取并交给原候选审核，多问不只取最后一项

#### Scenario: 最终结果与证明
- **WHEN** JSON Finalizer 已生成 answer 字段
- **THEN** 非证明题返回仅 boxed 的全部最终结果，证明题保留证明正文，无法提取时明确失败

### Requirement: 平台契约与安全诊断
系统 SHALL 使用注入客户端，保持初始化与 solve 接口，返回 JSON 可序列化且 final_response 为非空字符串的字典，公开 debug 不包含原始模型响应、提示词或隐藏答案。

#### Scenario: 最小平台客户端
- **WHEN** 客户端仅接受 messages、temperature 和 max_tokens
- **THEN** 系统正常调用原客户端包装，不创建替代客户端，不读取参考答案求解

#### Scenario: 独立思考配置
- **WHEN** 调整 CUSTOM2_TEXT_THINKING_MODE
- **THEN** 仅文本 Solver 的思考参数改变，其他 JSON 角色保持原设置

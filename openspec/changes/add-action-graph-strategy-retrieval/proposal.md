## Why

Action Graph 目前只使用模型选择的领域技能章节，缺少可复用的相似题策略和完整示例来帮助弱模型将抽象方法落到当前动作。仓库已具备本地 `strategy_data` 索引及结构化混合检索脚本，应在不破坏动作图预算、安全边界和独立数学审核的前提下接入。

## What Changes

- 为 `custom2_action` 增加可配置的本地策略案例检索，默认使用 `strategy_data` 返回 Top-2 策略条目。
- 结构化检索 query 的提示词、字段校验、embedding 查询及 `0.2 × 原题分数 + 0.8 × 结构分数` 的排序语义 SHALL 与 `scripts/query_strategy_with_client.py` 一致。
- 使用本地 Qwen3-Embedding-0.6B 生成归一化的 1024 维 query 向量，并与策略索引元数据及脚本的模型、维度和向量协议一致。
- 将命中条目整理为两种受限策略卡：Planner 接收不含示例正文的摘要卡；Executor 接收受总字符限制的摘要、`example.problem` 和 `example.solution`，并明确它们仅为待核验的方法参考。
- Reflector 不接收策略案例，继续仅依据当前题面、当前节点输出和已接受结论判断正确性。
- 在稳定 trace 中记录经过字段和总长度限制的结构化 query、每条检索结果的排名及三类分数，以及实际构造并注入 Planner/Executor 的策略卡，便于本地评测定位检索质量和案例使用情况。
- 资源缺失、模型加载失败、结构化 query 无效或检索失败时，运行时 SHALL 记录有界诊断并继续使用既有 `skill2` 材料，不得阻断单题求解、下载资源或创建替代 API 客户端。

## Capabilities

### New Capabilities

- `action-graph-strategy-retrieval`: 定义 Action Graph 中本地策略案例的检索、上下文分层注入、预算约束、降级与可观察性行为。

### Modified Capabilities

无。

## Impact

- 影响 `reasoning_agent/action_graph/` 的状态、配置、运行时、提示词和测试，以及 `reasoning_agent/strategy_retrieval.py` 的可复用接口。
- 复用仓库内的 `strategy_data/`、`strategyrag/` 和注入 client；不改变 `user_agent.py`、`ReasoningAgent` 或默认 `custom2_staged` 模式。
- 会增加一次受 Action Graph 统一预算控制的结构化 query 调用及本地 embedding 编码；策略资源必须作为可选本地资源处理。

## Why

`custom2_staged` 目前只使用模型生成的策略和既有 skill 材料，无法复用仓库内 `strategy_data` 中经过验证的相似题策略案例。Action Graph 已接入同一批资源，staged runtime 需要获得等价的检索能力，同时不能让案例正文干扰独立审核或改变平台接口。

## What Changes

- 为默认 `custom2_staged` 运行时增加可配置的本地策略案例检索，默认返回 Top-2。
- 复用 `reasoning_agent.strategy_retrieval` 的结构化 query、Qwen3-Embedding-0.6B 1024 维协议及 `0.2 × 原题分数 + 0.8 × 结构分数` 排序，不实现 staged 专用检索变体。
- 在分类后执行至多一次受运行时预算约束的检索，并默认直接交给 Solver；可选的模型路线规划默认关闭，缺失模型、索引、预算或 query 无效时无阻塞地回退到既有 staged 流程。
- 将摘要策略卡提供给 staged 策略选择和 emergency finalizer，完整案例卡提供给 Solver/压缩恢复；审核器和最终仲裁器不接收案例正文。
- 在稳定 trace 中记录受上限约束的结构化 query、排名与分数、实际注入的卡片及降级原因。

## Capabilities

### New Capabilities

- `staged-strategy-retrieval`: 定义 custom2 staged runtime 的本地策略案例检索、分层上下文注入、预算降级和可审计行为。

### Modified Capabilities

无。

## Impact

- 影响 `reasoning_agent/custom2/staged_runtime.py`、其配置及 staged runtime 测试。
- 复用现有 `reasoning_agent/strategy_retrieval.py`、策略卡渲染能力和可选的本地 `strategy_data/` 资源，不修改 `user_agent.py`、注入 client 合约或默认外部依赖。

## Context

参见 proposal.md。现有 Action Graph 已将模型前置职责拆分为题面预处理、Profile 和 Strategy/Skill Selector 三步，并在 Executor 节点注入来自 `skill2` 的通用方法材料；当前的 `_bootstrap` 仅是串联这些步骤的 Runtime 外层方法。仓库另有 `StrategyRetriever` 与 `scripts/query_strategy_with_client.py`：前者在本地 `strategy_data` 上执行向量检索，后者定义了结构化 query 的模型提示词及混合排序用法。

策略检索需要额外一次模型调用和本地 Qwen3-Embedding-0.6B 编码；策略索引为归一化的 1024 维向量。Action Graph 的现有 `retrieve_for_problem(client, ...)` 直接调用 client，不能绕过 Runtime 的墙钟预算、调用计数和阶段池。

## Goals / Non-Goals

**Goals:**

- 使策略 query 与现有脚本的提示词、校验和 0.2/0.8 排序完全对齐。
- 将相似题的完整 worked example 仅在 Executor 层受限注入，并保持 Reflector 独立。
- 对缺少索引或 embedding 模型的环境提供无阻塞降级。

**Non-Goals:**

- 不改变默认 mode，不让策略案例成为当前题答案或证明的来源。
- 不在求解期间下载模型、构建索引或调用外部向量服务。
- 不为每次 repair 或每个节点重复检索同一原题。

## Decisions

### 1. 在 Profile 后、Strategy/Skill Selector 前检索一次，并复用检索结果

Runtime 在 Profile 后、Strategy/Skill Selector 前对当前 source packet 执行一次策略检索。默认 Top-K 为 2，且通过独立 `action_*` 配置允许正整数覆盖。结果存入每题独立状态：结构化 query、排名结果、摘要策略卡和完整 Executor 策略卡。Strategy/Skill Selector 从摘要卡选择首动作；所有 Executor 节点复用同一检索结果。

这比每节点检索更节省模型调用和 embedding 计算，也避免 repair 因原题未变而得到相同案例。拒绝路线后的方法变化由既有 failure memory、动作选择和 `skill2` 章节检索处理。

### 2. 复用脚本的检索语义，但通过 Runtime 发起 query 调用

结构化 query 请求直接复用 `build_structure_messages(problem)` 和 `normalize_retrieval_text`，随后以本地 Qwen3-Embedding-0.6B 的归一化 1024 维向量复用 `retrieve_hybrid(raw_problem, retrieval_text, top_k)`。在编码前或加载索引时校验模型标识和 `embedding_dim=1024`，不匹配则降级。为使模型调用受同一预算控制，Runtime 使用现有调用包装发送该 messages，而不是调用会直接执行 `client.chat()` 的便利方法。提示词文本、字段要求、embedding 查询及混合权重不产生 Action Graph 专用变体。

备选方案是直接调用 `retrieve_for_problem`。它虽然代码更短，却会绕过 Runtime 的 timeout、调用计数、阶段池和 trace，故不采用。

### 3. 策略卡按 Planner/Executor 分层

每个结果被转为两种视图：

```text
Planner card = name + tags + description + applicability + steps
Executor card = Planner card + example.problem + example.solution
```

Planner 不接收完整例题和例解，减少其把案例答案误当成当前题路线的机会。Executor 可以借完整案例学习推导形态，但提示词把案例置于不可信边界块，并要求逐项验证适用条件以及独立推出当前题结论。Top-K 默认应较小；先在卡边界处裁去低排名案例，再对单条案例使用明确字段级上限，避免破坏原题或 accepted memory 的完整性。

### 4. 案例不进入 Reflector

Reflector 的上下文维持当前题、节点目标、节点输出和已接受结论。案例材料不传入审核阶段，确保“案例解法相似”不能被当作当前题的正确性证据。

### 5. 资源和故障为可选能力

策略检索的导入、索引读取和 embedding 模型加载均懒执行并包在受控降级边界内。配置提供启用开关、Top-K、策略卡总字符上限及单独的策略检索阶段池。失败只产生短 trace 事件，继续原有 `skill2` 检索和动作路线。每个 solve 建立独立检索状态，避免并发题目共享可变结果。

embedding 模型和只读索引按资源路径与设备在进程内共享；它们不是题目级状态。共享 retriever 用锁覆盖模型首次加载和每次 query 编码，避免多个 local-runner 线程同时向 MPS 提交 SentenceTransformer 工作而触发 Metal command-buffer 断言。网络模型调用、Planner 与 Executor 不受该锁限制，仍可按 `LOCAL_MAX_CONCURRENCY` 并行。

### 6. Trace 记录实际检索与实际注入的策略卡

成功路径写入一个稳定的 `strategy_retrieval_completed` 事件。事件至少包含经上限裁剪的 `retrieval_text`、`results`（`rank`、`id`、`score`、`raw_score`、`structure_score`）以及 `planner_cards` 和 `executor_cards`。后两者是实际传给相应角色的卡片文本/字段，而不是重新从元数据构造的另一份展示内容；因此 Executor 卡会包含受限的 `example.problem` 和 `example.solution`。

Trace 使用现有的单字段和单事件上限：优先保留结构化 query、排名与三类分数，再按排名保留完整卡片；空间不足时仅在卡片边界丢弃低排名卡，并分别写入 `planner_cards_truncated`、`executor_cards_truncated`。embedding 向量、完整模型响应、密钥与本地绝对路径始终不写入 trace。

## Risks / Trade-offs

- [示例答案锚定或误迁移] → 只让 Executor 接收完整案例，明确独立核验规则，并由不含案例的 Reflector 审核。
- [额外模型调用挤占预算] → 前置流程中仅检索一次、独立阶段池、最终整理保留窗口和预算不足时跳过。
- [1.6GB 本地 embedding 模型在评测环境缺失或内存压力过高] → 懒加载、可配置关闭、失败无阻塞降级；不在运行期下载。
- [案例文本耗尽上下文] → 小 Top-K、卡边界裁剪、单独字符上限，并优先保留题面与当前节点证据。
- [检索实现随脚本漂移] → 将结构化 query 构造、校验和混合排序公共化；测试直接比较 Runtime 使用路径与脚本基准输出。
- [完整案例使 trace 过大] → 记录实际注入但受字段/事件上限约束的卡片，在卡片边界裁剪低排名内容并显式标记。

## Migration Plan

1. 提取或确认可由 Runtime 调用的公共检索接口，并为其添加不触发直接 client 调用的测试。
2. 新增 Action Graph 配置、每题状态和 Profile 后的受控检索调用；资源或预算异常先验证降级。
3. 将卡片分层接入 Strategy/Skill Selector、Executor 和 trace，保持 Reflector 输入不变。
4. 以模拟 client、伪 embedding/retriever 和临时策略资源执行单元及运行时集成测试；再在本地样例上做非提交式比较。
5. 回滚只需关闭策略检索开关或停止选择该策略资源；既有 Action Graph、`skill2` 和默认运行时无需迁移。

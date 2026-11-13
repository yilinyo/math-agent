## Context

`custom2_staged` 已有分类、策略生成、主 Solver、压缩恢复、多类审查和最终仲裁流程，但没有本地案例检索状态。Action Graph 已将公共检索语义、进程内 embedding 缓存、串行编码和策略卡渲染抽离为可复用组件；staged runtime 需要使用这些组件而不是复制索引加载或结构化 query 提示词。

## Goals / Non-Goals

**Goals:**

- 让 staged runtime 获得与脚本和 Action Graph 一致的一次性策略检索结果。
- 保持检索调用、时间与资源错误都归属 staged runtime 自身预算，并保留无阻塞降级。
- 以较小的分层上下文增强策略生成和解题，不改变审查、终局整合或平台 client 合约。

**Non-Goals:**

- 不将 Action Graph 的 action、节点、反思循环或温度策略迁移到 staged runtime。
- 不在每次重试、审查或恢复时重新检索同一题，不在线下载模型或索引。
- 不让案例成为答案、已审核证据或 judge 专用规则。

## Decisions

### 1. 检索位置为分类之后、实际 Solver 之前

分类给出领域画像后，runtime 调用公共结构化 query messages；完成本地混合检索后，将结果保存为单题状态并供后续所有阶段复用。默认直接将检索卡提供给 Solver，避免额外模型路线规划请求在服务端延迟时挤占实际解题时间；可选实验开关恢复该请求。这个位置避免在每次 Solver 恢复中重复耗费模型调用或 embedding 编码。

### 2. 用 Runtime 包装发送 query，复用公共检索的其余语义

结构化 query 通过 staged runtime 的现有 model-call 包装发送，以便保留调用计数、超时与 trace 约束；随后使用公共 `normalize_retrieval_text` 和共享 retriever 进行索引验证、编码和混合排序。直接使用方便接口会绕过 staged 预算；复制脚本会让提示词和排序实现漂移，因此均不采用。

### 3. 可选策略阶段用摘要，Solver 用完整案例，审查和终局完全隔离

若显式启用模型策略规划，它仅获摘要卡，以降低案例答案锚定；默认跳过该调用。主 Solver 和压缩恢复 Solver 始终获完整卡，并在 user-message 不可信边界内明确独立验证要求。emergency finalizer 获得同一份摘要卡，帮助它在时间不足时理解已有草稿应沿何种方法整合，但提示词限制其只能依据原题、草稿和已审核证据作结论。审查器、仲裁器和最终整理器不接收案例，从而使接受门槛仅依赖当前题证据。卡片按排名、完整案例边界裁剪，优先保护题面与已审核材料。

### 4. staged 配置独立命名，默认保守且可关闭

新增 `staged_strategy_retrieval_*` 配置，包括开关、Top-K、模型 query token/timeout、阶段预算、卡片大小和 trace 限制。默认启用、Top-K 为 2，与 Action Graph 的资源协议一致；预算不足或任意受控错误时仅写降级 trace 并继续。这样实验可独立关闭，也不会影响其他 `custom2` runtime。

### 5. 使用共享 embedding retriever 串行化本地编码

staged 与 Action Graph 使用同一按数据路径、模型路径和设备缓存的 retriever，编码持有内部锁。它避免 macOS MPS 并发编码导致的 command-buffer 失败，同时不锁住网络模型调用或 staged 的其它求解阶段。

## Risks / Trade-offs

- [完整案例锚定 Solver] → 只在 Solver 层提供案例、要求独立核验，并由无案例审查器判定。
- [检索多占一次模型调用与本地加载时间] → 只执行一次、专用阶段预算、最终保留窗口和可关闭降级。
- [策略卡挤占 Solver 上下文] → 小 Top-K、完整卡边界裁剪并保留原题和当前策略优先级。
- [共享模型仍造成资源压力] → 懒加载、单例缓存和编码锁；资源不可用时继续无案例流程。
- [trace 过大或泄漏内部信息] → 记录受限文本和分数，不记录向量、完整响应、密钥或绝对路径。

## Migration Plan

1. 为 staged config、单题状态和调用包装添加检索预算与温度配置。
2. 将一次性检索接入分类与策略生成之间，并把分层卡片接入策略/Solver 提示词。
3. 保持审查和终局提示词不变，增加 trace 与可控降级。
4. 使用模拟 client、临时 retriever 及并发测试验证，并在本地样例比较启用和关闭状态。
5. 回滚只需关闭 staged 策略检索开关；既有 staged 流程和外部接口不迁移。

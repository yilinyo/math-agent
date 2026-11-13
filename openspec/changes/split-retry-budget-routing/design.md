## Context

见 `proposal.md - Why`。当前 `custom2` 已经有三层状态机，但全局调用预算和局部路线预算的终止语义仍然耦合，导致协议失败容易把任务卡在同一路线。

## Goals / Non-Goals

**Goals:**
- 把协议/传输失败与数学拒绝分开计数。
- 让 `local_retry_count` 只描述当前路线是否还值得继续。
- 让局部失败优先驱动换 task、blocked、repair 和 replan。
- 保持 `solver_call_count` 作为全局上限，不改变平台返回契约。

**Non-Goals:**
- 不重写三层状态机本身。
- 不修改平台入口、模型客户端接口或 `final_response` 格式。
- 不引入新的外部依赖。

## Decisions

1. **保留两个预算维度，但语义分离**
   - `solver_call_count` 继续作为全局尝试上限，避免无限重试。
   - `local_retry_count` 改成局部路线健康度指标，只对合法步骤被 verifier 拒绝时增长。
   - 备选方案是把所有失败都并到 task 统计里，但会失去全局终止保护，不利于稳定性。

2. **协议失败不进入数学 error_memory**
   - JSON/schema/HTTP 失败的根因通常在 prompt、格式或传输层，不是数学内容本身。
   - 这类失败更适合进入调度层，通过 retry message、task blocked 或 replan 处理。
   - 备选方案是继续写入 error_memory，但会污染后续数学上下文，并误导 verifier。

3. **局部失败达到阈值后先换路**
   - 局部预算用尽时，优先阻塞当前 task，再尝试其他可执行 task。
   - 只有没有可执行任务、重规划也无路可走或全局预算耗尽时，才终止整题。
   - 备选方案是沿用当前的直接 incomplete，但会过早结束可恢复的题目。

4. **任务级协议失败单独记录**
   - 同一 task 连续 schema/HTTP 失败时，说明这条 task 的当前 prompt 形态或粒度不适合继续。
   - 需要一个任务级失败信号去驱动降级 prompt 或重规划，而不是重复同样请求。
   - 备选方案是只依赖 `solver_call_count`，但它只能统计消耗，不能表达“该 task 已坏”。

5. **通用 JSON 纠错模板复用**
   - 各环节的无效 JSON 修复都使用同一类通用构造器，再由调用方传入协议名和 schema 约束。
   - 这样可以避免 custom / custom2 各自维护一套硬编码提示，降低分叉风险。

## Risks / Trade-offs

- [Risk] 局部失败分流后，调度逻辑更复杂。→ [Mitigation] 通过 deterministic 测试覆盖 route、replan 和 budget 边界。
- [Risk] 过度切换 task 可能降低连续推理的上下文质量。→ [Mitigation] 仅在连续失败达到阈值后才切换，并保留已验证历史。
- [Risk] 协议失败与数学失败的界线不总是绝对清晰。→ [Mitigation] 以“是否得到合法可验证步骤”为界，格式问题优先走调度分流。

## Migration Plan

1. 先把协议失败纠错消息统一到共享模板。
2. 再把 `local_retry_count` 的递增条件收紧为 verifier reject。
3. 然后在路由层加入 task 级 blocked / replan 逻辑。
4. 最后补充针对 HTTP 400、JSON/schema 失败和连续 verifier reject 的回归测试。

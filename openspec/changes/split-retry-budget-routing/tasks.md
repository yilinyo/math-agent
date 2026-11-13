## 1. 失败语义与状态建模

- [x] 1.1 为 `custom2` 补充 task 级协议失败或路线失败的状态字段，明确区分数学拒绝、协议失败和全局预算。
- [x] 1.2 收紧 `local_retry_count` 的递增条件，只在合法步骤被 StepVerifier 拒绝时递增。
- [x] 1.3 保留 `solver_call_count` 作为全局调用预算，并确保其终止语义与 `local_retry_count` 分离。

## 2. 路由与重规划

- [x] 2.1 调整 `route()`，使局部预算耗尽时优先触发换 task、blocked 或 replan，而不是直接终止整题。
- [x] 2.2 为同一 task 的连续协议失败增加调度信号，并在阈值达到时阻塞当前 task 或生成 repair/replan task。
- [x] 2.3 确保在仍有可执行 task 时，局部失败不会把整个运行提前标记为 incomplete。

## 3. 通用 JSON 纠错消息

- [x] 3.1 抽出通用 JSON 纠错消息构造器，支持传入协议名、错误信息、允许格式和额外约束。
- [x] 3.2 将 `custom` 和 `custom2` 的无效 JSON 重试消息接入共享构造器，保留各自协议的 schema 约束。

## 4. 回归测试

- [x] 4.1 增加测试覆盖 HTTP 400 / JSON / schema 失败不会递增 `local_retry_count`。
- [x] 4.2 增加测试覆盖合法步骤被 verifier 拒绝时 `local_retry_count` 会递增。
- [x] 4.3 增加测试覆盖 `local_retry_count` 达到上限时优先换路或重规划，而不是立即结束整题。
- [x] 4.4 增加测试覆盖通用 JSON 纠错消息在 `custom` 与 `custom2` 两侧都可复用。

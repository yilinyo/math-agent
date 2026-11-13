## Why

`custom2` 当前把协议失败、JSON/schema 失败和数学推理拒绝混在同一条重试路径里，导致模型在同一 task 上反复原地打转。`local_retry_count` 现在更像“当前路线是否还值得继续”的信号，而不是整题终止条件，需要把它和全局调用预算、task 级重规划分开。

## What Changes

- 将 `solver_call_count` 继续保留为全局模型调用预算，只表示总调用次数，不直接代表某条 task 是否失败。
- 将 `local_retry_count` 重新定义为当前局部路线的连续数学拒绝计数，只对 StepVerifier reject 生效，不再覆盖 HTTP 400、JSON 解析失败或 schema 失败。
- 为协议/运输/格式失败增加独立的 task 级调度信号，连续失败时触发换任务、标记 blocked、降级 prompt 或 replan，而不是继续消耗同一路线。
- 调整路由逻辑，使局部失败优先推动任务切换或重规划；只有全局预算耗尽、没有可执行任务或多次重规划仍无进展时，才结束整题。
- 保持现有重试提示词的通用化构造方式，使不同环节都能复用同一类 JSON 纠错消息模板。

## Capabilities

### Modified Capabilities
- `custom2-three-layer-runtime`: 调整局部重试计数、全局调用预算和 task 级重规划之间的行为边界，使协议失败不再直接终止整题。

## Impact

- 影响 `reasoning_agent/custom2/` 下的 `runner`、`state_manager`、`context`、`prompts` 和相关测试。
- 需要补充 task 级失败分流、重规划触发和预算耗尽行为的确定性测试。
- 不改变平台入口、返回结构或外部依赖。

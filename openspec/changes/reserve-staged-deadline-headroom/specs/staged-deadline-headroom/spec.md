## Purpose

为受 20 分钟平台硬时限约束的 staged 求解预留返回和序列化时间，避免内部模型调用占满外部时限后丢失最终响应。

## ADDED Requirements

### Requirement: Staged 外部时限安全余量
系统 SHALL 在默认 1200 秒平台时限内预留可配置且默认非零的安全余量，并以扣除余量后的时间作为 staged 内部 deadline。所有 staged 模型调用 SHALL 受该内部 deadline 约束。

#### Scenario: 默认平台时限
- **WHEN** 未覆盖 staged 时间配置
- **THEN** 内部模型调用预算 SHALL 在 1200 秒之前结束，并保留默认 300 秒用于返回结果

#### Scenario: 受限自定义预算
- **WHEN** 自定义总预算小于默认平台时限
- **THEN** 内部 deadline SHALL 不超过该自定义预算扣除适用安全余量后的值

### Requirement: 可观测的有效时间预算
系统 SHALL 在 trace 中记录配置总预算、安全余量和有效内部预算，且在预算耗尽时继续返回非空最终响应。

#### Scenario: 预算接近耗尽
- **WHEN** 求解进入内部 deadline 后的最终收尾路径
- **THEN** 系统 SHALL 不启动超出有效内部预算的模型请求，并返回可序列化结果

## 1. 检索状态、配置与预算

- [ ] 1.1 为 staged runtime 增加每题隔离的策略检索状态，保存经校验的 query、排名结果、摘要/完整卡和有界降级信息。
- [ ] 1.2 新增 `staged_strategy_retrieval_*` 配置：启用开关、默认 Top-K=2、query token/timeout、阶段预算、卡片与 trace 字符上限；将 query 调用计入 staged 模型调用、墙钟和最终保留预算。
- [ ] 1.3 在分类后、策略生成前通过 staged Runtime 调用包装发送一次公共结构化 query，并用共享 retriever 执行同一 1024 维与 0.2/0.8 混合排序检索。
- [ ] 1.4 为无效 Top-K、query 协议、资源缺失、模型/索引加载、编码、维度协议和预算不足实现不阻塞的有界降级。

## 2. 策略卡与上下文隔离

- [ ] 2.1 复用策略卡渲染器构造按案例边界裁剪的 staged 摘要卡和完整 Solver 卡，并保持实际注入文本可追踪。
- [ ] 2.2 默认跳过 staged 模型策略生成，保留显式实验开关；启用时将摘要卡加入其 user-message 不可信边界，要求其只选择当前题策略且不把案例结论视为当前题事实。
- [ ] 2.3 将完整案例卡加入主 Solver 和压缩恢复 Solver 的 user-message 不可信边界，要求先核验适用条件并独立推导当前题。
- [ ] 2.4 将摘要卡加入 emergency finalizer 的不可信 user-message 边界；验证风险审查、目标审查、最终仲裁和答案整理不接收 `example.problem`、`example.solution` 或完整案例卡。

## 3. Trace、测试与文档

- [ ] 3.1 记录 `staged_strategy_retrieval_completed` 与受控降级 trace，包含受限 query、rank/id/三类分数、两层实际注入卡片和截断标记，且不泄漏向量、密钥、绝对路径或完整模型响应。
- [ ] 3.2 添加确定性 staged runtime 测试：默认/覆盖 Top-K、调用与阶段预算、资源/协议降级、摘要与完整卡分层、审查隔离、trace 截断和单题并发状态隔离。
- [ ] 3.3 添加进程内共享 embedding retriever 的 staged 并发回归，验证编码被串行化且网络模型调用不被该锁串行化。
- [ ] 3.4 在本地样例做不提交的启用/关闭 A/B 回归，比较调用数、耗时、格式失败和结果质量；更新 README 的配置、资源前提、trace 字段和降级说明。

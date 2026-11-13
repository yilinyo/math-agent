## 1. 共享检索语义与受控接口

- [x] 1.1 整理 `reasoning_agent.strategy_retrieval` 的公共接口，使 Action Graph 能复用脚本同一份结构化 query messages、规范化校验和混合排序，而不通过直接 `client.chat()` 绕过 Runtime 调用包装。
- [x] 1.2 为结构化 query、缺字段校验、Qwen3-Embedding-0.6B 的归一化 1024 维向量协议及 0.2/0.8 混合排序添加确定性测试，并与 `scripts/query_strategy_with_client.py` 的基准行为对照。
- [x] 1.3 保持检索模块不读取密钥、不创建客户端、不下载模型或索引，并验证缺失资源抛出可由调用方降级的受控错误。

## 2. Action Graph 检索状态、预算与降级

- [x] 2.1 为 Action Graph 增加独立且每题隔离的策略检索状态，保存已校验 query、排名摘要、分层策略卡及有界降级信息。
- [x] 2.2 新增 `action_*` 策略检索配置，包括启用开关、默认值为 2 且可覆盖的 Top-K、策略案例字符上限和阶段时间池；将 query 调用接入总调用数、墙钟保留窗口和阶段预算。
- [x] 2.3 在 Profile 后、Strategy/Skill Selector 前执行至多一次策略检索；预算、资源、模型加载、编码或检索失败时记录短 trace 并无阻塞地退回既有 `skill2` 流程。
- [x] 2.4 添加模拟时钟与客户端测试，覆盖默认/覆盖 Top-K、1024 维协议不匹配、调用上限、阶段预算不足、资源缺失、加载失败及并发 `solve` 状态隔离。
- [x] 2.5 为本地并发运行复用进程级 embedding retriever，并串行化 SentenceTransformer 编码以避免重复加载模型和 MPS command-buffer 并发崩溃；添加相关回归验证。

## 3. 分层策略卡与提示词接入

- [x] 3.1 将策略元数据转为摘要卡和完整 Executor 卡：摘要包含名称、标签、描述、适用条件和步骤；完整卡额外包含 `example.problem` 与 `example.solution`，并实行案例边界裁剪。
- [x] 3.2 将摘要卡加入 Strategy/Skill Selector 的不可信 user-message 边界块，要求其只选当前题首动作且不把案例内容作为当前题结论。
- [x] 3.3 将完整策略卡加入 Executor 的不可信 user-message 边界块，要求逐项核验适用条件并独立推导当前题；确保 Reflector、Finalizer 和 accepted claim 不接收案例正文。
- [x] 3.4 添加提示词和上下文测试，验证 Planner 不含 `example.problem`/`example.solution`，Executor 在预算内获得二者，裁剪不破坏题面与已接受结论，且案例伪指令不能改变动作或输出协议。

## 4. Trace、回归与文档

- [x] 4.1 记录稳定的 `strategy_retrieval_completed` trace 事件，包含经上限裁剪的结构化 query、每条结果的 rank/id/混合分数/原题分数/结构分数，以及实际注入 Planner 和 Executor 的策略卡；保留每种卡的截断标记。
- [x] 4.2 添加 trace 截断与 JSON 安全测试，验证完整案例在允许空间内可记录、超限时仅在卡片边界裁剪低排名内容，并且不泄露 embedding 向量、完整模型响应、密钥或绝对路径。
- [x] 4.3 扩展 Action Graph 运行时回归测试，覆盖策略案例不能使 Reflector 自动接受、资源降级后仍返回非空结果，以及默认/既有模式不触发策略检索。
- [ ] 4.4 在本地样例进行非提交式回归，比较启用与关闭策略检索时的模型调用数、耗时、格式失败和结果质量，并更新 README 的配置、资源前提、trace 字段和降级说明。

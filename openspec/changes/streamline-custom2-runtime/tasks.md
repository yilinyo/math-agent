## 1. 配置、状态与协议基础

- [x] 1.1 在 custom2 配置中增加高效运行 feature flag、总时间预算、final reserve、最大 Repair 次数和最大模型 Replanner 次数，并提供兼容旧流程的默认/回滚路径
- [x] 1.2 扩展 AgentState，加入 execution mode、solution draft、accepted claims、repair count、model replan count、deadline 和 finalize mode，确保 `model_dump` 与 JSON 序列化兼容
- [x] 1.3 定义宏任务、解答草稿和批量 Critique 输出 schema，覆盖 `accept`、`repair`、`reject_route`、candidate assessment 和失败路线摘要
- [x] 1.4 为旧 ReasoningStep 增加到新草稿/claim 批次的兼容转换，避免一次性删除现有 P/D/R/C 提交流程
- [x] 1.5 增加状态 invariant 测试，覆盖草稿版本、claim 依赖、预算字段、finalize mode 和旧状态兼容

## 2. 策略与宏任务生成

- [x] 2.1 扩展 StrategyPlanner 输出，选择 `direct`、`draft` 或 `macro` execution mode
- [x] 2.2 更新策略提示词，要求默认生成 2 至 4 个可独立审查的宏任务，并禁止只做符号重命名、机械转写或未闭合猜想的小任务
- [x] 2.3 实现宏任务程序规范化，限制数量、过滤过细或重复 objective，并保持选择题任务中立
- [x] 2.4 调整任务优先级和激活逻辑，使重规划或策略创建的首个宏任务成为下一执行目标
- [x] 2.5 增加 direct/draft/macro 路由与宏任务规范化的 deterministic 测试

## 3. Solver 草稿生成与上下文压缩

- [x] 3.1 更新 Solver 协议，允许一次提交多个定义、结论、任务关闭和候选，并增加完整 solution draft 输出
- [x] 3.2 更新 Solver 提示词，使其优先完成整个宏任务或完整解答，不再要求只推进一个微小步骤
- [x] 3.3 重构 Solver context，只传原题、策略、当前宏任务、关键可靠结论、当前草稿/候选、最近失败路线和预算摘要
- [x] 3.4 移除 accepted assistant JSON 在 solver history 与 authoritative state 中的重复注入，仅为协议 regeneration 保留受限 response excerpt
- [x] 3.5 增加上下文内容和字符上限测试，确认 skill 全文、完整历史和原始模型响应不会重复进入 Solver 请求

## 4. 确定性协议校验与批量数学审查

- [x] 4.1 实现 Solver 输出的本地协议校验，检查 schema、task ID、dependency ID、重复定义、空 proposal 和非法任务关闭
- [x] 4.2 将可确定修复的协议问题接入本地规范化或一次 JSON regeneration，确保纯协议错误不调用数学 Critique
- [x] 4.3 实现批量 Critique 消息构造与解析，使 LLM 只审查数学正确性、论证闭合和候选一致性
- [x] 4.4 实现 accepted claims 的依赖闭包校验，禁止保留依赖 invalid claim 的后续结论
- [x] 4.5 增加批量 `accept`、局部 `repair`、核心 `reject_route` 和协议 fast-fail 的测试

## 5. 定向 Repair 与部分提交

- [x] 5.1 实现 Critique `repair` 的部分提交，将安全 accepted claims 写入 authoritative state，并保留当前 solution draft 版本
- [x] 5.2 构造定向 Repair 请求，只包含当前草稿、可保留结论、无效结论和最小修复指令
- [x] 5.3 实现草稿版本和 repair count 更新，默认同一草稿最多执行一次模型 Repair
- [x] 5.4 Repair 后只重新审查修改部分及依赖它的结论，同时保持候选冲突检查
- [x] 5.5 增加局部代数修复、依赖无效传播和 Repair 上限耗尽的状态迁移测试

## 6. 时间驱动路由与受限重规划

- [x] 6.1 在每次模型调用前计算 elapsed、remaining 和 final reserve，保留调用次数作为第二保险丝
- [x] 6.2 实现正常、收敛和 final reserve 三个时间区间的路由规则，确保进入 reserve 后下一调用必须收口
- [x] 6.3 为失败路线生成通用 fingerprint，记录核心方法、关键变换和错误分类，不包含题目索引或答案硬编码
- [x] 6.4 将模型 Replanner 默认上限设为 2，并在达到上限后路由到完整草稿修复或 best-effort finalize
- [x] 6.5 修改 replan commit：失效 blocked task 与同路线 open tasks，用新宏任务替换失败路线并立即激活首个新任务
- [x] 6.6 增加时间边界、final reserve、replan 上限、重复路线过滤和任务替换测试

## 7. 候选冲突、Final Audit 与双级收口

- [x] 7.1 实现候选等价/冲突的确定性预检查，区分单一候选和多个实质冲突候选
- [x] 7.2 调整路由：单一受支持候选直接进入 Final Audit，只有冲突候选才调用独立 CandidateVerifier
- [x] 7.3 实现 strict finalize gate，保持必要 requirements、候选一致性和 authoritative evidence 完整性检查
- [x] 7.4 实现 best-effort finalize gate，在时间临界、调用预算临界或存在部分支持候选时允许提前收口
- [x] 7.5 更新 Finalizer/Final Audit 提示词和 schema，要求输出非空、直接、可独立判分的 answer 与关键 reasoning，禁止 `incomplete`、`unknown` 和空答案
- [x] 7.6 增加 strict finalize、单候选 fast path、冲突候选验证、无显式候选提炼和 best-effort finalize 测试

## 8. 编排、审计与回归验证

- [x] 8.1 将新流程接入 Runtime 主循环，形成 Direct Solve 或 Draft/Macro -> Critique -> Repair/Replan -> Final Audit 的完整状态迁移
- [x] 8.2 更新稳定 trace，记录 execution mode、宏任务、Critique、Repair、route rejection、调用计数、剩余预算和 finalize mode，仅保存摘要与 ID
- [x] 8.3 确认 debug trace 继续受配置和字符上限控制，不泄露完整 prompt、原始响应、密钥或本地路径
- [x] 8.4 增加端到端 fake-client 测试，验证普通题在 5 至 8 次目标调用内正常收口，复杂失败路径仍预留最终调用
- [x] 8.5 运行 custom2 parser、state、runtime、verifier、finalizer 相关单元测试和 `tests/test_user_agent_contract.py`
- [ ] 8.6 使用本地 JSONL runner 做不依赖标准答案硬编码的回归比较，记录模型调用数、Verifier 拒绝率、Replanner 次数、strict/best-effort 比例和总耗时
- [x] 8.7 在新流程 feature flag 下验证 `final_response` 始终为非空字符串后，将高效流程设为 custom2 默认，并保留旧流程回滚开关一个版本周期

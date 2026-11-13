## Why

当前默认 `custom2_staged` 让单个模型同时承担完整求解、固定四章节排版和多项验证要求；当接入模型能力有限时，容易出现路线漂移、格式失败和无效重试。需要引入一种受 20 分钟硬时限约束的动作图运行时，让 Planner 每次只选择一个数学动作、节点只完成一件事，并把严格性放在中间结论验证而非最终答案排版上。

## What Changes

- 新增可独立选择的 Action Graph 数学运行时；它使用独立 Agent、状态、提示词、调度循环和 `action_*` 配置，不继承、不委托、不替换也不改写现有 `custom2_staged`。当前默认入口保持 `custom2_staged`，只有显式选择新 mode 时才运行新 Runtime。
- Planner 不生成完整解答，只从受控动作集合中选择下一动作、目标和成功条件；Executor、Reflector 和 Finalizer 各自承担单一职责。
- 首次 Bootstrap 在一次调用内完成领域归一化、答案模式、风险、技能路由和首个动作选择；该动作直接作为第一次 Planner 决策，避免再调用一遍分类器或策略器。
- 支持分析、联想、推导、界证明、构造、分类、归纳、反证、命题检验、路线反思和结束等通用动作，并限制分支深度、修复次数和失败路线复用。
- 系统参考 MathAgent 的 PRER 提示词组织方式，为 Planner、各类动作、正确性检查和完成度摘要提供职责隔离的模板；统一注入当前目标、已知条件、已接受记忆和失败记忆，并动态隐藏已禁用动作。
- 将动作选择、动作执行、节点检查、节点摘要、分支创建、记忆装载和可用动作过滤实现为明确的内部工具接口，结合本项目已有技能检索、白名单程序检查和最终答案适配能力。
- 新增零模型调用的离线题目预处理，提供可追溯的规范化文本、LaTeX 视图、条件与数字、子问题、显式定义域、题目目标和复杂度特征。
- 原题保持不可变且为唯一权威来源；压缩、重述和结构化抽取均为辅助视图，校验失败时自动回退原题。
- 显式维护带来源与问项覆盖信息的候选答案；候选答案只有在依赖结论均已审核且覆盖要求成立后，才能供 Finalizer 使用，依赖失效时同步撤销候选资格。
- 为各角色设置确定的上下文字符上限和裁剪优先级；动态题面、技能和历史均作为 user message 中有边界的不可信数据，system message 只保留简短角色定义。
- 使用单题墙钟总预算控制 Planner、Executor、Reflector、分支和 Finalizer，任何路径均不得突破正式评测的 20 分钟最高时长。
- Action Runtime 的 Planner、Executor、Reflector、恢复和 Finalizer 默认全部关闭 thinking mode，同时为每个阶段提供互不联动的代码配置开关。
- 最终生成采用宽松自然语言协议：完整回答全部问项，证明题保留必要证明，其他题允许直接给结论；不要求固定章节、固定步数或 JSON。最终答案适配器 SHALL 将成功提取的答案统一规范化为 `\boxed{...}`，方便评判器识别，而不把该格式负担交给弱模型。
- 保持平台注入 client、`ReasoningAgent` 初始化与 `solve` 返回契约，以及现有数据集输出和 JSON 安全 trace 结构不变。
- `metadata` 仅用于本地诊断标识且不进入模型提示词；运行时不得读取或依赖其中的答案、标签、参考解或同类字段。

## Capabilities

### New Capabilities

- `action-graph-math-runtime`: 定义单动作规划、节点执行与反思、受限分支、结论提交、墙钟预算、宽松最终整理及 trace 行为。
- `offline-problem-preprocessing`: 定义不调用模型的题面规范化、结构化抽取、安全紧凑视图、来源追踪、复杂度估计和失败回退行为。

### Modified Capabilities

无。

## Impact

- 预计在 `reasoning_agent/action_graph/` 新增完整独立的 Agent、Runtime、动作工具接口、提示词模板及预处理模块，仅在 `reasoning_agent/factory.py` 增加显式 `custom2_action` 入口；不把新协议塞入 `Custom2Agent` 的 `json|text|staged` 分支。
- 只复用与 staged 调度无关的注入客户端调用包装、数学技能检索、程序检查和答案规范化等通用底层能力；不得继承或调用 `StagedReasoningRuntime`，不得复用 staged 固定四章节提示词、修复循环、问题特例和 staged 配置字段。
- `user_agent.py`、`ReasoningAgent(client=...)`、`solve(problem, metadata)` 和最小 `{"final_response": "..."}` 返回契约保持不变。
- 不增加外部依赖，不读取答案字段，不针对数据集索引、已知题目、特定常数或参考答案增加硬编码。
- 新增确定性单元测试和模拟客户端集成测试；生成输出、评测数据与日志不进入版本控制。

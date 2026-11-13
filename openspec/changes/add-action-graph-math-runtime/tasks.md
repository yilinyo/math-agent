## 1. 预处理数据模型与基础规范化

- [x] 1.1 在 `reasoning_agent/action_graph/` 新建完全独立的 Agent、Runtime、配置与 preprocessing 包，先定义最小 `ProblemPacket(raw_text, normalized_text, subquestions)`，再扩展 `SourceSpan`、公式、数值、条件、变量域和复杂度记录的数据模型，并保证全部对象可转为 JSON 安全摘要；不得继承或委托 `StagedReasoningRuntime`。
- [x] 1.2 实现换行、空白和受支持 Unicode 数学符号的机械规范化，同时保留不可变原题和 normalized-to-raw 位置映射；所有 `SourceSpan` 必须使用 `raw_text` 半开区间字符偏移。
- [x] 1.3 实现 LaTeX 数学块识别、定界符与花括号平衡检查，保存原始公式和规范化公式，不执行求值或代数化简。
- [x] 1.4 为文本与 LaTeX 规范化添加确定性测试，覆盖混合换行、Unicode/多字节关系符号、转义字符、不平衡公式、长度变化后的 offset 映射和 `raw_text[start:end]` 原文可恢复性。

## 2. 结构化题面抽取与安全紧凑视图

- [x] 2.1 实现段落、列表、选项、公式块和显式分项标记的结构切分，并在无法可靠拆分时退回单一子问题。
- [x] 2.2 实现显式数值、区间、变量、条件和目标提取，确保每项包含来源位置、原文片段、方法和置信度，语义不明确时标记未知。
- [x] 2.3 实现整数、正整数、非负整数、有理数、实数、复数和有限集合的显式定义域及局部作用域识别。
- [x] 2.4 实现抽取式“已知/需要”题目要求视图，不生成无法定位回原文的新事实。
- [x] 2.5 实现结构化紧凑视图及不变量检查，至少验证数字、公式、量词、否定条件、定义、选项和子问题不丢失且不引入新数字或符号，失败时回退规范化全文。
- [x] 2.6 实现只用于资源路由的复杂度特征和保守默认值，不让复杂度结果参与答案或数学事实判断。
- [x] 2.7 添加预处理组件级测试和整体属性测试，覆盖多问顺序、定义域作用域、来源定位、压缩不变量、单组件异常隔离及零模型调用。

## 3. 动作状态与注册表

- [x] 3.1 定义 `ActionRuntimeState`、`ActionNode`、`AcceptedClaim`、`AnswerCandidate`、`RouteFingerprint`、子问题状态和共享 `RuntimeBudget`，区分草稿、权威结论和可判分候选答案。
- [x] 3.2 建立通用动作注册表，注册 `analyze`、`associate`、`derive`、`prove_bound`、`construct`、`classify`、`induct`、`negate`、`test_claim`、`rethink` 和 `finish` 的职责、输入和成功条件。
- [x] 3.3 实现默认保险丝：正常节点 5、总 Executor 节点尝试 6、分支深度 2、单次子分支 3、开放分支 3、单节点及全题修复 1、路线反思 1、Planner 协议修复 1、网络恢复 1、总模型调用 20、程序检查 8；新增节点须保留 Executor、Reflector 和 Finalizer 调用额度。
- [x] 3.4 实现失败路线指纹、依赖失效和重复路线检测，确保没有新增证据时不能原样重复已否决路线。
- [x] 3.5 添加状态转换测试，覆盖结论提交、候选支持、候选依赖递归失效、分支覆盖、上限收束和重复路线拒绝。

## 4. Planner 与上下文构造

- [x] 4.1 编写 Model Preprocessor、Profile Classifier、Strategy/Skill Selector 和逐轮 Planner 的动态提示词；前置请求各自只承担结构、画像、策略/技能或单动作选择。
- [x] 4.2 实现 Planner/Executor 上下文构造和默认字符上限：24000/48000、题目视图 24000、accepted memory 10000、failure memory 4000、技能材料 12000、trace/debug 单字段 12000；按当前目标、相关原文、定义域/量词/否定、直接依赖结论、当前失败、技能、旧成功记忆、旧失败记忆的优先级裁剪。
- [x] 4.3 实现 Planner 决策 JSON 解析与程序校验，未知动作、多动作或缺失字段最多触发一次短协议修复，随后使用确定性安全路由。
- [x] 4.4 添加模拟模型测试，验证单动作约束、非法 JSON、未知动作、完整答案越权输出、预算不足和 `finish` 路由。
- [x] 4.5 实现提示词前完整阅读 MathAgent 的 `src/prompts.py`、`src/actions.py` 和 `src/infer_node.py`，逐项对照其 `select`、动作角色、通用上下文、分支模板、`check`、`summary`、失败记忆和动作禁用机制，并按 `design.md` 的适配表确认哪些复用、改造或拒绝移植。
- [x] 4.6 参考 MathAgent 的目标、条件、成功记忆和失败记忆结构，实现共用提示词骨架，并确保所有动态内容只进入 user message。
- [x] 4.7 实现 `filter_available_actions`，按目标类型、分支深度、剩余预算和失败路线动态删除不可用动作，只把过滤后的动作目录交给 Planner。
- [x] 4.8 添加提示词快照与动作隔离测试，验证 Planner 不求解、Executor 只执行当前动作、成功/失败记忆分区且完整旧稿不被重复注入。
- [x] 4.9 将全部动态材料放入 user message 的命名边界块，system message 仅保留短角色和协议优先级；测试题面、技能和历史中的伪指令不能覆盖动作或输出协议，并验证裁剪不从 LaTeX 块或 SourceSpan 中间切断。
- [x] 4.10 添加前置路由测试，覆盖预处理、领域画像、策略/技能筛选、非法 JSON 修复、字段缺失回退和简单题首动作直接执行。

## 5. Executor、技能检索与节点审核

- [x] 5.1 为各动作生成职责单一的 Executor 动态提示词，system message 仅声明领域数学专家，user message 包含当前动作所需的完整动态上下文。
- [x] 5.2 实现自然语言 Executor 响应接收和可选最小 `ACTION_RESULT` 控制尾部解析，控制尾部失败时保留正文供审核。
- [x] 5.3 复用并适配现有技能检索，按 Strategy/Skill Selector 的已校验规范领域和章节使每个节点只注入相关定理卡，并在字段非法、`unknown` 或无命中时无阻塞降级。
- [x] 5.4 实现 Reflector 提示词和 `accept|repair|reject_route` 解析，只提交审核明确接受的结论并记录首个关键错误。
- [x] 5.5 接入现有白名单程序检查，把真实检查结果作为审核证据，但不把表达式检查自动提升为题目模型证明。
- [x] 5.6 实现每节点最多一次的局部修复以及核心路线否决后的依赖失效和 Planner 反馈。
- [x] 5.7 添加模拟模型测试，覆盖接受、部分结论提交、局部修复、路线否决、技能缺失、控制尾部损坏和程序检查矛盾。
- [x] 5.8 实现 `negate`、`induct` 和 `classify` 的专用安全 JSON 分支协议及 `spawn_branches`，禁止 `eval` 并验证条件、目标和覆盖字段。
- [x] 5.9 实现与 Reflector 分离的 `summarize_node`，只压缩已接受结论、更新目标覆盖和生成后续记忆，不重新判断错误草稿为正确。
- [x] 5.10 将 `select_action`、`execute_action`、`check_node`、`summarize_node`、`spawn_branches`、`load_node_memory` 和 `filter_available_actions` 建立为可独立测试的内部工具接口。
- [x] 5.11 添加分支协议、正确性/完成度分离、失败动作禁用和内部工具受控异常的测试。

## 6. 运行循环与 20 分钟预算

- [x] 6.1 实现显式动作循环和受限分支队列，串联预处理、规划、执行、审核、提交、重规划和收束。
- [x] 6.2 实现 `min(configured_total, 1200)` 的共享墙钟截止时间，并确保所有重试、分支和最终整理使用同一计时器。
- [x] 6.3 实现独立 `action_*` 配置：总预算 1200 秒、最终整理保留 150 秒、返回保留 30 秒、Reflector 保留 60 秒和最小节点周期 240 秒；总剩余时间不大于 330 秒时停止创建新节点。
- [x] 6.4 实现网络错误、读取超时、长度截断和空输出的一次有界恢复，保证恢复不会重置预算或递归重试。
- [x] 6.5 实现 Finalizer 失败时的确定性返回优先级，优先保留有效最终正文或已接受数学结论，并始终返回非空字符串。
- [x] 6.6 添加可控时钟和模拟 client 测试，覆盖正常完成、慢调用、阶段超时、恢复成功、恢复失败、收束窗口和不超过 1200 秒的调度约束。
- [x] 6.7 配置 Model Preprocessor(false/8192/150s)、Profile Classifier(false/8192/90s)、Strategy/Skill Selector(false/8192/120s)、Planner(false/8192/120s)、Executor(false/16384/420s)、压缩恢复(false/8192/270s)、Reflector(false/8192/120s) 和 Finalizer(false/8192/150s)，为每个阶段提供互不联动的 `action_*_thinking_mode` 代码配置开关；JSON 协议修复只针对已返回但结构非法的内容，Node Summarizer 默认零模型调用。
- [x] 6.8 实现 5/180/720/210/120/115 秒的预处理、Planner、Executor/Repair、Reflector、Finalizer 和安全余量阶段池，并在每次调用前取阶段上限、阶段剩余和扣除保留后的总剩余最小值。
- [x] 6.9 区分可安全恢复的返回失败与可能留下后台线程的 Runtime 强制超时；后者不得立即启动另一个长请求，并添加孤儿请求不叠加测试。
- [x] 6.10 用模拟 client 打通最小纵向切片：模型预处理 → 画像 → 策略/技能 → 首动作 → Executor → Reflector → supported AnswerCandidate → Finalizer，并验证 low 复杂度题不会发生无意义的重复前置请求且仍经过审核。

## 7. 宽松 Finalizer 与答案适配

- [x] 7.1 编写宽松 Finalizer 提示词，只允许使用原题、supported AnswerCandidate 与已接受结论，覆盖全部问项、证明题保留必要证明并且不输出控制状态。
- [x] 7.2 实现模式感知的最低限度可用性检查，不再检查固定章节、固定步骤或行数，也不把模型是否主动输出 `boxed` 作为生成成功门槛。
- [x] 7.3 调整动作运行时的答案适配：可靠提取到的最终答案必须由程序规范化为 `\boxed{...}`，已有合法 box 不重复包裹，多问保持问项对应关系。
- [x] 7.4 确保只有空文本、占位文本或明显漏问才可能触发一次预算内整理修复，纯排版差异不得触发重试。
- [x] 7.5 实现证明题答案适配，保留完整证明正文，并在末尾保留或追加可靠提取出的 boxed 结论；抽取失败时不得编造 box。
- [x] 7.6 添加最终输出测试，覆盖裸数值自动 boxed、已有 box 不嵌套、LaTeX、无标题正文、多问编号与逐项 boxed、中文结论、完整证明加 boxed 结论、抽取失败但正文有效和占位输出。

## 8. Trace、入口与契约集成

- [x] 8.1 实现预处理、Planner、节点、审核、候选答案状态、分支、修复、路线否决、预算收束、最终整理和结束的稳定 trace 事件；结束事件包含程序判定的 `success|timeout|failed`、耗时、计数和停止原因。
- [x] 8.2 对 trace 和 debug trace 做 JSON 安全及长度限制，验证其中不包含完整 prompts、原题副本、API key、metadata 答案字段或本地私密路径。
- [x] 8.3 新建独立 `ActionGraphAgent`，只在工厂中增加直接构造它的显式 `custom2_action` mode；不得修改 `Custom2Agent` 的 `json|text|staged` 协议分派，当前默认 `custom2_staged` 保持不变。
- [x] 8.4 保持本地 runner 输出兼容，使动作运行时结果能继续组合为 `idx`、`status`、`final_response`、`trace`、可选 `debug_trace` 和 `duration_seconds`。
- [x] 8.5 扩展平台契约测试，验证 `ReasoningAgent(client=...)`、`solve(problem, metadata)`、`metadata=None`、JSON 序列化、三种 `solve_status` 和任何状态下非空 `final_response`。
- [x] 8.6 添加架构隔离测试，验证选择 `custom2_staged` 时不会导入或执行 Action Graph 调度，选择 `custom2_action` 时不会导入 staged prompts/models/runtime，也不会读取任何 `staged_*` 配置字段。
- [x] 8.7 添加并发 solve 测试，验证共享 Agent 实例下每题 Runtime、预算、节点、失败记忆、候选和 trace 完全隔离。
- [x] 8.8 添加 metadata 隔离测试，向 `answer`、`reference_answer`、`solution` 和 `label` 注入伪值并确认它们不进入 prompt、数学状态或 trace，也不改变模型调用序列和答案适配结果。

## 9. 回归验证与文档

- [ ] 9.1 运行全部离线单元测试和平台入口契约测试，修复动作图新增逻辑导致的回归。
- [x] 9.2 使用模拟 client 完成端到端场景，验证简单计算、证明、多问、分类分支、错误路线修复、预处理降级和最终模型弱格式输出。
- [x] 9.3 使用本地样例数据进行非提交式回归，比较正确性、模型调用次数、纯格式失败次数和总耗时，确认单题不会由调度逻辑突破 20 分钟。
- [x] 9.4 更新 README 的运行模式、配置、预算、trace 和宽松最终输出说明，并明确动作图模式暂不改变默认入口。
- [x] 9.5 检查 `git status` 和暂存列表，确保不提交数据集、验证输入、生成输出、运行日志、原始模型响应、缓存或密钥。
- [x] 9.6 在设计文档或 README 中记录 MathAgent 的 MIT 来源、借鉴机制和未移植的安全风险，避免后续维护者误以为是逐文件复制。

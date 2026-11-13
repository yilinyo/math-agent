## Purpose

提供一种面向能力有限数学模型和单题 20 分钟评测环境的动作图推理协议，通过单动作规划、局部执行、独立反思和受限收束生成可判分答案，同时保持平台入口、注入客户端和诊断输出兼容。

## ADDED Requirements

### Requirement: 独立可选的动作图运行时
系统 SHALL 提供显式可选的动作图数学运行时，并 SHALL 保持现有默认运行时可继续独立使用。动作图运行时 SHALL 拥有独立 Agent、状态模型、提示词、调度循环和 `action_*` 配置，不得继承、委托或调用 `StagedReasoningRuntime`，也不得把动作协议加入 `Custom2Agent` 的现有 solver protocol 分支。该运行时 SHALL 通过平台注入的 client 发起全部模型调用，不得创建替代客户端或读取本地密钥。

#### Scenario: 显式选择动作图运行时
- **WHEN** 调用方通过受支持的 agent mode 选择动作图运行时
- **THEN** 工厂直接构造独立 Action Graph Agent 处理题目，且 `ReasoningAgent(client=...)` 与 `solve(problem, metadata)` 的签名保持不变

#### Scenario: 未选择动作图运行时
- **WHEN** 调用方选择现有受支持运行时
- **THEN** 系统保持该运行时原有入口、配置和行为，不导入或执行动作图调度，也不被动作图运行时隐式替换

#### Scenario: 复用通用底层能力
- **WHEN** 动作图运行时需要模型调用、技能检索、白名单计算或答案规范化
- **THEN** 它可以调用不含 staged 调度语义的通用工具，但不得因此读取 staged 提示词、状态、节点循环或配置字段

#### Scenario: 并发处理多道题
- **WHEN** 同一个平台 Agent 实例被并发调用多次 `solve`
- **THEN** 每次调用创建独立 Runtime 和题目级状态，任一道题的节点、预算、失败记忆或 trace 不得泄漏到其他题目

### Requirement: Planner 每轮只选择一个动作
Planner SHALL 只根据题目视图、已确认结论、失败路线、未完成问项和剩余预算选择一个下一动作，不得生成整题完整答案。每个决策 SHALL 至少包含动作名称、处理目标、所需事实和可检查的成功条件。

#### Scenario: 存在未完成目标
- **WHEN** 当前状态仍有未完成问项且预算允许继续推理
- **THEN** Planner 从动作注册表中返回恰好一个合法动作，而不是返回多步计划或完整解答

#### Scenario: Planner 返回非法决策
- **WHEN** Planner 返回未知动作、多个动作或缺少必要控制字段
- **THEN** 系统拒绝该决策并使用一次受限协议修复或确定性安全路由，不把非法内容作为数学结论提交

### Requirement: 前置模型阶段职责隔离与首动作选择
Runtime SHALL 将题面预处理、领域/风险画像、策略与技能章节选择拆为职责单一的 JSON 模型请求，再由策略结果提供首个合法动作。前置请求 SHALL 不得直接求解或输出最终答案；技能详情 SHALL 由程序按已校验领域和章节本地检索。只有模型已返回但 JSON 结构失败时，系统 SHALL 最多带错误原因修复一次；网络、读取超时和长度错误 SHALL 直接使用对应的确定性降级，不得把分类失败当作数学事实。

#### Scenario: 前置阶段返回有效首动作
- **WHEN** Model Preprocessor、Profile Classifier 和 Strategy/Skill Selector 返回合法结构及 `initial_decision`
- **THEN** Runtime 直接执行该动作，并把它计入 Planner 决策和总模型调用额度

#### Scenario: 领域无法识别
- **WHEN** Profile Classifier 返回中文标题、别名或不在技能目录中的领域值且程序无法映射
- **THEN** 系统使用 `unknown` 和通用数学技能继续，Executor 的 system message 使用“你是数学专家”而不是构造 unknown 领域名称

#### Scenario: 简单低复杂度题
- **WHEN** 模型画像复杂度为 low 且策略选择的首动作足以直接求得目标
- **THEN** 系统可用一个 Executor 节点完成推导或计算，但仍须经过 Reflector、候选答案覆盖检查和 Finalizer，不另设绕过审核的完整 Solver

### Requirement: 通用数学动作与单一节点职责
运行时 SHALL 提供领域无关的受控动作集合，至少覆盖分析、联想、推导、证明上下界、构造、分类、归纳、反证、检验命题、反思路线和结束。每个执行节点 SHALL 只处理 Planner 指定的一个目标，并 SHALL 将数学正文与最小控制信息分离。

#### Scenario: 执行推导动作
- **WHEN** Planner 选择 `derive` 并指定一个待证中间结论
- **THEN** Executor 只围绕该结论给出可审核推导，不擅自宣布其他未完成问项已经解决

#### Scenario: 执行分类动作
- **WHEN** Planner 选择需要分支的分类动作
- **THEN** 系统创建数量受限、条件互斥且可追踪的子分支，并记录各分支覆盖目标

### Requirement: 职责隔离的动作提示词
系统 SHALL 为 Planner、每类数学动作、正确性检查和完成度摘要使用不同的职责提示词。各动作提示词 SHALL 复用统一的目标、条件、已接受记忆和失败记忆上下文骨架，并 SHALL 明确当前 Agent 只能完成所选动作，不得越权代替其他节点或 Finalizer。

#### Scenario: 构造 Executor 提示词
- **WHEN** Planner 已选择一个合法动作
- **THEN** Executor 接收该动作专属角色、当前目标、相关原题条件、已接受结论和失败反馈，且提示词不要求其输出完整整题答案

#### Scenario: 提示词包含失败记忆
- **WHEN** 当前目标存在已审核失败的尝试
- **THEN** 后续 Planner 和 Executor 接收短而可定位的失败原因，并被要求避免重复对应错误，而不是接收整份旧草稿

#### Scenario: 动作被动态禁用
- **WHEN** 某动作因深度上限、预算、重复路线或当前目标不适用而不可用
- **THEN** Planner 的动作目录不包含该动作，且不得依赖提示词后的程序纠错来反复选择它

### Requirement: 分支动作使用专用协议
反证、归纳和分类动作 SHALL 使用各自的最小分支协议。反证协议 SHALL 明确附加假设和待导出的矛盾目标；归纳协议 SHALL 区分基例和归纳步骤；分类协议 SHALL 输出有限的分支条件、分支目标和覆盖说明。分支输出 SHALL 使用安全 JSON 解析，不得执行模型生成文本。

#### Scenario: 反证动作创建分支
- **WHEN** Planner 选择反证动作
- **THEN** 系统只接受包含原条件、反设和矛盾目标的合法分支描述，并将其作为子节点上下文而非已证结论

#### Scenario: 归纳动作创建分支
- **WHEN** Planner 选择归纳动作
- **THEN** 系统分别登记基例与归纳步骤，且两者均完成前不得将归纳目标标记为已解决

#### Scenario: 分类动作协议不完整
- **WHEN** 分类输出缺少分支条件、目标或覆盖信息
- **THEN** 系统拒绝创建不完整分支，并在预算允许时进行一次协议修复或改选动作

### Requirement: 节点反思与结论提交门槛
每个产生数学结论的节点 SHALL 在写入权威结论集合前接受 Reflector 审核。Reflector SHALL 返回 `accept`、`repair` 或 `reject_route` 之一，并 SHALL 指明首个关键错误或接受依据；未经接受的结论不得供 Finalizer 当作已证事实使用。

#### Scenario: 节点被接受
- **WHEN** Reflector 确认节点满足动作成功条件且没有致命数学错误
- **THEN** 系统仅提交该节点明确支持的结论，并保留其来源节点和依赖关系

#### Scenario: 节点需要局部修复
- **WHEN** Reflector 判断核心路线可用但存在可定位的局部缺口
- **THEN** 系统最多进行配置允许的有限修复，并把错误信息和修复要求提供给修复节点

#### Scenario: 核心路线被否决
- **WHEN** Reflector 给出 `reject_route`
- **THEN** 系统使依赖该路线的未确认结果失效，记录失败路线指纹，并禁止 Planner 原样重复同一路线

### Requirement: 正确性检查与完成度摘要分离
系统 SHALL 将“节点推导是否正确”和“当前目标是否已解决”作为两个独立判断。Reflector 负责正确性与可提交结论；Node Summarizer 只压缩已接受内容、判断目标覆盖并生成后续记忆，不得把未通过审核的输出总结成已证事实。

#### Scenario: 推导正确但目标未完成
- **WHEN** Reflector 接受节点中的局部结论，但该结论不足以满足当前目标
- **THEN** Node Summarizer 将其记录为可复用中间记忆，并保持对应目标未完成

#### Scenario: 输出声称完成但存在错误
- **WHEN** Executor 声称已经解决目标而 Reflector 发现致命错误
- **THEN** 系统拒绝提交该结论，Node Summarizer 不得将目标标记为完成

### Requirement: 显式候选答案与依赖失效
运行时 SHALL 将已接受的局部结论与可用于最终回答的 `AnswerCandidate` 分开管理。每个候选 SHALL 记录答案内容、答案模式、覆盖的子问题、来源 claim、产生节点、状态和失效原因。候选只有在所有来源 claim 有效且覆盖检查通过后才可标记为 `supported` 并提供给 Finalizer；依赖 claim 失效 SHALL 递归撤销相关候选资格。

#### Scenario: 局部结论正确但尚无完整答案
- **WHEN** Reflector 接受一个中间结论但它没有覆盖任何最终问项
- **THEN** 系统保存 accepted claim，但不得凭该结论创建或支持完整答案候选

#### Scenario: 候选答案获得支持
- **WHEN** 候选的全部来源 claim 已接受且其声明的问项覆盖经程序核对成立
- **THEN** 系统将候选标记为 `supported`，Finalizer 可以使用该候选及对应证明材料

#### Scenario: 修复使上游结论失效
- **WHEN** 路线否决或修复使候选依赖的 claim 失效
- **THEN** 系统同步将候选标记为 `invalidated`，后续上下文和 Finalizer 不得继续使用旧答案

### Requirement: 动作能力通过内部工具接口组合
运行时 SHALL 通过边界清晰的内部工具接口组合动作选择、动作执行、节点检查、节点摘要、分支创建、记忆装载和可用动作过滤。工具失败 SHALL 返回可记录状态并按预算降级，不得通过未捕获异常终止整题。

#### Scenario: 动作工具正常组合
- **WHEN** 一个非分支节点被处理
- **THEN** 系统依次完成可用动作过滤、单动作选择、动作执行、正确性检查和完成度摘要，并把每一步结果关联到同一节点 ID

#### Scenario: 内部工具失败
- **WHEN** 任一内部动作工具返回解析错误、空结果或受控异常
- **THEN** 系统记录工具名和有界错误类型，保留已有权威状态，并依据剩余预算修复、改选动作或收束

### Requirement: 有界分支和循环收敛
系统 SHALL 对动作节点数、分支深度、每次分类的子分支数、单节点修复次数和路线反思次数设置有限上限。默认 SHALL 最多创建 5 个正常动作节点、执行 6 次 Executor 节点尝试、达到 2 层分支深度、为一个分支动作创建至多 3 个子分支、全题执行至多 1 次节点修复和 1 次路线反思。正常、分支、修复和压缩恢复 SHALL 共享 6 次节点尝试额度；新增节点仍须满足墙钟收束窗口并保留 Executor、Reflector 和 Finalizer 的模型调用额度。达到上限后 SHALL 转入已有证据收束，不得继续无界扩展推理图。

#### Scenario: 达到节点或分支上限
- **WHEN** 下一动作会超过任一配置上限
- **THEN** 系统不创建该节点，转而请求结束或基于当前最佳证据进入最终整理

#### Scenario: 复杂度调整初始额度
- **WHEN** 离线复杂度分别为 low、medium 或 high
- **THEN** 系统分别以 1/2、2/3、3/4 作为正常节点/总节点尝试的初始额度，并只允许在已接受有效进展但目标未完成时扩展一次，绝对上限仍为 5 个正常节点和 6 次节点尝试

#### Scenario: Planner 重复失败路线
- **WHEN** 新决策与已记录的失败路线指纹等价且没有新增证据
- **THEN** 系统拒绝该决策，并选择反思、替代动作或收束

### Requirement: 单题 20 分钟墙钟预算
运行时 SHALL 将单题总预算限制在不超过 1200 秒，并 SHALL 默认预留 150 秒用于最终整理及 30 秒用于解析返回。新节点至少需要 240 秒节点周期预算；当总剩余时间不大于 330 秒时不得创建新节点。Executor 调用前 SHALL 额外保留 60 秒 Reflector 时间。每次模型调用的允许等待时间 SHALL 取阶段上限、阶段剩余额度、总剩余时间和保留窗口约束后的最小值；预算不足时不得发起无法在窗口内完成的新推理调用。

#### Scenario: 正常预算推进
- **WHEN** 剩余时间大于当前动作估计时间和最终整理保留时间之和
- **THEN** 系统允许发起下一节点调用，并把实际剩余墙钟时间传入调用约束

#### Scenario: 进入收束窗口
- **WHEN** 剩余时间达到或低于 330 秒的新节点阈值
- **THEN** 系统停止创建推理节点并立即进入最终整理或确定性兜底

#### Scenario: 单次调用失败或超时
- **WHEN** 注入客户端返回网络错误、读取超时、长度截断或空结果
- **THEN** 系统记录失败并仅在总预算与重试上限允许时执行一次有界恢复，不重置单题计时器

### Requirement: 各角色独立调用配置
动作图运行时 SHALL 使用独立于 staged 的 `action_*` 配置控制各角色的 thinking mode、max tokens、单次 timeout、阶段时间池和调用上限。默认总模型调用上限 SHALL 为 20；新增推理节点前 SHALL 保留一轮 Executor、Reflector 和 Finalizer 所需调用额度。Node Summarizer 默认 SHALL 不调用模型。

#### Scenario: 使用默认角色配置
- **WHEN** 调用方没有覆盖动作图配置
- **THEN** Model Preprocessor 使用 thinking=false、8192 tokens、150 秒，Profile Classifier 使用 thinking=false、8192 tokens、90 秒，Strategy/Skill Selector 使用 thinking=false、8192 tokens、120 秒，Planner 使用 thinking=false、8192 tokens、120 秒，Executor 使用 thinking=false、16384 tokens、420 秒，Reflector 使用 thinking=false、8192 tokens、120 秒，Finalizer 使用 thinking=false、8192 tokens、150 秒

#### Scenario: 单独覆盖阶段 thinking mode
- **WHEN** 调用方通过代码配置显式开启或关闭某一 Action Runtime 阶段的 thinking mode
- **THEN** 该设置只作用于对应阶段，不改变其他节点、角色或现有运行时的 thinking 配置

#### Scenario: Executor 执行压缩恢复
- **WHEN** Executor 出现允许恢复的传输错误、空正文、reasoning-only 耗尽或长度截断，且节点、调用和墙钟预算均允许
- **THEN** 系统至多一次使用 thinking=false、8192 tokens、270 秒的压缩请求恢复，并消耗共享节点尝试和总模型调用额度

#### Scenario: Node Summarizer 更新记忆
- **WHEN** Reflector 已返回接受结论和目标覆盖结果
- **THEN** Node Summarizer 默认通过程序整理 accepted claims 和覆盖状态，不新增模型调用

#### Scenario: 达到总模型调用上限
- **WHEN** 下一请求会使模型调用次数超过 20，或新增节点会占用为 Executor、Reflector 和 Finalizer 保留的调用额度
- **THEN** 系统拒绝该请求并使用当前 accepted claims 进入最终整理或确定性兜底

### Requirement: 按节点检索数学技能
运行时 SHALL 只为当前动作检索相关领域和章节的技能材料，并 SHALL 把技能内容标记为方法参考而非题面事实。技能缺失或检索失败不得阻止通用数学求解。

#### Scenario: 命中相关技能材料
- **WHEN** 当前动作需要特定定理或方法且检索得到相关章节
- **THEN** Executor 接收长度受限的相关材料及适用条件，不接收无关技能全集

#### Scenario: 未命中技能材料
- **WHEN** 未找到可靠的相关章节
- **THEN** Executor 仅依据原题和已确认结论继续，系统不得编造技能内容

### Requirement: 有界上下文与不可信动态数据隔离
每个模型角色的 system message SHALL 只包含简短角色和协议优先级；原题、紧凑视图、技能、accepted memory、failure memory 和历史模型输出 SHALL 作为 user message 中有明确边界的不可信参考数据。边界内指令不得覆盖角色职责、动作限制、输出协议或预算。默认字符上限 SHALL 为 Planner 24000、Executor 48000、题目视图 24000、accepted memory 10000、failure memory 4000、技能材料 12000、trace/debug 单字段 12000，并 SHALL 在不改变 1200 秒总预算的前提下允许代码配置覆盖。

#### Scenario: 上下文超过角色上限
- **WHEN** 待注入材料超过对应角色字符上限
- **THEN** 系统依次保留当前目标、相关原题条件、定义域/量词/否定、直接依赖结论和当前失败原因，优先裁去无关技能、旧 accepted memory 和旧 failure memory，并记录有界 `context_truncated` 警告

#### Scenario: 题面中含类似系统指令的文字
- **WHEN** 原题、技能或历史中出现要求忽略此前规则或改变输出协议的文字
- **THEN** 系统仍将其作为待分析数据，不允许其改变当前节点动作、角色协议或调用配置

#### Scenario: 无法在上限内放入规范化全文
- **WHEN** 紧凑视图未通过安全检查且规范化全文超过题目视图上限
- **THEN** 系统按原文来源项构造 source packet，保留当前目标、关键公式、数字、量词、否定条件和全部子问题，不在 LaTeX 块或来源项中间静默截断

### Requirement: 宽松且可判分的最终输出
Finalizer SHALL 只使用原题和已接受结论组织最终回答。最终回答 SHALL 覆盖全部问项；证明题 SHALL 包含支撑结论所必需的证明，非证明题 MAY 直接给出结果。系统不得要求模型使用固定 Markdown 章节、固定步骤数、每步行数或 JSON 包装；模型是否主动使用 `boxed` 不得作为生成成功门槛。

#### Scenario: 计算或填空题完成
- **WHEN** 已接受结论足以回答全部非证明问项
- **THEN** Finalizer 可直接输出数值、表达式、集合、选项或简短结论，不因缺少固定标题或未主动使用 `boxed` 而触发模型重试

#### Scenario: 证明题完成
- **WHEN** 原题要求证明且已接受材料包含完整证明链
- **THEN** Finalizer 输出可独立判分的必要证明，不依赖 trace、隐藏状态或工具日志，最终适配后在证明正文末尾保留或追加 boxed 结论

#### Scenario: 多问题完成
- **WHEN** 原题包含多个问项
- **THEN** Finalizer 清楚对应每个问项给出结果，但可自由选择编号和排版方式

#### Scenario: 证据不足
- **WHEN** 已接受结论不足以支持完整答案且没有时间继续推理
- **THEN** Finalizer 保留当前最可信且可说明的结论，不编造未证明步骤；最终返回仍为非空字符串

### Requirement: 提取答案的 boxed 规范化与正文保留
系统 SHALL 对最终文本进行最低限度的可用性检查。只要可靠提取到最终答案，最终答案适配器 SHALL 将其规范化为 `\boxed{...}`；已有合法 `\boxed{...}` SHALL 原样保留且不得重复包裹。无法可靠提取时 SHALL 保留完整可判分回答，不得猜测内容放入 box，也不得因抽取器不识别格式而丢弃正文。

#### Scenario: 自由格式答案可直接判分
- **WHEN** Finalizer 返回非空、非占位且覆盖题目要求的自然语言或数学文本
- **THEN** 系统接受该文本且不要求固定章节；若能可靠提取最终答案，则程序将提取结果规范化为 `\boxed{...}`

#### Scenario: 答案已经 boxed
- **WHEN** 可靠提取的最终答案已经具有合法 `\boxed{...}`
- **THEN** 系统保留该表达式，不生成嵌套或重复的 box

#### Scenario: 多问答案被可靠提取
- **WHEN** 原题包含多个问项且系统能可靠识别各问项的最终答案
- **THEN** 系统逐项使用 boxed 答案或使用一个无歧义的 boxed 组合表达式，并保留问项对应关系

#### Scenario: 抽取失败但正文有效
- **WHEN** 简短答案抽取失败而完整最终回答仍可判分
- **THEN** 系统返回完整最终回答，不编造 boxed 内容，也不触发纯格式模型修复

### Requirement: 输出与 trace 兼容
运行时 SHALL 返回 JSON 可序列化字典及非空 `final_response`，并 SHALL 提供有界、无密钥、无完整提示词的稳定 trace。trace SHALL 记录预处理、规划、节点执行、审核、结论提交、分支、预算收束、最终整理和结束事件。结束状态 SHALL 只取 `success`、`timeout` 或 `failed`：完整问项由 supported candidate 或 accepted proof 覆盖且回答可用时为 `success`；墙钟或收敛窗口导致覆盖未完成时为 `timeout`；非时间类失败且没有可用受支持答案时为 `failed`。任何状态下均 SHALL 返回非空 `final_response`。

#### Scenario: 正常完成题目
- **WHEN** 运行时形成最终回答
- **THEN** 返回值至少包含 `final_response` 和 `trace`，并可由现有本地 JSONL runner 写入 `idx`、`status` 和 `duration_seconds`

#### Scenario: 记录诊断信息
- **WHEN** 开启 debug trace
- **THEN** 诊断字段保持长度受限且不包含 API key、完整动态提示词、隐藏答案、数据集答案字段或本地私密路径

#### Scenario: 记录结束状态
- **WHEN** Runtime 结束或被迫收束
- **THEN** `action_runtime_finished` 记录 `solve_status`、耗时、节点/调用计数和 `stop_reason`，且不采用模型自报状态替代程序判定

#### Scenario: metadata 包含答案字段
- **WHEN** `metadata` 为 `None` 或包含 `answer`、`reference_answer`、`solution`、`label` 及同类字段
- **THEN** 运行时不把这些字段放入模型提示词、数学状态或 trace；它们不得影响动作选择、验证和最终回答，仅允许非语义诊断标识用于本地日志

## Context

新增独立 `custom2_langgraph` 模式，保留 `custom2_staged` 默认模式、官方注入客户端、题目画像、结构化策略检索、领域技能、题面保真审查与数学审计。用户最新确认采用“分段连续推导”：每轮尽量生成多个完整数学步骤，只有按需计算或主动关键结论检查时暂停，出现非空的 `### 最终答案` 段后进入整题验证。不设固定检查点或“无法继续”独立分支。

本设计替代此前“一轮只能一步、单步独立审查、commit、finish_gate”的方案。历史任务和既有测试结果不能作为本次修订的验收结果。可验证推理轨迹指可读的定理、前提、代入、推导、结论和真实工具证据，不要求模型暴露内部思考。

## Goals / Non-Goals

目标：减少不必要的模型请求；允许一次完成简单题、分段续写长题；保留完整推导及真实工具证据；统一整题验证和三轮以内修复；保持工程职责及平台契约。

非目标：通用 ReAct、形式化自动证明、跨题记忆、改变默认模式、另建模型客户端、修改 judge 或检索索引。模型审计通过不等同机器形式证明认证。

## 1. 外层流程与原 staged 行为

```text
分析 → 结构化检索 → 规划/技能准备 → solve 子图 → verify 子图
                                      ↑                │
                                      └── 修复/重规划 ─┤失败或不确定
                                                       │通过
                                           最终答案确认 → 一致性检查
                                                       ↓
                                                 render → END
```

分析只生成问题分析与结构化画像，保留原题中的定义域、量词、端点、方向、互异、有序、重复、维数和结构内运算；原题才是直接事实。规划结合检索策略和技能材料，补充路线、定理前提及义务，不能删除原问项或复制案例答案。

保留 planner 与 executor 两类策略材料、案例置信度、技能/定理来源和修复时的材料刷新。额外策略模型默认关闭时，仍由分析路线和材料形成合法计划。词法、向量、分数加权和 RRF 均可配置；分数加权通道归一化后使用0.3/0.7，RRF 使用同权重及 rrf_k=20。旧模块默认0.45/0.55、rrf_k=10保持不变，不删除任何原检索代码。

## 2. solve 子图：分段连续推导

实际图节点有五个；普通生成不会自动经过关键检查节点：

| 节点 | 职责 | 模型调用 |
| --- | --- | --- |
| assemble_context | 组装原题、路线、已有草稿、工具观测、pending 和修复要求，检查预算 | 无 |
| generate_step | 每轮尽量生成多个完整数学步骤，可附一个工具请求 | 一次生成请求；协议格式恢复另受有界预算限制 |
| update_context | 保存完整格式步骤和未完尾部、提取最终答案段；不判断数学正确性 | 无 |
| python_executor | 执行真实受限 Python，回填输入、范围、状态和结果 | 无 |
| check_conclusion | 仅在 Solver 主动请求时检查指定关键命题，回填结果后继续 | 一次独立检查调用 |

```text
START → assemble_context → generate_step → update_context
              ↑                                  │
              ├────── 普通正文/尚未完成 ───────────┤
              ├──── python_executor ← 有工具请求 ─┤
              ├──── check_conclusion ← 主动送检 ─┤
              │                                  │
              └──────── 继续续写                  └─ 非空最终答案段 → END
预算/异常另有非成功出口，不依赖模型最终输出标记才能停止。
```

不再设置 parse_step、commit_step、step_review 或 finish_gate。函数名 generate_step 为兼容现有组织保留，语义是生成一段，不能理解为一轮只能一步。模型响应不回传 revision、step_id、action、closes 或 candidate；内部编号、版本与工具归属由程序管理。

一轮可以生成步骤1–6及候选，或者步骤1–4后调用工具，下一轮根据真实结果补齐步骤5并继续步骤6–8。没有工具请求不表示结束；没有最终答案段则继续生成，直到预算限制。输出应尽量在完整步骤边界暂停，但不限制每轮数学步骤数量。

## 3. 响应协议与结束标记

SolveTurn 是适配器转换后的内部节点协议（不再要求模型用 JSON tool/check 发起请求）：

```json
{
  "content": "本轮新增的多个数学步骤或当前步骤续写",
  "tool": null,
  "check": null
}
```

API 使用原生 tools 定义 python_executor（code、inputs、scope）和 check_conclusion（claim、reason）。模型通过 assistant.tool_calls 发起最多一个请求，适配器校验函数名、唯一非空ID及完整参数后映射为内部 tool/check；不接受用 JSON 控制字段冒充原生调用。执行节点追加带匹配 tool_call_id 的真实 tool 结果，失败/超时/复用均保持实际状态。普通无工具回答使用仅含 content 的 JSON 对象；有原生调用时可附纯文本或 content JSON 数学正文。截断不执行或回放 tool_calls。此处只是协议检查，不是单步数学验证。

content 每个完整步骤按用户格式：
`步骤 n｜目标：…｜使用公式/定理：…（含适用前提）｜代入题面：…｜推导/计算：…｜得到：…`。
程序按独立数学步骤归档，不把整轮当成一步，显示时统一编号；正文、公式和关键代入不被摘要替代。

只有代码块外独立的 `### 最终答案`（也兼容无空格写法）以及其后的非空答案段才能正常退出。普通提及、引用行、代码示例、孤立 boxed、空标题和重复答案段不能作为正常结束信号。只剥离包住整个对象的展示包装，不挑最后一个框丢掉其他问项。

计算/检查请求优先于同轮最终答案段：先执行请求，丢弃过早候选。标记仅产生待审 candidate，不等于成功。问项完整性、数学正确性、义务闭合和答案集合一致性在外层验证，不设内层送审数学门槛。

## 4. 工具、正文尾部与截断续写

工具请求之前已有依据的完整步骤立即保存。尚未完成的最后一步进入 pending；真实工具结果返回后先补其剩余字段，再继续多个步骤，不能重复已保存正文。每次工具纯输入/输出、独立运行，无隐藏变量。

保留现有 BoundedCalculator 解释能力，增加受限赋值、for、if、assert、print、容器与推导式。独立可终止工作进程不携带客户端/密钥；禁用 import、属性访问、文件、网络、shell 和任意进程 API。使用时间、输出、内存、运算步数及容器规模限制。这不是通用 OS 安全沙箱，不开放任意 Python。

每次记录执行ID、内部版本/步骤、代码摘要、实际输入、scope、输出、断言次数和状态。success 仅是该代码在该范围的观测；error、timeout、unsupported、truncated 不得被称为验证通过。有限枚举不能自动升级为一般定理。macOS 无法设置 RLIMIT_AS 时保留 RSS、值规模、解释步数与父进程墙钟回收限制。

模型 length/max_tokens 响应不得执行计算/检查请求或采纳最终答案。如果能从完整 JSON 或截断的首个 content 字符串安全解析正文，保留此前完整步骤，最后尾部进入 pending，下一轮接着写；不得猜补请求参数。完全无法解析时仅做有界协议恢复。网络/API异常和不确定在途超时不走这种恢复。

## 5. 状态、上下文与回滚

| 数据 | 语义 |
| --- | --- |
| problem / constraint_ledger | 不可放宽的原题输入 |
| analysis / plan / obligations | 画像、路线、全部问项目标 |
| steps | 逐条数学正文，status=draft 表示尚待整题验证 |
| pending | 尚未写完的尾部，不是已证事实 |
| facts | 原题 given 与实际工具 observation；生成草稿不晋升为 lemma |
| evidence | 真实运行输入、范围、结果与状态 |
| conclusion_checks | 指定关键命题的模型检查及范围，不是确定事实、计算观测或整题通过票据 |
| candidate / ticket | 待审完整答案与当前内容指纹对应的有效验证票据 |
| repair_requirements / forbidden | 跨轮具体补证要求、错误禁用原因 |
| revision / internal step_id | 程序内部归属，不由模型照抄 |

工作视图保留原题、路线、完整有效草稿、公式条件、真实工具结果和 pending。没有局部审查时，不能为压缩上下文把草稿总结成确定引理。先整体省略可选参考材料，仍超预算则诚实返回未完成，不截断核心条件。完整证明保存与最终显示不依赖隐含历史聊天。

state 另外保存 solver_messages、solver_context_key 和 solver_rebuild_reason，并由 SolveOutput 回传父图及异常快照。首次进入或重建时发送完整 system 和十区块 user；正常续写追加已校验 assistant、原生工具结果（若有）和增量 user 要求，不反复复制全部推导。数学 steps/pending/facts/evidence/conclusion_checks 仍独立维护，是上下文重建的依据。会话不是跨题记忆，不进入平台 result/trace/debug_trace，也不保存私有 reasoning_content。

完整发送消息（含封装及工具定义）超过 context_chars 的85% 时提前重建；关键结论失败、版本、修复轮次、路线、义务或参考材料变化也重建。只从有效台账恢复，撤销后的错误 assistant 历史不能继续发送；历史失效记录可在明确标识的检查反馈中保留。重建仍超过硬预算则非成功退出，不悄悄删证明。协议恢复只追加有界重试要求，不回放无效/未配对的工具调用；网络异常不重试。

外层找到有证据的错误后保守撤销最早错误及后续可能相关步骤、旧计算适用性、candidate 和 ticket；保留不受影响的前段正文。没有足够依赖信息时不能默认后续独立。uncertain 只请求补证，不谎称命题已被反驳；修复要求直到整题通过才清空。

## 6. 外层完整验证与输出

verify 子图保留程序/协议检查、题面保真、数学审计三层。读取所有有效数学步骤的完整正文与证据；逐项检查定义域、量词、方向、端点、最值取等、所有解必要/充分/完备、选择真值集合及几何独立复核。

每个 fail issue 必须逐字引用实际步骤字段，列出真实步骤ID、题面/反例/复算证据、影响范围和可执行修改；保真错误另需逐字原题条件。无证据 fail 降 uncertain，不能据其撤销事实或指定替代答案。审计须覆盖全部有效步骤及原题义务，不能依赖生成器的 closes。

至少两个实际验证点，合计覆盖最小合法规模、边界、非平凡和独立复算；无法实例化时写原因和符号替代检查。程序枚举/计算声明须引用当前版本实际成功 evidence；具体失败和未决义务均阻止通过。局部数值等式可由白名单程序复算，不能用模型 pass 覆盖矛盾。

仅当前完整证明与候选得到有效票据后才调用最终答案确认。answer 必须逐字等于已审 candidate；变化则回到验证。render 确定性组装“问题分析→详细解题步骤→最终答案→关键验证点”，proof 保留完整证明，非 proof 按模式加框，选择题只输出全部正确字母串。

未完成仍保留四章节与实际已有正文，不框猜测、不伪造成功检查。solve_status 使用 success、timeout、failed，和 main.py 的 runner 契约一致。

## 7. 预算、客户端和诊断

保持官方注入客户端调用约定，不另建客户端、不读取本地密钥、不使用参考答案或 metadata.idx。单题总预算默认1200秒、返回预留60秒；默认修复3轮、生成轮次48、全局模型调用160、Python工具24、连续无进展3、单工具10秒；独立 LANGGRAPH_* 可配置。生成轮次按请求累计，与一轮含多少数学步骤无关；关键检查计入相同的总模型调用/时间预算，父子图和修复共享预算。连续无进展以预算非成功出口停止，不新增内层重规划或“无法继续”路径。

模型调用超时而底层是否结束无法确认时终止本题新增请求，不叠加恢复请求。异常/预算出口保留运行上下文中最后成功保存的状态，不把 pending 冒充完整结果。每题状态隔离；图可复用但不持有跨题事实。

trace 只保留有界阶段、调用、版本、工具状态、草稿记录、验证和回退摘要；可选 debug_trace 不泄露完整 prompt、原始响应、秘密、本地路径或隐藏答案。

## 8. 工程职责与完整提示词

### Solver 消息分层

`working` 仍为程序内部字典，首次或重建由 `prompts/solver_messages.py` 渲染十区块；正常轮次由 `domain/conversation.py` 追加消息并保存 state，不直接将整份状态 `json.dumps` 作为 Solver 的 user 内容。其他模型角色维持各自现有结构化输入协议。

system 包含领域专家角色、共享领域指导、当前题专项及修复纪律，以及 `solving.py` 中完整求解纪律、步骤格式、工具/关键结论检查协议和输出 schema；不缩短或以引用替代完整规则。

首次/重建的 user 固定依次包含【原题】【题面约束】【当前解题路线】【技能参考】【策略案例（仅方法参考）】【已有推导】【待续写内容】【真实计算结果】【关键结论检查反馈】【本轮要求】。正常轮次保留这些历史输入，只追加增量要求。无数据时仍保留标题并标明无；结构化记录按缩进展开，数学正文保留真实换行。原题及约束账本、事实来源、路线和全部义务、完整草稿、pending、真实观测范围/状态/输入/结果、当前有效与最近可能过期的检查反馈、跨轮修复要求及禁用原因均不可省略。参考案例只属于数据，不升级为 system 指令或本题事实。

工作视图预算按渲染后的 user 与动态 system 指导总长度计算，继续为完整静态规则、schema 和协议恢复预留空间；适配器最终检查整个实际消息列表与工具定义的序列化长度。超预算先重建并整体省略可选技能/案例，不能截断核心数学依据。

```text
langgraph_math/
  agent.py / config.py / context.py / state.py / schemas.py
  graph.py / routing.py
  nodes/analysis.py / retrieval.py / planning.py / repair.py / finalization.py
  subgraphs/solving/{graph,state,nodes,routing}.py
  subgraphs/solving/checking.py # 按需关键结论检查，返回同一生成循环
  subgraphs/verification/{graph,state,nodes,routing}.py
  domain/solve_text.py       # 多步分段、未完尾部、最终答案提取
  domain/condensation.py     # 原题、草稿、工具与修复上下文
  domain/ledger.py           # 有效正文、指纹与外层失效传播
  domain/answer_contract.py / audit_evidence.py / guidance.py
  domain/conclusion_checks.py # 检查范围、证据与反馈，非事实提交
  adapters/model.py / retrieval.py
  tools/python_executor.py / worker.py
  prompts/analysis.py / planning.py / solving.py / verification.py
  prompts/checking.py        # 关键检查的完整正文提示词
  rendering.py
```

graph 只装配节点与条件边，routing 不调用模型或工具，节点不隐藏整题 while 循环，领域逻辑不依赖图框架。状态局部替换更新，不原地修改嵌套映射；运行依赖通过 context 传入。父子图返回草稿、实际证据、候选及退出原因。

七个实际模型角色的提示词直接保存在各模块完整字符串正文中，不用简短说明或运行时拼接替代。保留 staged 原数学规则；仅适配多步批次、工具和答案标记协议。staged_rules.py 仅为测试原文对照。领域/专项/修复指导继续共享 staged_guidance.py，规划见目录及材料，审计只见无例题方法摘要和所选技能小结。完整映射见 docs/langgraph-prompt-migration.md。

## 9. 验证计划与边界

新增测试必须驱动真实编译图，覆盖：一次多步完成；多轮多步续写及编号；多步后工具暂停及真实结果；完整步骤保留与未完尾部续写；截断不能执行工具或定案；无最终标记预算退出；外层失败修复；选择/证明与四章节；无 step_review、commit 或 finish_gate；模型不回传管理编号。

继续运行平台初始化/solve/runner 契约、模型调用、staged 格式/配置和检索回归。Python 工具测试执行真实独立进程。未配置凭据则明确未做真实模型质量评测。

此前阶段记录为126、138、140项回归通过及301项纯规则提取对照，均为历史结果，不代表本次分段修订已验收。baseline trace 测试此前因系统 lagent0.2.4 不导出 Agent 而收集失败，固定 commit 在 Python3.13 的构建也失败；未修改 baseline 或系统依赖。

## 10. 本次分段方案实施结果

下列离线回归共152项通过（新模式及提示词测试66项、现有回归86项）：

```bash
python -m pytest -q \
  tests/test_langgraph_math.py tests/test_langgraph_prompt_migration.py \
  tests/test_user_agent_contract.py tests/test_runner_contract.py \
  tests/test_staged_runtime_config.py tests/test_staged_candidate_evidence.py \
  tests/test_staged_answer_extractor.py tests/test_custom2_program_checks.py \
  tests/test_custom2_model_call.py tests/test_hybrid_strategy_retrieval.py \
  tests/test_strategy_skills_retrieval.py
```

其中新增验收覆盖一轮六步完成、两轮各三步、工具前完整三步/暂停第四步/返回后继续第五步、截断JSON恢复、截断候选与工具禁用、无答案标记的预算退出、分段后仅撤销错误后缀及跨步骤选择真值汇总。测试使用脚本化客户端驱动真实父子图，Python工具使用真实独立工作进程。移除旧单步 schema、commit、单步审查规范化和送审义务门槛代码。

OpenSpec strict 与 git diff --check 通过。baseline trace 测试仍受前述 lagent.Agent 依赖问题阻塞，不计入152项。未执行真实模型/API质量评测；不据模拟结果保证真实数学正确率或调用耗时改善。

## 11. 按需关键结论检查

Solver 默认连续多步生成，普通代数变换不必暂停。只有后续大量推导依赖尚不确定的关键结论时，主动提交 check，立即交还控制权，收到反馈后继续。不预设每几步检查一次，也不检查每个公式。

check.claim 必须逐字位于当前数学正文或 pending，reason 说明送检原因。检查器读取原题、实际正文、必要依赖与真实工具证据。找不到明确对象时只返回 uncertain，不发起无对象模型调用。pass 需支持依据且没有未解决修改要求；fail 需以题面/反例/复算开头的具体否定证据和可执行修复要求，否则降 uncertain。

结果单独保存到 conclusion_checks，不提交 lemma，也不认为全部历史正确。检查通过后继续生成；uncertain 只补证、不撤销草稿；有证据的 fail 撤销对应草稿及保守影响后缀，清理 pending/候选和旧观测适用性，Solver 在同一循环修正后继续，不走新 blocked 或内层重规划分支。

记录绑定原输入指纹、版本及证明范围，相同上下文重复请求重用已有结果；旧版本或失效范围不能作为当前依据。最近一次反馈可保留作诊断，标明原版本。局部 pass 是模型审查，不是形式化认证或真实 Python 计算记录；整题审计仍独立检查全部证明。

每步仍严格使用“步骤 n｜目标：…｜使用公式/定理：…（含适用前提）｜代入题面：…｜推导/计算：…｜得到：…”；工具请求和检查报告另存，不能混入步骤字段。模型输出可验证数学依据，不要求暴露内部思考。

七个角色的完整提示词均直接保存正文。新增 checking.py 明确检查范围、数学纪律、通过/失败/不确定证据及输出要求；solving.py 详细说明主动暂停与返回后续写，不使用简短说明替代规则。

本次验收在第10节合并命令中增加 `tests/test_langgraph_conclusion_checks.py`，共166项通过：新增按需检查14项、既有新模式/提示词66项及原平台/staged/检索86项。新增测试驱动真实编译图，覆盖正常推导无检查开销、检查通过后多步及五字段格式、具体失败后同循环修正、uncertain 保留草稿、无法定位命题不调用模型、缺依据降级、重复请求复用、计算/检查互斥、过早答案不得跳过检查、截断不执行检查、预算出口、完整提示词正文、局部 pass 不覆盖整题失败及旧版本结果不复用。检查使用官方注入客户端的脚本化替身，不是线上数学质量评测；OpenSpec strict、编译和 diff 空白检查均通过。

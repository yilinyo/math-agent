## 上下文

动机与行为约束见 `proposal.md`。本次涉及多模块迁移、启动装配和 checkpoint 兼容，满足编写设计的条件；没有行为规格变更，沿用 `skip_specs: true`。

当前本地入口 `agent_platform/__main__.py` 和分布式入口 `deployment.py` 使用 `agent_platform.graph_runtime.LangGraphRuntime`。后者定义 GraphState、GraphCheckpoint、route 和 StateGraph，并通过 StagedAdapter 执行阶段。StagedAdapter 继承 `custom2.staged_runtime.StagedReasoningRuntime`，实际依赖 custom、custom2、action_graph、平台工具及展示函数，不能按目录名称认定其为无用历史代码。

当前图将所有阶段注册为条件边目标，节点公共包装负责取消、进度、线程调用、异常恢复、状态合并、脱敏及 checkpoint 提交。state 中的 adapter 保存部分运行时字段，是现有协议的一部分。

## 目标与非目标

- 将既有实现移动或机械提取到清晰的职责模块，保持函数调用、对象生命周期、共享状态和异常传播的原有语义。
- 独立节点入口能定位阶段实现；图文件能直接看到节点注册、条件边和编译。
- 所有新增 Web 编排与节点模块归入 `agent_platform/agent/`；`reasoning_agent/` 保留以前约定的结构与格式，本次不向其新增模块或搬迁其原实现。
- 兼容旧导入与持久化状态，不引入第二套推理流程。
- 不将字典 state 改成新模型，不增加黑板、状态 reducer、节点契约执行器或新的恢复算法，不顺带修复既有业务逻辑。

## 技术决策

### 1. 以当前 Web 实现建立迁移清单

实施前记录运行入口、公开符号、节点分支、提示词来源、相对资源路径、checkpoint 哈希输入和测试导入关系。以迁移前工作区的实际源码为基准，不以历史设计或未跟踪目录为基准。

`reasoning_agent/langgraph_final/` 和相关未跟踪测试保持原状，不能将其替换为本次目标目录；其现有问题单独记录，不能通过删除测试消除失败。

### 2. 目标模块与所有权

| 目标 | 来源与职责 |
| --- | --- |
| `agent_platform/agent/graph.py` | 提取现有图构建、节点注册及边声明；不负责平台持久化 |
| `agent_platform/agent/state.py` | 原样迁移 GraphState、GraphCheckpoint、CandidateCheckpoint 和相关阶段常量 |
| `agent_platform/agent/routing.py` | 原样提取 route，不修改任何分支和目标 |
| `agent_platform/agent/dependencies.py` | 描述现有模型、工具、运行上下文所需接口；不创建客户端或服务 |
| `agent_platform/agent/nodes/` | profile、retrieve、plan、solve、repair、emergency、tool、verify、arbitrate、finalize 独立入口 |
| `agent_platform/agent/stage_engine.py` | 承接原 StagedAdapter 的共享初始化、继承方法、候选管理及字段导入导出 |
| `agent_platform/agent/execution.py` | 提取现有节点公共包装与 TracedClient；通过注入的回调提交事件和 checkpoint |
| `agent_platform/agent/checkpoint.py` | 承接原状态装载、兼容校验及源码身份计算；规则及载荷保持原样 |
| `agent_platform/runtime.py` | 保留现有平台运行协议及 RuntimeContext，实现不借机重写 |
| `agent_platform/reasoning_runtime.py` | 平台适配入口，连接 RuntimeContext、图执行和 RuntimeResult |
| `agent_platform/bootstrap.py` | 提取本地与分布式共用的客户端、工具和 runtime 装配步骤 |
| `agent_platform/storage/` | 将当前 storage.py 的契约与内存实现分别归入 base.py、memory.py；Redis、PostgreSQL 等实现按依赖迁入 |
| `agent_platform/presentation/` | 按原函数职责拆出答案处理、公开区段提取与展示指令；通过包入口重导出旧符号 |

prompts、schemas、retrieval、tools 在 `agent_platform/agent/` 内按实际依赖提供入口：历史共享定义保持原位置，通过薄入口访问，禁止复制算法形成双份维护。既有检索实现保留，资源寻址须验证仍解析到同一文件。MCP、沙箱、进程隔离、会话文档存储仍由平台提供，节点通过现有注入接口调用。

选择保留共享 engine 而非将每个节点重写成完整独立 Agent，因为继承状态和候选缓存均会影响行为。节点提取保持公共前置解析、分支执行和公共尾部导出的原顺序；solve 与 repair 复用原有公共代码，保留各自入口，不改变对象创建次数。

### 3. 图定义显式化，但不修改边集合

graph.py 显式注册十个节点，并保留原 GRAPH_STAGES 顺序。为各节点声明与原来完全相同的条件目标集合，包括 terminal 到 END；不得以“只保留合理后继”为由收紧图。

保留 START 按 checkpoint.next_stage 选入口、预算不足时转 finalize、各节点公共包装计算 next_stage 的逻辑，以及递归限制 40。是否将条件边注册写成循环只影响表达，不改变图；不添加静态边与原条件边重复触发节点。

### 4. 兼容入口和依赖装配

agent_platform.graph_runtime 和 staged_adapter 保留薄兼容入口，重导出原公开符号和既有构造参数。兼容入口不维护另一套算法；涉及 monkeypatch、默认 adapter_factory 绑定或模块级常量的既有调用点须逐一对照，不能假定重导出即完全兼容。

storage.py 转为同名包时，用 storage/__init__.py 保持 TaskStore、MemoryTaskStore 等原符号；presentation 同理。迁移前调查实际导出列表，保留确被使用的接口。处理顺序为先建立新模块再调整调用方，避免同名文件与包长期并存。

bootstrap 只提取重复装配，保留本地与分布式各自的校验、初始化时机、工具身份和关闭次序。不把可选依赖变成无条件导入，不新增环境变量回退，不修改原有错误与默认值。

### 5. checkpoint 的源码身份兼容

当前 config_hash 依次纳入配置 JSON、客户端身份、工具身份及 function-calling 模式，再纳入指定源码目录、检索文件、索引清单和技能文档的路径与内容。只保留 WORKFLOW_VERSION 或跳过 config_hash 无法满足兼容要求。

采用受限的迁移兼容映射，同时保持 checkpoint 结构和版本不变：

1. 实施前为本次基准保存重算旧哈希所需的源码快照和路径清单，仅覆盖迁移影响的原文件；它们是经检查的兼容资源，不包含凭据、模型响应或运行数据，也不被 import 执行。
2. 为等价重构后的全部受影响源码建立受审查的内容指纹清单。仅在这些源码与清单完全匹配且行为对照通过时，启用旧路径与旧内容构成的逻辑源码视图。
3. 对未迁移的原哈希输入继续读取当前实际内容，按原次序与原配置、客户端和工具身份计算 config_hash。这样配置、技能、索引或未迁移代码变化仍按原规则使旧 checkpoint 不兼容。
4. 任一受保护的新源码变化即禁用该基准映射，使用包含全部当前执行源码的正常哈希；禁止运行时自动更新指纹或接受任意历史哈希。新代码必须纳入覆盖，不能因迁出 agent_platform 而退出身份校验。
5. 同一等价版本的新任务继续写入对应逻辑身份，原有载荷、版本、严格校验及任务、会话、题目、deadline 和样式绑定不变。旧版本不能接受来自不兼容新逻辑的 checkpoint。

这是一项仅服务于本次源码搬迁的有界兼容措施，不是通用的宽松旧版本恢复机制。测试必须覆盖原可恢复状态仍可恢复，及代码、提示词、配置、工具、身份或载荷不匹配仍被拒绝。快照保留增加少量维护成本，但避免直接冻结哈希掩盖后续业务变化。

### 6. 以确定性对照证明行为等价

先在原实现运行受控模型响应、工具替身、固定时间和随机标识，记录最小合成用例的预期请求与轨迹，再迁移。基准不得在迁移后自动重录；不使用真实题库、真实模型回复或历史聊天作为提交夹具。

对照内容包括系统及用户消息全文、请求参数、调用次数和次序、节点路径、各节点 state 增量及完整 checkpoint、工具参数与幂等标识、公开事件、最终答案和错误语义。只规范化固定清单中的非确定元数据；时间预算分支通过受控时间驱动，不删除 deadline 等业务字段来使测试通过。

测试路径覆盖：正常成功，低风险免模型复核，检索空结果或降级，文档证据，工具成功及失败，首次审计失败，1 至 3 轮 repair，修复上限，emergency，arbitrate，部分答案恢复，预算与返回期限收尾，阶段异常，finalize 异常，取消及各可恢复节点的 checkpoint 恢复。

测试分为 unit、integration、e2e；移动现有测试时同步修复跨测试导入、夹具位置、pytest 收集和 CI 路径，不为分类改变断言。保留既有前端回归。

## 风险与取舍

- 节点提取改变对象和缓存生命周期 -> 保持每阶段创建实例的原机制，逐节点对照导出字段及候选状态。
- 模块拆分出现循环依赖 -> 依赖接口不导入平台具体存储和服务；平台适配入口统一装配；兼容层只向新实现转发。
- 旧测试依赖模块身份或默认参数绑定 -> 记录实际使用点并验证注入、patch 和公开入口，不能只验证新路径。
- 测试工作区已有失败 -> 先记录基线，将已有失败与本次新增回归分别报告，不覆盖用户文件。
- 可选数据库环境缺失 -> 运行其余确定性验证，明确报告跳过项；只使用专用可丢弃数据库及隔离端口、存储命名空间，不停共享服务。
- 结构迁移无法获得严格行为等价证据 -> 暂缓该迁移步骤，不以“优化”名义调整原逻辑或放宽断言。

## 迁移与回退

1. 记录工作区和行为基准、原源码身份输入及运行依赖。
2. 先提取 state、路由及依赖接口，再拆节点和共享执行机制；每步保持旧导入可用并执行对应对照。
3. 将图构建迁入推理层，保留平台 runtime 适配，完成源码身份映射及恢复验证后再切换本地与分布式装配。
4. 整理存储、展示、共享代码入口和测试目录，更新 README、AGENTS.md 中的当前架构路径及相关 CI 引用。
5. 完成完整回归，报告各模块迁移关系、行为对照和环境限制；不执行提交、推送或服务切换。

迁移不修改数据库或既有 checkpoint。需要回退时仅恢复本次代码和入口变更，保留所有状态与用户原有修改；不使用破坏性 git 操作。部署仍遵循原运行管理方式，不在重构或测试过程中停止共享服务。

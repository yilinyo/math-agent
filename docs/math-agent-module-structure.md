# 数学推理应用模块结构

本次只迁移代码职责；现有流程、提示词、state、checkpoint 载荷和 Web 合约保持不变。

当前 Web 应用的新增图与节点统一位于 `agent_platform/agent/`。`reasoning_agent/` 保留以前约定的格式和原实现，作为共享库被引用，不承担本次新增的目录组织。

## 代码位置

| 原位置 | 当前实现 |
| --- | --- |
| agent_platform/graph_runtime.py 中的图注册 | agent_platform/agent/graph.py |
| 同文件中的 GraphState、GraphCheckpoint、CandidateCheckpoint | agent_platform/agent/state.py |
| 同文件中的 route | agent_platform/agent/routing.py |
| 同文件中的 checkpoint 校验、装载 | agent_platform/agent/checkpoint.py |
| 同文件中的图节点公共包装 | agent_platform/agent/execution.py |
| 同文件中的平台 runtime | agent_platform/reasoning_runtime.py |
| agent_platform/staged_adapter.py 中的共享方法 | agent_platform/agent/stage_engine.py |
| 同文件中的 TracedClient、ExecutionStopped | agent_platform/agent/execution.py |
| 同文件中的各阶段分支 | agent_platform/agent/nodes/，solve 与 repair 保留原共享实现 |
| agent_platform/storage.py | agent_platform/storage/base.py、memory.py |
| agent_platform/redis_store.py、postgres_store.py | agent_platform/storage/redis.py、postgres.py |
| agent_platform/presentation.py | agent_platform/presentation/instructions.py、sections.py、rendering.py |
| 启动入口的共用 runtime 装配 | agent_platform/bootstrap.py |

旧 graph_runtime、staged_adapter、redis_store、postgres_store 模块映射到当前实现，保留既有导入和被测试使用的 patch 目标。storage 与 presentation 的包入口重导出原有业务符号。可选数据库或模型依赖不会由 storage 包入口统一加载。

图仍有 profile、retrieve、plan、solve、tool、verify、repair、emergency、arbitrate、finalize 十个阶段，保留全部原条件目标集合、START 恢复选择和预算收尾规则。节点读取和返回的字段不变；公共包装仍按原顺序进行进度、线程执行、异常恢复、脱敏和 checkpoint 提交。实际调用链为 graph.py 注册节点、execution.py 执行公共包装、stage_engine.py 分发至 nodes 中对应的 run 函数。

prompts、schemas、retrieval 和 tools 提供可定位的共享入口；已有 custom、custom2、action_graph 及检索实现继续是对应共享逻辑的来源。没有复制或替换提示词、数学检查与检索算法。MCP、会话文档与工具隔离仍由平台实现并注入。

## 源码身份与恢复

旧 checkpoint 的 config_hash 包含源码路径和内容，直接搬迁会导致原可恢复任务失效。`agent_platform/agent/_compat/source_snapshot.json` 仅保存本次受影响的原应用源码，用于按旧顺序重算身份；运行时不会执行其中代码。

`migration.json` 列出经过行为对照的迁移源码指纹、原文件的移除路径与新增路径。只有快照和受保护源码都匹配时，`checkpoint_identity.py` 才使用旧逻辑路径视图。其余原哈希输入继续读取当前文件，配置、客户端与工具身份也继续参与计算。

修改受保护的任一源码会禁用映射，转为包含当前执行源码的身份；新增文件也参与哈希。不能为让业务变更兼容旧任务而重录指纹、增加任意旧哈希白名单或跳过校验。兼容资源损坏或缺失时不启用迁移映射。

## 验证方式

`tests/integration/test_structure_equivalence.py` 在测试中载入冻结的原源码作为对照，使用合成模型响应、固定时间和工具边界，对照模型请求、节点状态、事件、工具记录、修复轮次和恢复结果。冻结源码只在测试中执行，不注册为生产运行模式，不依赖未跟踪的 langgraph_final 实现。

既有测试按职责逐步迁入 unit、integration、e2e，原断言保留；pytest 的 pythonpath 保留跨测试模块的已有导入。CI 分组覆盖率指向搬迁后的实际实现，阈值保持原值。

## 实施前基线

工作区原有 `.agent-memory/`、`judge/`、`reasoning_agent/langgraph_final/`、相关未跟踪测试及 PDF 均不属于本次修改范围。

系统默认 Python 3.13 缺少 fastapi 等依赖，首次测试在收集时失败。使用现有 Python 3.11.18 环境完成实施前基线：1237 通过、40 失败、15 跳过，另有 105 个子测试通过。核心图测试 40 项通过。

基线失败包含 fakeredis 未安装 Lua 扩展导致的 EVAL 不可用、隔离解析与计算子进程的资源限制及其上层附件测试；PostgreSQL 测试需要专用可丢弃数据库。验证环境补充工具依赖时使用临时虚拟环境，不修改共享服务或业务异常处理。

## 最终验证结果

最终目录的定向回归 331 项通过；前端 76 项测试及构建通过；Ruff、mypy（15 个源文件）、OpenSpec 严格校验和差异空白检查通过。Fake 启动烟测完成会话、任务和 SSE 成功流程，隔离测试服务已关闭。

最终 CI 测试阶段为 1290 通过、35 失败、15 跳过，另有 105 个子测试通过；失败属于基线已有的 MCP、解析隔离、工具子进程及附件测试。CI 返回失败，后续覆盖率门槛未完成。独立全量 pytest 因客户端退出等待长时间未推进，在 245 秒后中断，得到 819 通过、1 失败、12 跳过。不能宣称全量 CI 通过。PostgreSQL 未使用共享数据库，缺少专用数据库的测试跳过。

`reasoning_agent/`、前端源码、任务 service 和用户历史数据没有本次修改，没有暂存、提交或推送。Prompt 原文仍在 `reasoning_agent/custom2/staged_prompts.py` 和 `text_prompts.py`；`agent_platform/agent/prompts/staged.py` 仅是兼容入口，尚未物理迁移原文，继承的 runtime 仍从原模块导入。

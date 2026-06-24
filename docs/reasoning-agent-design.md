# 数学推理 Agent 详细设计

## 1. 文档目的

本文档定义挑战杯数学推理 Agent 的首版工程方案，作为后续编码、测试和实验迭代的实现依据。

方案围绕正式评测接口设计：

```python
from user_agent import ReasoningAgent

agent = ReasoningAgent(client=official_client)
result = agent.solve(problem=problem, metadata=metadata)
```

正式实现必须保证：

- `ReasoningAgent.__init__` 接受平台注入的 `client`。
- `solve(problem, metadata)` 返回可 JSON 序列化的 `dict`。
- 返回值包含非空字符串 `final_response`。
- 不读取标准答案、隐藏数据、个人路径或平台内部信息。
- 不依赖题目顺序、固定进程、固定线程或跨题状态。
- 只依赖官方公开的 `client.chat(messages, temperature, max_tokens)` 接口。

本文档描述的是首版稳健架构，不追求一次性加入所有高级机制。后续实验应建立在接口稳定、预算可控和结果可复现的基础上。

## 2. 设计目标

### 2.1 核心目标

1. 提高数学题最终答案正确率。
2. 对复杂题提供分析、工具辅助、独立验证和纠错能力。
3. 对简单题减少无意义的多轮调用。
4. 严格控制模型调用次数、工具循环次数和输出体积。
5. 在模型返回异常、JSON 格式错误或工具失败时仍可降级输出。
6. 保证同一个 Agent 实例被并发调用时不发生状态污染。
7. 保持实现简单透明，便于快速调整提示词和进行消融实验。

### 2.2 非目标

首版不实现以下能力：

- 跨题长期记忆。
- 向量数据库或检索历史题目。
- 多个 Agent 之间的自由对话。
- 模型生成任意 Python 代码并执行。
- 网络搜索或外部知识库访问。
- 工作流持久化、断点恢复或人工审批。
- 对 LangGraph、LangChain 或 Lagent 的运行时依赖。

## 3. 技术选型

### 3.1 最终选择

采用：

- 自研有限状态机。
- 角色化 Subagent 处理器。
- 单题临时工作记忆。
- 官方 `client.chat` 直接调用。
- SymPy 白名单数学工具。
- 统一模型调用和错误处理入口。

整体流程如下：

```text
Analyzer
   |
   v
Solver <------> Math Tools
   |
   v
Verifier
   | PASS
   +----------------------> Extractor ---> DONE
   |
   | REVISE / REJECT
   v
Repairer <-----> Math Tools
   |
   v
Verifier
   |
   v
Extractor ---> DONE
```

### 3.2 不使用 LangGraph 的原因

LangGraph 适合复杂动态工作流、持久化状态、断点恢复、人工介入和长时间运行的多节点任务。当前问题只有有限状态和较短生命周期，可以通过 `Enum + dataclass + while` 清楚表达。

引入 LangGraph 不会直接提高数学推理能力，却会增加：

- 官方 client 适配工作。
- 依赖安装和版本兼容风险。
- 状态序列化与调试复杂度。
- 调用预算统计和异常降级的间接性。
- 隐式消息历史或预制节点行为的排查成本。

裸 LangGraph 本身不会必然污染提示词，但在当前规模下，即使手动控制每个节点的消息，剩余编排收益仍然有限。

### 3.3 不使用 LangChain 的原因

LangChain 的预制 Agent、ReAct scratchpad、memory 和工具描述可能自动注入额外上下文，例如：

```text
Thought -> Action -> Observation -> Final Answer
```

对于数学推理，这类通用协议可能产生以下副作用：

- 模型为了遵守 Agent 格式而分散解题注意力。
- 简单题也倾向调用工具。
- 工具 schema、解析错误和历史日志占用上下文。
- Verifier 继承 Solver 的完整历史后产生锚定效应。
- 框架答案格式与比赛 `final_response` 格式发生冲突。

本方案直接构造每次调用的 `messages`，确保角色之间只传递必要信息。

### 3.4 不以 Lagent 为核心的原因

当前 baseline 使用 Lagent 封装模型和角色，但正式评测只保证官方 client 的公开 `chat` 方法，不保证本地 `InternChatClient` 类型，也不保证 Lagent 所需的其他隐含接口。

直接调用 `client.chat` 可以：

- 减少类型和协议适配层。
- 避免依赖本地 `llm_client.py`。
- 精确控制消息、参数、调用次数和错误处理。
- 更贴近正式评测的最低契约。

## 4. 总体架构

建议代码结构：

```text
user_agent.py
requirements.txt
reasoning_agent/
  ├── factory.py
  ├── runner/
  │   ├── agent.py
  │   ├── task_runner.py
  │   ├── config.py
  │   ├── state.py
  │   ├── errors.py
  │   ├── runner/
  │   │   ├── loop.py
  │   │   ├── events.py
  │   │   ├── policy.py
  │   │   └── context.py
  │   ├── tools/
  │   ├── prompts/
  │   ├── parsers/
  │   └── verifier/
  ├── baseline/
  │   └── agent.py
  └── __init__.py
tests/
```

各模块职责：

| 模块 | 职责 |
| --- | --- |
| `user_agent.py` | 平台入口，只从 `reasoning_agent.factory` 导出 `ReasoningAgent` |
| `reasoning_agent/factory.py` | 唯一顶层 agent 入口，解析模式并创建具体实现 |
| `reasoning_agent/custom/agent.py` | `CustomAgent` 实现，保存官方 client、配置和工具注册表，承接 `solve()` |
| `reasoning_agent/custom/task_runner.py` | 单题生命周期 runner，组织生成、验证、修复、抽取和降级 |
| `reasoning_agent/baseline/agent.py` | `BaselineAgent` 实现，用于本地对比旧版 lagent generate-verify-select baseline |
| `reasoning_agent/custom/runner/loop.py` | 受控 ReAct loop，执行 `model -> tool -> observation -> model -> final` |
| `reasoning_agent/custom/runner/events.py` | 定义模型事件，如 `ToolCall`、`Observation`、`FinalAnswer`、错误事件 |
| `reasoning_agent/custom/runner/policy.py` | 管理 step 上限、模型调用预算、工具调用预算、停止条件 |
| `reasoning_agent/custom/runner/context.py` | 单题 loop 上下文，保存 messages、工具结果、候选答案和 trace |
| `reasoning_agent/custom/tools/` | 白名单数学工具、工具注册、参数校验、执行和结果序列化 |
| `reasoning_agent/custom/prompts/` | 系统提示词、工具调用提示词和消息构造模板 |
| `reasoning_agent/custom/parsers/` | 解析工具调用、最终答案和模型 JSON 片段 |
| `reasoning_agent/custom/verifier/` | 独立答案验证、修复提示和候选选择辅助逻辑 |
| `reasoning_agent/custom/config.py` | 静态配置、调用预算、温度、输出长度限制 |
| `reasoning_agent/custom/state.py` | 单题阶段状态、候选结构和必要枚举 |
| `reasoning_agent/custom/errors.py` | 内部异常类型，便于统一降级和 trace 记录 |
| `tests/` | 接口契约、runner loop、工具、解析、并发和端到端测试 |

该结构明确区分三层循环：

```text
平台或本地 runner
  -> ReasoningAgent.solve()
      -> TaskRunner 管理单题生命周期
          -> Controlled ReAct loop 管理模型与工具交互
```

正式评测只直接依赖根目录的 `user_agent.py`。`main.py`、`llm_client.py`、`sample_data/` 和 `tests/` 只用于本地开发，不应被正式推理逻辑依赖。

## 5. 正式接口设计

### 5.1 初始化

```python
class ReasoningAgent:
    def __init__(self, client, *args, **kwargs):
        self.client = client
        self.config = AgentConfig()
        self.tools = build_tool_registry()
```

初始化阶段只允许：

- 保存官方 client。
- 创建轻量配置。
- 构造静态工具注册表。
- 加载随提交包提供的提示词文本。

初始化阶段禁止：

- 调用模型。
- 访问网络。
- 读取隐藏文件或个人绝对路径。
- 创建依赖题目顺序的缓存。
- 假设 Agent 实例会长期存在。

### 5.1.1 Agent 模式选择

根目录 `user_agent.py` 暴露的是可配置入口 `ReasoningAgent`。它只负责保持平台接口稳定，并委派给 `reasoning_agent/factory.py` 选择具体实现。默认模式为 `custom`，即使用 `reasoning_agent/custom/` 中的 `CustomAgent`。

本地实验可以通过构造参数选择实现：

```python
agent = ReasoningAgent(client=client, agent_mode="custom")
agent = ReasoningAgent(client=client, agent_mode="baseline")
```

也可以通过环境变量选择：

```bash
export REASONING_AGENT_MODE=baseline
```

支持的模式：

| 模式 | 实现 | 用途 |
| --- | --- | --- |
| `custom` | `custom/CustomAgent`，内部组合 `TaskRunner + ToolUseRunner` | 默认提交入口 |
| `baseline` | `baseline/BaselineAgent` | 对比旧版 lagent generate-verify-select baseline |

正式提交建议保持默认 `custom`，避免依赖实验环境变量。`baseline` 依赖 `lagent`，只有安装完整依赖后才能使用。

### 5.2 求解入口

```python
def solve(self, problem: str, metadata: dict) -> dict:
    ...
```

输入规范化：

- `problem` 转成字符串并去除首尾空白。
- `metadata` 不是字典时按空字典处理。
- `metadata.get("idx")` 只用于 trace 标识。
- 不读取 `metadata["answer"]`。

输出格式：

```python
{
    "final_response": "72",
    "trace": [
        {
            "step": "analyze",
            "content": {
                "subject": "abstract_algebra",
                "answer_type": "integer"
            }
        }
    ]
}
```

`final_response` 必须：

- 是 `str`。
- `strip()` 后非空。
- 面向判分，不包含异常堆栈或 Python 对象表示。

## 6. 状态机设计

### 6.1 状态定义

```python
from enum import Enum


class State(str, Enum):
    ANALYZE = "analyze"
    SOLVE = "solve"
    TOOL = "tool"
    VERIFY = "verify"
    REPAIR = "repair"
    EXTRACT = "extract"
    FALLBACK = "fallback"
    DONE = "done"
```

### 6.2 状态职责

| 状态 | 职责 |
| --- | --- |
| `ANALYZE` | 识别题型、目标、答案类型、策略、风险和工具需求 |
| `SOLVE` | 生成初始候选，或请求执行白名单工具 |
| `TOOL` | 校验并执行工具，把结果放回单题上下文 |
| `VERIFY` | 独立检查候选答案和关键步骤 |
| `REPAIR` | 根据验证问题修正候选或采用独立方法重解 |
| `EXTRACT` | 选择最佳候选并提取稳定的最终答案 |
| `FALLBACK` | 无完整候选时执行最低限度降级 |
| `DONE` | 停止状态机并返回结果 |

### 6.3 状态转移

```text
ANALYZE -> SOLVE

SOLVE:
  返回合法工具请求        -> TOOL
  返回完整候选            -> VERIFY
  调用失败且已有候选      -> EXTRACT
  调用失败且没有候选      -> FALLBACK

TOOL:
  工具执行结束            -> SOLVE 或 REPAIR
  达到工具轮次上限        -> VERIFY 或 EXTRACT

VERIFY:
  PASS 且独立结果一致     -> EXTRACT
  REVISE/REJECT           -> REPAIR
  修正次数或预算耗尽      -> EXTRACT

REPAIR:
  返回工具请求            -> TOOL
  返回修正候选            -> VERIFY
  调用失败                -> EXTRACT

EXTRACT:
  成功获得非空答案        -> DONE
  无法提取                -> FALLBACK

FALLBACK:
  产生稳定非空结果        -> DONE
```

### 6.4 三层调度循环

本方案包含三层循环，职责不同：

| 层级 | 位置 | 职责 |
| --- | --- | --- |
| 评测或本地 runner | 平台 runner / `main.py` | 多题调度、并发、异常归一化、结果收集 |
| 单题 TaskRunner | `reasoning_agent/custom/task_runner.py` | 管理一道题的生成、验证、修复、抽取和降级 |
| 受控 ReAct loop | `reasoning_agent/custom/runner/loop.py` | 管理模型与工具的多轮交互，直到得到候选答案或触发停止条件 |

`ReasoningAgent.solve()` 只承接平台接口，并把单题工作交给 `TaskRunner`：

```python
def solve(self, problem: str, metadata: dict) -> dict:
    runner = TaskRunner(
        client=self.client,
        tools=self.tools,
        config=self.config,
    )
    result = runner.run(problem=problem, metadata=metadata)
    final_response = normalize_final_response(result.final_response)
    return {
        "final_response": final_response,
        "trace": make_json_safe(result.trace),
    }
```

`TaskRunner` 负责单题生命周期。首版可以采用轻量阶段状态，而不把模型与工具交互细节塞进同一个状态机：

```python
def run(self, problem: str, metadata: dict) -> TaskResult:
    ctx = TaskContext.create(problem, metadata)

    try:
        candidate = self.tool_use_runner.run(ctx)
        ctx.candidates.append(candidate)

        verification = self.verifier.verify(ctx, candidate)
        if verification.needs_repair and ctx.can_repair():
            repaired = self.repairer.repair(ctx, candidate, verification)
            if repaired:
                ctx.candidates.append(repaired)

        ctx.final_response = self.finalizer.extract(ctx.candidates)
    except Exception as exc:
        record_error(ctx, exc)
        ctx.final_response = fallback_answer(ctx)

    return TaskResult(
        final_response=ctx.final_response,
        trace=ctx.trace,
    )
```

受控 ReAct loop 只处理 `model -> tool -> observation -> model -> final`：

```python
def run(self, ctx: RunnerContext) -> Candidate:
    while not ctx.done:
        if self.policy.should_stop(ctx):
            return fallback_candidate(ctx)

        raw = self.chat(ctx.messages)
        event = parse_model_event(raw)

        if event.type == "tool_call":
            result = self.tool_executor.execute(event.tool_call)
            ctx.add_observation(result)
            continue

        if event.type == "final_answer":
            return Candidate(answer=event.answer, source="tool_loop")

        ctx.add_error("invalid_model_event", raw)

    return fallback_candidate(ctx)
```

必须同时设置 `max_state_steps`、`max_loop_steps`、`max_model_calls`、`max_tool_calls` 和 `max_repair_rounds`，防止单题阶段和工具交互循环出现死循环。

## 7. 单题工作记忆

### 7.1 上下文结构

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SolveContext:
    problem: str
    idx: str | int | None

    state: State = State.ANALYZE
    return_state_after_tool: State = State.SOLVE

    total_steps: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    tool_rounds: int = 0
    repair_rounds: int = 0

    analysis: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    pending_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)

    raw_responses: list[str] = field(default_factory=list)
    final_response: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
```

### 7.2 内存边界

`SolveContext` 是唯一允许保存动态求解状态的位置。它必须：

- 在每次 `solve()` 内创建。
- 不挂载到 `self`。
- 不与其他题目共享。
- 在 `solve()` 返回后自然销毁。

`ReasoningAgent` 实例只保存：

- 官方 client。
- 静态配置。
- 不含题目状态的工具注册表。

这样即使平台并发调用同一个 Agent 实例，也不会出现候选、工具结果或 trace 串题。

### 7.3 不引入长期记忆

长期记忆对本任务收益有限，且存在以下风险：

- 正式环境可能每题重建进程或 Agent。
- 题目调用顺序不固定。
- 多线程下缓存可能互相污染。
- 历史错误答案可能影响新题。
- 读取历史样例可能产生答案泄漏嫌疑。
- 额外持久化依赖降低提交可复现性。

因此只保留单题工作记忆，不建立跨题经验库。

## 8. 角色化 Subagent

Subagent 在本方案中是“不同职责的模型调用处理器”，不是拥有独立运行时、长期记忆或自由通信能力的 Agent。

所有 Subagent：

- 共用 `ReasoningAgent._chat()`。
- 共用单题预算。
- 使用不同 system prompt。
- 使用明确的最小输入。
- 返回受控 JSON 协议。
- 不自动继承其他角色的消息历史。

### 8.1 Analyzer

职责：

- 识别数学领域。
- 明确所求目标。
- 判断答案类型。
- 提取关键条件。
- 给出建议策略和潜在陷阱。
- 建议可能需要的工具。

输入：

```text
原始题目
```

输出：

```json
{
  "subject": "calculus",
  "answer_type": "number",
  "strategy": "使用微积分基本定理和反函数定义",
  "key_conditions": [
    "积分下限为 x",
    "f_inv 是 f 的反函数"
  ],
  "risks": [
    "注意积分下限求导产生负号"
  ],
  "suggested_tools": []
}
```

约束：

- 固定调用一次。
- 使用低温度。
- 只输出策略摘要，不尝试生成冗长完整证明。
- JSON 解析失败后使用默认分析，不重复调用。

### 8.2 Solver

职责：

- 根据题目和分析生成初始候选。
- 选择直接推理或请求工具。
- 给出关键推导摘要和最终候选。
- 不评价自身答案正确性。

输入：

```text
原始题目
Analyzer 的策略摘要
当前轮可用的必要工具结果
```

直接答案协议：

```json
{
  "action": "answer",
  "reasoning_summary": "由 F'(x)=-f_inv(x)，且 f(-1)=5，所以 F'(5)=-1。",
  "final_candidate": "-1"
}
```

工具请求协议：

```json
{
  "action": "tool",
  "tool_calls": [
    {
      "name": "simplify_expression",
      "arguments": {
        "expression": "(x^2 - 1)/(x - 1)"
      }
    }
  ]
}
```

约束：

- `action` 只允许 `answer` 或 `tool`。
- 每轮最多请求两个工具。
- 不接受模型自行声明的新工具。
- `final_candidate` 为空时不创建候选。
- 工具结果只在下一次 Solver 调用中传入。

### 8.3 Verifier

职责：

- 独立求解或重算关键步骤。
- 检查条件遗漏、符号、计算和逻辑。
- 判断候选是否满足题目要求。
- 给出可定位的错误和修正建议。

输入：

```text
原始题目
候选最终答案
候选关键步骤摘要
必要且可信的工具结果
```

Verifier 不接收：

- Analyzer 的主观置信度。
- Solver 的完整消息历史。
- Solver 的隐藏长推理。
- 之前的格式解析错误日志。
- 无关工具输出。

输出：

```json
{
  "verdict": "PASS",
  "issues": [],
  "correction_hint": "",
  "independent_result": "-1"
}
```

`verdict` 只允许：

- `PASS`
- `REVISE`
- `REJECT`

转移规则：

- `PASS` 且 `independent_result` 与候选一致：进入提取。
- `PASS` 但独立结果明显冲突：强制视为 `REVISE`。
- `REVISE`：把具体问题交给 Repairer。
- `REJECT`：要求 Repairer 使用独立方法重解。
- 输出无法解析：按 `REVISE` 处理，但受预算约束。

### 8.4 Repairer

职责：

- 根据 Verifier 定位的问题修正候选。
- 必要时切换到不同解法。
- 可以请求白名单工具。
- 生成新的候选，而不是原地覆盖旧候选。

输入：

```text
原始题目
当前候选答案
当前候选关键步骤
Verifier 的 issues
Verifier 的 correction_hint
相关工具结果
```

Repairer 不接收完整历史，只接收修复所需信息。

输出协议与 Solver 相同：

- `action=answer`：创建来源为 `repair` 的新候选。
- `action=tool`：进入工具状态，执行后返回 Repairer。

首版最多修正两轮。

### 8.5 Extractor

Extractor 不是默认模型 Subagent，而是“本地规则优先、模型兜底”的答案整理模块。

处理顺序：

1. 选择最佳候选。
2. 读取候选的 `final_candidate`。
3. 去除代码块和明显包装。
4. 保留 LaTeX、分数、集合、区间和方程原意。
5. 非空时直接作为 `final_response`。
6. 只有无法从候选分离答案时，才调用模型抽取一次。

Extractor 不应把完整推理直接作为最终答案，除非无法获得更精确的判分表达。

## 9. 提示词与上下文隔离

### 9.1 污染风险

提示词污染不只指 system prompt 中出现错误指令，也包括：

- 自动注入通用 ReAct 格式。
- 重复附带完整消息历史。
- 将失败尝试持续传给后续角色。
- 将解析错误提示追加到数学上下文。
- 把冗长工具 schema 放入每次调用。
- Verifier 过度继承 Solver 的推理路径。

这些内容会产生上下文噪声和锚定效应。

### 9.2 隔离原则

每个角色重新构造消息：

```python
analyzer_messages = [
    {"role": "system", "content": ANALYZER_PROMPT},
    {"role": "user", "content": problem},
]

solver_messages = [
    {"role": "system", "content": SOLVER_PROMPT},
    {"role": "user", "content": build_solver_input(ctx)},
]

verifier_messages = [
    {"role": "system", "content": VERIFIER_PROMPT},
    {"role": "user", "content": build_verifier_input(ctx, candidate)},
]
```

禁止使用全局共享的：

```python
shared_history.extend(all_previous_messages)
```

### 9.3 最小上下文原则

- Analyzer 只看原题。
- Solver 看原题、策略摘要和当前必要工具结果。
- Verifier 看原题、候选答案和关键步骤。
- Repairer 看原题、候选和明确验证问题。
- Extractor 只看被选候选和答案形式。

原题必须保持原文，不让上游角色改写后的题目替代原题。

### 9.4 结构化输出

结构化 JSON 用于降低解析歧义，但不应设置过于复杂的 schema。

解析顺序：

1. 直接 `json.loads`。
2. 提取 Markdown JSON 代码块。
3. 提取首个平衡 JSON 对象。
4. 使用角色相关的纯文本降级解析。
5. 仍失败则记录错误并进入对应降级状态。

不要为了修复格式无限重试模型。Analyzer 格式失败不重试，其他角色最多允许一次有预算约束的格式修复。

## 10. 候选管理

### 10.1 候选结构

```python
@dataclass
class Candidate:
    candidate_id: int
    answer: str
    reasoning_summary: str
    source: str
    verification: dict = field(default_factory=dict)
```

JSON 形式：

```json
{
  "candidate_id": 1,
  "answer": "-1",
  "reasoning_summary": "使用反函数定义得到 f_inv(5)=-1",
  "source": "repair",
  "verification": {
    "verdict": "PASS",
    "issues": [],
    "independent_result": "-1"
  }
}
```

### 10.2 生成策略

首版不固定生成多个候选。正常路径只生成一个候选，然后独立验证。

只有以下情况才生成新候选：

- Verifier 返回 `REVISE`。
- Verifier 返回 `REJECT`。
- Verifier 的独立答案与候选冲突。
- 工具结果直接否定当前候选。

这样可以把调用预算集中在真正存在不确定性的题目上。

### 10.3 选择优先级

最终候选按照以下顺序选择：

1. 最新且通过 `PASS` 的候选。
2. 与 Verifier 独立结果一致的候选。
3. 验证问题最少的修正候选。
4. 最新的非空候选。
5. 初始候选。

Verifier 给出的数值置信度只用于 trace，不作为主要选择依据，避免模型虚假高置信度影响结果。

## 11. 数学工具设计

### 11.1 工具范围

首版白名单工具：

- `simplify_expression`
- `factor_expression`
- `expand_expression`
- `solve_equation`
- `differentiate`
- `integrate`
- `numeric_evaluate`
- `polynomial_roots`
- `matrix_compute`
- `check_equivalence`

工具主要用于机械计算和结果复核，不承担完整题意理解。

### 11.2 注册协议

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    function: Callable
    required_arguments: tuple[str, ...]
    optional_arguments: tuple[str, ...] = ()


def build_tool_registry() -> dict[str, ToolSpec]:
    return {
        "simplify_expression": ToolSpec(
            name="simplify_expression",
            function=simplify_expression,
            required_arguments=("expression",),
        ),
    }
```

### 11.3 安全边界

禁止：

- `eval` 和 `exec`。
- shell 命令。
- 文件读取和写入。
- 网络访问。
- 动态导入模型指定模块。
- 运行模型生成的任意 Python。

必须检查：

- 工具名在白名单中。
- 参数是 JSON 基础类型。
- 参数名符合工具 schema。
- 表达式长度未超过限制。
- 变量数量和矩阵规模未超过限制。
- 工具结果长度未超过限制。

### 11.4 工具结果协议

成功：

```json
{
  "tool": "simplify_expression",
  "ok": true,
  "result": "x + 1"
}
```

失败：

```json
{
  "tool": "simplify_expression",
  "ok": false,
  "error": {
    "type": "ValueError",
    "message": "expression is too long"
  }
}
```

异常对象本身不能放入上下文或最终 trace。

### 11.5 循环控制

- 总工具调用最多 6 次。
- 工具轮次最多 3 轮。
- 单轮最多两个工具。
- 相同工具和相同参数不得重复执行。
- 工具失败后不得用完全相同参数重试。
- 工具预算耗尽后强制进入验证或提取。

工具调用去重键可使用：

```python
tool_key = json.dumps(
    {"name": name, "arguments": arguments},
    ensure_ascii=False,
    sort_keys=True,
)
```

## 12. 模型调用预算

### 12.1 总预算

单题模型调用硬上限为 10 次，但正常题目目标为 3 到 5 次。

| 阶段 | 常规次数 | 最大次数 |
| --- | ---: | ---: |
| Analyzer | 1 | 1 |
| Solver | 1-2 | 3 |
| Verifier | 1-2 | 3 |
| Repairer | 0-2 | 2 |
| Extractor | 0 | 1 |

各阶段上限和总上限同时生效。

### 12.2 统一调用入口

任何模块不得直接调用 `self.client.chat`，必须经过统一入口：

```python
def _chat(
    self,
    ctx: SolveContext,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    role: str,
) -> str:
    if ctx.model_calls >= self.config.max_model_calls:
        raise ModelBudgetExceeded("model call budget exhausted")

    ctx.model_calls += 1

    response = self.client.chat(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if not isinstance(response, str) or not response.strip():
        raise EmptyModelResponse("client.chat returned empty content")

    return response.strip()
```

统一入口负责：

- 调用计数。
- 参数约束。
- 返回类型检查。
- 空响应检查。
- 响应长度限制。
- 异常归一化。
- trace 中的调用摘要。

### 12.3 重试规则

官方 client 可能已经实现重试，因此 Agent 内部不应进行无上限重试。

建议：

- 网络类或临时模型异常最多额外重试一次。
- 重试计入模型调用预算。
- JSON 格式错误不默认重发完整请求。
- 预算不足时立即降级，不继续尝试格式修复。

## 13. 错误处理与降级

### 13.1 错误分类

内部统一错误类型：

- `ModelBudgetExceeded`
- `EmptyModelResponse`
- `InvalidModelResponse`
- `InvalidToolRequest`
- `ToolBudgetExceeded`
- `ToolExecutionError`
- `StateStepLimitExceeded`

trace 中只记录简单结构：

```json
{
  "step": "error",
  "content": {
    "state": "verify",
    "type": "InvalidModelResponse",
    "message": "missing verdict"
  }
}
```

### 13.2 降级优先级

出现异常时按以下顺序处理：

1. 使用最后一个通过验证的候选。
2. 使用与 Verifier 独立结果一致的候选。
3. 使用问题最少的修正候选。
4. 使用最新非空候选。
5. 从保存的模型纯文本响应中本地抽取答案。
6. 返回稳定的非空失败说明。

最后一级可以是：

```text
无法确定唯一答案
```

它不能提高正确率，但能保证接口契约不被破坏。

### 13.3 防止无限循环

同时限制：

- `max_model_calls = 10`
- `max_tool_calls = 6`
- `max_tool_rounds = 3`
- `max_repair_rounds = 2`
- `max_state_steps = 24`

任何预算耗尽都必须进入 `EXTRACT` 或 `FALLBACK`，不能回到原状态。

## 14. 最终答案抽取

### 14.1 本地抽取优先

如果候选已经包含：

```json
{"final_candidate": "-1/8"}
```

则直接清理并使用，不需要额外模型调用。

允许清理：

- 首尾空白。
- Markdown 代码块外壳。
- `最终答案：`、`Answer:` 等固定前缀。
- 无意义的外围引号。

不应激进修改：

- LaTeX 结构。
- 正负号。
- 分数括号。
- 集合和区间边界。
- 方程中的变量和等号。
- 多个答案之间的对应关系。

### 14.2 模型抽取条件

只有以下情况才调用 Extractor 模型：

- 候选没有独立 `final_candidate`。
- 候选答案与推理混在一起且本地规则无法可靠分离。
- 题目要求多项答案，必须保持明确映射关系。

模型抽取输入只包含原题、答案类型和被选候选，不包含整个 trace。

## 15. Trace 设计

### 15.1 目标

trace 用于：

- 定位状态转移错误。
- 检查调用预算。
- 理解工具使用。
- 分析验证和修复是否有效。
- 支持后续消融实验。

trace 不替代 `final_response`。

### 15.2 推荐格式

```json
[
  {
    "step": "analyze",
    "content": {
      "subject": "complex_analysis",
      "answer_type": "expression",
      "suggested_tools": ["simplify_expression"]
    }
  },
  {
    "step": "solve",
    "content": {
      "candidate_id": 0,
      "answer": "-1/8"
    }
  },
  {
    "step": "verify",
    "content": {
      "candidate_id": 0,
      "verdict": "PASS",
      "issues": []
    }
  },
  {
    "step": "finalize",
    "content": {
      "answer": "-1/8",
      "model_calls": 3,
      "tool_calls": 0,
      "repair_rounds": 0
    }
  }
]
```

### 15.3 体积和安全限制

trace 不保存：

- API key 或 Authorization header。
- client 对象。
- 完整异常对象。
- 个人绝对路径。
- 完整长模型响应。
- 大型 SymPy 对象。
- 重复工具日志。

模型响应只保存摘要或截断片段。所有 trace 在返回前通过 `make_json_safe()` 转换。

## 16. 并发与线程安全

本地 runner 会通过线程并发调用同一个 Agent 实例。正式平台也可能使用多线程或多进程。

实现要求：

- `SolveContext` 必须是局部变量。
- 不使用 `self.current_problem`、`self.trace`、`self.candidates` 等动态字段。
- 工具注册表只读。
- 配置对象初始化后不修改。
- 不使用全局可变消息历史。
- 不用 `idx` 作为 session 状态的唯一来源。
- 不依赖请求完成顺序。

如果第三方数学库存在全局状态，应避免在运行时修改其全局配置。

## 17. 配置设计

```python
@dataclass(frozen=True)
class AgentConfig:
    max_model_calls: int = 10
    max_tool_calls: int = 6
    max_tool_rounds: int = 3
    max_repair_rounds: int = 2
    max_state_steps: int = 24

    analyzer_temperature: float = 0.1
    solver_temperature: float = 0.3
    verifier_temperature: float = 0.0
    repairer_temperature: float = 0.2

    analyzer_max_tokens: int = 1024
    solver_max_tokens: int = 4096
    verifier_max_tokens: int = 2048
    repairer_max_tokens: int = 4096
    extractor_max_tokens: int = 512

    max_response_chars: int = 30000
    max_trace_chars: int = 12000
    max_expression_chars: int = 4000
```

首版使用静态配置，避免从个人环境变量读取关键策略。后续实验可以通过构造函数 `kwargs` 覆盖，但不能破坏官方默认初始化方式。

## 18. 关键伪代码

### 18.1 Analyze

```python
def _handle_analyze(self, ctx: SolveContext) -> State:
    try:
        raw = self._chat(
            ctx,
            build_analyzer_messages(ctx.problem),
            temperature=self.config.analyzer_temperature,
            max_tokens=self.config.analyzer_max_tokens,
            role="analyzer",
        )
        ctx.analysis = parse_analysis(raw)
    except Exception as exc:
        record_error(ctx, exc)
        ctx.analysis = default_analysis()

    append_analysis_trace(ctx)
    return State.SOLVE
```

### 18.2 Solve

```python
def _handle_solve(self, ctx: SolveContext) -> State:
    raw = self._chat(
        ctx,
        build_solver_messages(ctx),
        temperature=self.config.solver_temperature,
        max_tokens=self.config.solver_max_tokens,
        role="solver",
    )
    action = parse_solver_action(raw)

    if action.kind == "tool":
        ctx.pending_tool_calls = validate_tool_requests(action.tool_calls)
        ctx.return_state_after_tool = State.SOLVE
        return State.TOOL

    candidate = create_candidate(action, source="initial")
    ctx.candidates.append(candidate)
    append_candidate_trace(ctx, candidate)
    return State.VERIFY
```

### 18.3 Verify

```python
def _handle_verify(self, ctx: SolveContext) -> State:
    candidate = ctx.candidates[-1]
    raw = self._chat(
        ctx,
        build_verifier_messages(ctx.problem, candidate, ctx.tool_results),
        temperature=self.config.verifier_temperature,
        max_tokens=self.config.verifier_max_tokens,
        role="verifier",
    )
    verification = parse_verification(raw)
    candidate["verification"] = verification
    ctx.verification = verification

    if verification_passes(candidate, verification):
        return State.EXTRACT

    if ctx.repair_rounds >= self.config.max_repair_rounds:
        return State.EXTRACT

    if ctx.model_calls >= self.config.max_model_calls:
        return State.EXTRACT

    return State.REPAIR
```

### 18.4 Repair

```python
def _handle_repair(self, ctx: SolveContext) -> State:
    ctx.repair_rounds += 1

    raw = self._chat(
        ctx,
        build_repair_messages(ctx),
        temperature=self.config.repairer_temperature,
        max_tokens=self.config.repairer_max_tokens,
        role="repairer",
    )
    action = parse_solver_action(raw)

    if action.kind == "tool":
        ctx.pending_tool_calls = validate_tool_requests(action.tool_calls)
        ctx.return_state_after_tool = State.REPAIR
        return State.TOOL

    candidate = create_candidate(action, source="repair")
    ctx.candidates.append(candidate)
    return State.VERIFY
```

### 18.5 Extract

```python
def _handle_extract(self, ctx: SolveContext) -> State:
    candidate = select_best_candidate(ctx.candidates)
    answer = local_extract_answer(candidate)

    if not answer and ctx.model_calls < self.config.max_model_calls:
        answer = model_extract_answer(ctx, candidate)

    if not answer:
        return State.FALLBACK

    ctx.final_response = answer
    append_finalize_trace(ctx)
    return State.DONE
```

## 19. 测试方案

### 19.1 接口测试

- `ReasoningAgent(client=mock_client)` 可正常初始化。
- `solve(problem, metadata)` 返回 `dict`。
- `final_response` 始终是非空字符串。
- `json.dumps(result)` 成功。
- `metadata=None`、空字典、缺少 `idx` 时不报错。
- 代码不读取 `metadata["answer"]`。

### 19.2 状态机测试

覆盖：

- 正常 `ANALYZE -> SOLVE -> VERIFY -> EXTRACT`。
- Solver 请求工具后返回候选。
- Verifier 返回 `REVISE` 后修正成功。
- Verifier 返回 `REJECT` 后独立重解。
- 工具连续失败后的降级。
- 模型预算耗尽后的提取。
- 没有候选时进入 Fallback。
- 状态步数达到上限时终止。

### 19.3 模型响应测试

Mock client 返回：

- 合法 JSON。
- Markdown JSON 代码块。
- JSON 前后包含解释。
- 缺失字段。
- 非法 verdict。
- 空字符串。
- 非字符串。
- 抛出超时异常。
- 连续返回工具请求。

### 19.4 工具测试

- 合法代数表达式。
- 非法表达式。
- 超长表达式。
- 未知工具。
- 多余参数。
- 缺少参数。
- 重复工具调用。
- 大型矩阵。
- SymPy 无法求解。
- 所有结果均可 JSON 序列化。

### 19.5 并发测试

使用同一个 Agent 实例并发调用多道题，验证：

- 候选不串题。
- trace 不串题。
- 工具结果不串题。
- 模型调用计数按题独立。
- 返回顺序变化不影响结果。

### 19.6 样例验收

至少确保样例题最终答案可以稳定抽取为：

| idx | 预期答案 |
| ---: | --- |
| 0 | `72` |
| 1 | `-1` |
| 2 | `-1/8` |

## 20. 实验与迭代路线

首版完成后，使用统一评测集进行消融实验，不直接堆叠机制。

建议实验顺序：

1. 单次 Solver，无 Analyzer、Verifier 和工具。
2. Solver + Verifier。
3. Analyzer + Solver + Verifier。
4. 加入按需 Repairer。
5. 加入白名单工具。
6. 对困难题启用第二候选。
7. 比较不同调用预算和温度。

记录指标：

- 最终答案准确率。
- 平均模型调用次数。
- P95 模型调用次数。
- 平均 token 使用量。
- 工具调用成功率。
- Verifier 修正成功率。
- 格式解析失败率。
- 超时率和异常率。

只有在验证明确提升准确率且资源成本可接受后，才保留新增机制。

## 21. 首版实现顺序

1. 移除 `user_agent.py` 对本地 `InternChatClient` 和 Lagent Agent 的依赖。
2. 建立 `reasoning_agent/` 包和根目录 `user_agent.py` 导出入口。
3. 实现 `AgentConfig`、`TaskContext`、`RunnerContext`、事件结构和内部异常。
4. 实现 `ReasoningAgent` 和 `TaskRunner`，保证 `solve()` 返回稳定的 `final_response`。
5. 实现受控 ReAct loop：模型调用、事件解析、工具调用、observation 回填和停止策略。
6. 实现 SymPy 白名单工具、工具注册、参数校验、调用去重和结果序列化。
7. 实现最终答案抽取、本地 fallback、trace 清理和 JSON 安全转换。
8. 实现独立 Verifier、Repairer 和候选选择策略。
9. 编写 Mock client 单元测试、runner loop 测试、工具测试和并发测试。
10. 使用本地样例进行端到端验证。
11. 基于评测结果调整提示词和预算，不修改正式入口契约。

## 22. 验收标准

首版设计实现完成的判定条件：

- 正式入口完全符合平台契约。
- 不依赖 `main.py`、`llm_client.py` 的私有行为。
- 不依赖 LangGraph、LangChain 或 Lagent。
- 单题模型调用绝不超过 10 次。
- 工具调用和状态步数存在硬上限。
- Verifier 与 Solver 上下文隔离。
- 没有跨题长期记忆和可变共享状态。
- 所有返回值均可 JSON 序列化。
- 任意可恢复异常不会导致状态机无限循环。
- 样例题输出格式和答案满足本地 runner 校验。

# Challenge Cup 2026 Reasoning Agent

本仓库是挑战杯人工智能赛道初赛的数学推理智能体模板。目标是实现一个满足平台入口约定的 `ReasoningAgent`，接收数学题文本和题目元信息，调用 Intern-S 系列模型或本地推理逻辑，返回最终答案。

平台评测时会从仓库根目录的 `user_agent.py` 加载：

```python
from user_agent import ReasoningAgent

agent = ReasoningAgent(client=official_client)
result = agent.solve(problem: str, metadata: dict)
```

`solve` 必须返回可 JSON 序列化的字典，并包含非空字符串字段 `final_response`：

```python
{
    "final_response": "最终答案",
    "trace": [{"step": "finalize", "content": {"answer": "..."}}],
}
```

## 仓库目录结构

```text
.
├── user_agent.py                    # 平台固定入口，导出 ReasoningAgent
├── main.py                          # 本地 JSONL 调试 runner
├── llm_client.py                    # 本地 Intern-S API client 示例
├── requirements.txt                 # Python 依赖
├── sample_data/
│   └── dev.jsonl                    # 本地调试样例题
├── sample_outputs/                  # 本地运行输出目录
├── docs/
│   └── reasoning-agent-design.md    # 设计说明
└── reasoning_agent/
    ├── factory.py                   # 根据模式选择具体 agent
    ├── baseline/                    # lagent 版多候选 baseline
    └── custom/                      # 默认自定义 agent
        ├── agent.py                 # CustomAgent 入口
        ├── config.py                # 调用次数、token、trace 等配置
        ├── parsers/                 # 模型输出、JSON、最终答案解析
        ├── prompts/                 # 系统提示词和工具调用提示词
        ├── runner/                  # ReAct 风格循环与上下文管理
        ├── tools/                   # 工具注册与执行器
        └── verifier/                # 答案校验与修复逻辑
```

## 安装与本地调试

安装依赖：

```bash
pip install -r requirements.txt
```

配置 API key：

```bash
export INTERN_API_KEY="sk-..."
```

运行样例数据：

```bash
python main.py --input_file sample_data/dev.jsonl --output_dir sample_outputs
```

`main.py` 会读取 JSONL，每行一道题，并把每题结果保存为独立 JSON 文件。输出目录会自动带上时间戳和 agent 模式，例如：

```text
sample_outputs/2026-06-24-011243-custom/0.json
```

调整本地并发：

```bash
export LOCAL_MAX_CONCURRENCY=4
```

切换模型名称：

```bash
export INTERN_MODEL="intern-s2-preview"
```

## Agent 模式切换

当前支持两种模式：

```text
custom    默认模式，自定义工具调用推理循环
baseline  旧版 lagent 多候选生成-验证-选择 baseline
```

通过环境变量切换：

```bash
REASONING_AGENT_MODE=custom python main.py --input_file sample_data/dev.jsonl --output_dir sample_outputs
REASONING_AGENT_MODE=baseline python main.py --input_file sample_data/dev.jsonl --output_dir sample_outputs
```

也可以在代码中显式传入：

```python
agent = ReasoningAgent(client=client, agent_mode="custom")
```

## 不同 Agent 的工作方式

### custom

`custom` 是默认实现，入口为 `reasoning_agent/custom/agent.py`。它的主要流程是：

1. `CustomAgent.solve` 创建 `TaskRunner`。
2. `TaskRunner` 创建 `RunnerContext`，保存题目、metadata、消息、trace、错误和候选答案。
3. `ToolUseRunner` 进入受控 ReAct 风格循环，最多调用模型 `max_model_calls` 次。
4. 模型输出会被解析成三类事件：最终答案、工具调用、非法响应。
5. 如果是工具调用，则通过 `ToolExecutor` 执行白名单工具，并把 observation 写回上下文。
6. 如果是最终答案，则进入 `AnswerVerifier` 校验，再格式化为 `final_response`。
7. 出错时会记录 trace，并通过 fallback 逻辑尽量返回一个稳定答案。

默认工具注册表目前为空：

```python
def build_tool_registry() -> dict[str, ToolSpec]:
    return {}
```

如果需要加入 SymPy、计算器或检索工具，应在 `reasoning_agent/custom/tools/registry.py` 中注册，并确保工具参数、返回值和异常都可控、可序列化。

### baseline

`baseline` 位于 `reasoning_agent/baseline/agent.py`，依赖 `lagent`。它的流程是：

1. 调用 policy agent 生成多个候选解答。
2. 调用 verifier agent 对每个候选进行多轮 A/B 判断。
3. 按验证投票置信度选择得分最高的候选。
4. 返回该候选作为 `final_response`，并把生成和验证过程写入 `trace`。

该模式适合理解最小 baseline 和多候选投票思路，但依赖更重，调用次数也更多。

## 引入新的 Agent

新增 agent 推荐按以下方式接入：

1. 新建目录，例如：

```text
reasoning_agent/my_agent/
├── __init__.py
├── agent.py
└── config.py
```

2. 在 `agent.py` 中实现类，保持构造函数兼容：

```python
class MyAgent:
    def __init__(self, client, config=None, *args, **kwargs):
        self.client = client

    def solve(self, problem: str, metadata: dict | None) -> dict:
        return {
            "final_response": "...",
            "trace": [],
        }
```

3. 修改 `reasoning_agent/factory.py`：

```python
SUPPORTED_AGENT_MODES = {"custom", "baseline", "my_agent"}
```

并在 `_build_agent` 中加入分支：

```python
if mode == "my_agent":
    from reasoning_agent.my_agent import MyAgent
    return MyAgent(client, config, *args, **kwargs)
```

4. 本地运行：

```bash
REASONING_AGENT_MODE=my_agent python main.py --input_file sample_data/dev.jsonl --output_dir sample_outputs
```

新增 agent 时不要改动 `user_agent.py` 的平台入口，保持平台始终从 `user_agent.py` 导入 `ReasoningAgent`。

## 输出格式要求

每次 `solve` 至少返回：

```python
{"final_response": "答案"}
```

推荐同时返回：

```python
{
    "final_response": "答案",
    "trace": [
        {"step": "plan", "content": "..."},
        {"step": "model_call", "content": "..."},
        {"step": "finalize", "content": {"answer": "..."}}
    ],
}
```

注意事项：

- `final_response` 必须是非空字符串。
- 返回值必须能被 `json.dump` 序列化。
- 不要在 `trace` 中记录 API key、访问令牌或个人隐私。
- 不要依赖样例数据里的 `answer` 字段，正式评测不会提供标准答案。

## 提交与安全注意事项

- 仓库根目录必须保留 `user_agent.py`。
- 所有新增依赖写入 `requirements.txt`。
- 不要硬编码 API key、绝对路径、隐藏测试集或标准答案。
- 不要假设题目按固定顺序执行，也不要依赖跨题共享状态。
- 本地调试通过后，提交具体 commit SHA 供评测系统拉取，避免只提交分支名。

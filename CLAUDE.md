# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A competition template for the Challenge Cup 2026 math-reasoning-agent track. The goal is a `ReasoningAgent` whose `solve(problem: str, metadata: dict) -> dict` returns a JSON-serializable dict with a non-empty string `final_response`. See `README.md` for the full competition spec and submission rules (Chinese).

## The platform contract (do not break)

The evaluator loads the agent like this and nothing else:

```python
from user_agent import ReasoningAgent
agent = ReasoningAgent(client=official_client)
result = agent.solve(problem, metadata)   # must contain non-empty str final_response
```

- `user_agent.py` must stay at repo root and re-export `ReasoningAgent`. It is a one-line re-export of `reasoning_agent/factory.py`; never change its interface.
- `ReasoningAgent.__init__` must keep accepting `client` (positional/keyword) plus arbitrary `*args, **kwargs` — the evaluator constructs it and may pass extra args.
- `metadata` may be `None` or arbitrary; do not assume keys. The local runner only passes `{"idx": ...}`. Never rely on `answer` fields in sample data (real eval has no ground truth) and never share state across problems.

## Commands

```bash
pip install -r requirements.txt           # 'baseline' mode pulls lagent from git; 'custom' mode does not need it
export INTERN_API_KEY="sk-..."            # required; client raises at construction if missing
python main.py --input_file sample_data/dev.jsonl --output_dir sample_outputs
```

Useful environment variables:

- `REASONING_AGENT_MODE` — `custom` (default) or `baseline`. Selects the implementation in `factory.py`.
- `LOCAL_MAX_CONCURRENCY` — async worker count in `main.py` (default 8).
- `INTERN_MODEL` / `INTERN_API_BASE` — override model name / endpoint in `llm_client.py`.

`main.py` writes one `<idx>.json` per input line into a timestamped subdir like `sample_outputs/2026-06-24-011243-custom/`. It **skips inputs whose output file already exists** (resume behavior) — delete the run dir to force a rerun. Exceptions are caught per-item and written as `status: "error"` records, so a single failure never aborts the batch.

There is no test framework committed. `tests/` exists but is empty; if adding tests, name them `test_*.py` and keep parser/verifier/formatting tests deterministic (no live API).

## Architecture

Two agent implementations sit behind the stable `ReasoningAgent` wrapper, chosen by `factory.py`:

- **`baseline/`** — lagent-based generate→verify→select (multiple candidates, A/B verifier voting). Heavier deps and more model calls. Imported lazily so `custom` mode works without lagent installed.
- **`custom/`** — the default. A controlled ReAct loop. This is where active work happens.

### Custom agent flow (`reasoning_agent/custom/`)

`CustomAgent.solve` → `TaskRunner.run` → `ToolUseRunner.run`, with everything threaded through a single mutable `RunnerContext` (`runner/context.py`) that accumulates messages, counters, observations, candidates, `trace`, and `errors`.

1. `TaskRunner` (`task_runner.py`) builds the context, runs the loop, verifies the candidate, and **always** appends a `finalize` trace step. Any exception is swallowed into the trace and resolved via `fallback_answer` — `solve` is contractually not allowed to raise.
2. `ToolUseRunner` (`runner/loop.py`) is the ReAct loop. Each iteration: call the model → `parse_model_event` → dispatch. `RunnerPolicy` (`runner/policy.py`) enforces the budgets in `config.py` (`max_model_calls`, `max_tool_calls`, `max_loop_steps`).
3. The model must reply with a single JSON object. `parse_model_event` (`parsers/tool_call_parser.py`) turns it into one of three events (`runner/events.py`):
   - `final_answer` → returns a `Candidate`, loop ends.
   - `tool_call` → `ToolExecutor` runs a whitelisted tool; the observation is appended as a message and the loop continues.
   - invalid / unparseable → `InvalidEvent`, falls back rather than crashing.
4. `AnswerVerifier` (`verifier/answer_verifier.py`, with `verifier/repair.py`) checks/repairs the candidate; result goes into the trace.
5. `normalize_final_response` (`parsers/final_answer_parser.py`) strips answer prefixes / code fences; empty answers become the sentinel `"无法确定唯一答案"`.

### Key invariants when editing custom/

- **Tools are an empty whitelist by design.** `build_tool_registry()` (`tools/registry.py`) returns `{}` and `tools/math_tools.py` is a placeholder. To add a tool (e.g. SymPy), register a `ToolSpec` here. `ToolExecutor` (`tools/executor.py`) validates name + required/allowed arguments, catches all exceptions into the observation (tool failures are model-visible data, not crashes), and JSON-sanitizes results. Tool functions must therefore accept only whitelisted kwargs and return JSON-safe values.
- **The trace is the audit log.** Most steps append a `{"step": ..., "content": ...}` entry to `ctx.trace`. `make_json_safe` runs over it before return. Don't put secrets, API keys, or huge blobs in trace; sizes are bounded by `max_trace_chars` / `max_response_chars`.
- **Prompts** live in `prompts/system.py` and `prompts/tool_use.py`. `build_initial_messages` and `build_observation_message` define the message protocol the model is expected to follow — changing the required JSON shape means updating both the prompt and `parse_model_event`.

### Adding a new agent mode

Create `reasoning_agent/<name>/` with an `agent.py` exposing a class with `__init__(self, client, config=None, *args, **kwargs)` and `solve(problem, metadata) -> dict`. Then add `<name>` to `SUPPORTED_AGENT_MODES` and a branch in `_build_agent` in `factory.py`. Do not touch `user_agent.py`.

## Conventions

- `snake_case` for functions/files/trace step names, `PascalCase` for classes/dataclasses. Config and state objects are frozen/plain dataclasses.
- Commit messages follow `type: summary` (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
- Submit a concrete commit SHA for evaluation, not a branch name.

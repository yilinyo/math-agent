# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python baseline for the Challenge Cup reasoning-agent task. The platform entrypoint is `user_agent.py`, which exports `ReasoningAgent` from `reasoning_agent/factory.py`. Core implementations live under `reasoning_agent/`: `baseline/` contains the older lagent-based generate-verify-select agent, while `custom/` contains the active custom agent, prompts, parsers, tools, runner state, and verifier logic. `main.py` is the local JSONL runner. Sample inputs are in `sample_data/`, generated local outputs go to `sample_outputs/`, and design notes live in `docs/`.

## Build, Test, and Development Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the sample dataset locally:

```bash
export INTERN_API_KEY="sk-..."
python main.py --input_file sample_data/dev.jsonl --output_dir sample_outputs
```

Switch agent implementations when debugging:

```bash
REASONING_AGENT_MODE=baseline python main.py --input_file sample_data/dev.jsonl --output_dir sample_outputs
```

Limit local concurrency for API rate limits:

```bash
export LOCAL_MAX_CONCURRENCY=4
```

## Coding Style & Naming Conventions

Use Python 3 style with 4-space indentation, type hints where they clarify interfaces, and small modules grouped by responsibility. Keep `ReasoningAgent(client=...)` and `solve(problem: str, metadata: dict) -> dict` stable; the evaluator depends on that contract. Prefer `snake_case` for functions, variables, files, and trace step names, and `PascalCase` for classes and dataclasses. Do not hardcode API keys, local absolute paths, hidden answers, or judge-specific behavior.

## Testing Guidelines

There is no committed unit-test framework yet. Treat the local runner as the minimum regression check and confirm every changed agent returns a JSON-serializable dict with a non-empty string `final_response`. If adding tests, place them under `tests/`, name files `test_*.py`, and prefer deterministic parser, verifier, and formatting tests that do not require live API calls.

## Commit & Pull Request Guidelines

The existing history uses short conventional-style messages, for example `docs: move competition guide to README`. Follow `type: summary` where practical (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`). Pull requests should describe the agent behavior change, list validation commands run, note new dependencies or environment variables, and include sample output snippets when output formatting changes.

## Security & Configuration Tips

Keep secrets in environment variables such as `INTERN_API_KEY`. Use relative paths for project files, and ensure generated outputs, caches, and IDE files are not required for evaluation.

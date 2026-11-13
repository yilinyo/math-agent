# Submission Log

本文件只记录提交日志、修改逻辑和真实评测分数，不记录数据集、标准答案、模型原始响应或 API key。

规则：

- 每次 `main -> judge` 提交追加一条记录，不覆盖历史。
- `score` 首次可以留空，等 judge 返回真实结果后再回填。
- `commit_sha`、`timestamp`、`change_summary`、`logic_details` 和 `validation` 不能为空。
- 真实分数必须注明来源和更新时间。

<!-- New submission records are appended below this line. -->
## 2026-08-09T23:56:29+08:00 - feat: add structured custom reasoning pipeline

- source_branch: `main`
- target_branch: `judge`
- commit_sha: `4e95b4172b9439c90cce4317039c368a7ea842cb`
- timestamp: `2026-08-09T23:56:29+08:00`
- status: `submitted`
- score:
- score_source:
- score_updated_at:
- score_notes:
- validation: `python -m unittest discover -s tests -p 'test_*.py'`
- change_summary: Default to the custom reasoning pipeline, add structured solve-step verification, and improve local runner diagnostics.
- logic_details:
  - 1. Add a structured custom pipeline with preprocessing, generation, selection, formatting, and repair stages.
  - 2. Default the factory entrypoint to custom and keep the platform-facing user_agent contract stable.
  - 3. Extend the local runner with env loading, required env validation, duration tracking, and debug trace propagation.
  - 4. Add contract and pipeline tests to cover the new entrypoint and runner behavior.
- notes: Score will be filled after judge finishes.
## 2026-08-12T23:50:34+08:00 - feat: add domain skill strategy pipeline

- source_branch: `main`
- target_branch: `judge`
- commit_sha: `cb49a43cbc9f39285ade8ecb2cdec56139aebbc8`
- timestamp: `2026-08-12T23:50:34+08:00`
- status: `submitted`
- score:
- score_source:
- score_updated_at:
- score_notes:
- validation: `python -m unittest tests.test_custom2_state_runtime && python -m unittest tests.test_llm_client`
- change_summary: Split custom2 planning into domain classification, skill selection, fact formalization, and strategy planning with controlled skill injection.
- logic_details:
  - 1. Add domain classification and top-k Chinese math skill selection from the skills directory.
  - 2. Keep FactFormalizer focused on problem facts while StrategyPlanner consumes selected skills to generate initial tasks and guidance.
  - 3. Stop injecting full skill text into Solver; Solver now uses Strategy Guidance, while Replanner receives truncated skill summaries.
  - 4. Add model-based replanning context, request timing dumps, and lower local client timeout to 240 seconds.
- notes:
## 2026-08-13T23:22:28+08:00 - feat: enable thinking mode by default

- source_branch: `main`
- target_branch: `judge`
- commit_sha: `bbafd784749ea5dbd6cfcedbd13c6dc1336ae453`
- timestamp: `2026-08-13T23:22:28+08:00`
- status: `submitted`
- score:
- score_source:
- score_updated_at:
- score_notes:
- validation: `python -m unittest tests.test_llm_client tests.test_custom_pipeline tests.test_custom2_state_runtime`
- change_summary: Enable thinking_mode by default for local client, custom pipeline config, and all custom2 model nodes.
- logic_details:
  - 1. Add DEFAULT_THINKING_MODE=True to the InternChatClient payload defaults.
  - 2. Switch custom AgentConfig.thinking_mode default to True for legacy custom pipeline calls.
  - 3. Pass thinking_mode=True from custom2 classifier, formalizer, strategy planner, solver, replanner, finalizer, step verifier, and candidate verifier.
  - 4. Update tests to assert the new default behavior while preserving explicit override support.
- notes:

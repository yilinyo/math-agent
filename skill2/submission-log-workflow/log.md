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
## 2026-08-14T23:33:23+08:00 - feat: harden custom2 reasoning runtime

- source_branch: `main`
- target_branch: `judge`
- commit_sha: `8d04e037591a9c0dd21b1589b5e6b7d1183b7b7e`
- timestamp: `2026-08-14T23:33:23+08:00`
- status: `submitted`
- score:
- score_source:
- score_updated_at:
- score_notes:
- validation: `155 relevant tests passed: custom2 state 74, custom2 efficient 27, custom pipeline 22, answer normalizer 17, llm client 10, runner contract 3, user agent contract 2; py_compile and git diff --check passed. test_user_agent_trace not run because optional lagent dependency is unavailable.`
- change_summary: Add deadline-aware efficient reasoning, strict candidate gates, failed-route enforcement, safe task dependencies, mode-aware answer normalization, and expanded model output budgets.
- logic_details:
  - 1. Add a wall-clock-aware custom2 runtime with structured draft critique, repair, replanning, candidate verification, strict and independently audited best-effort finalization.
  - 2. Require Solver candidate registration before strict verification and keep JSON parsing failures outside the valid Solver-attempt budget.
  - 3. Inject complete selected skill guidance into strategy and replanning while validating task dependencies before they enter AgentState.
  - 4. Make failed-route memory a mandatory Critic and CandidateVerifier constraint so unresolved rejected methods cannot be silently accepted.
  - 5. Normalize objective answers by question mode, bound debug traces, expose model finish metadata, and increase Solver, Strategy, and Finalizer output budgets.
- notes: Score will be filled after judge finishes.
## 2026-08-14T23:59:13+08:00 - fix: improve custom2 convergence flow

- source_branch: `main`
- target_branch: `judge`
- commit_sha: `6f7c6963839b245cccb1b41429bfbb0b5f832119`
- timestamp: `2026-08-14T23:59:13+08:00`
- status: `submitted`
- score:
- score_source:
- score_updated_at:
- score_notes:
- validation: `122 targeted tests passed: custom2 efficient 31, custom2 state 74, answer normalizer 17; py_compile and git diff --check passed.`
- change_summary: Keep draft and macro execution on remaining tasks before candidate gates, and make best-effort finalization independently verify regenerated answers while still returning a concrete result.
- logic_details:
  - 1. Continue dependency-ready draft or macro tasks after Critic acceptance, including accepted repair drafts.
  - 2. Generate a candidate-extraction task when accepted reasoning has no registered candidate instead of spending a Replanner call.
  - 3. Verify both provisional and regenerated best-effort candidates independently, avoid false support links, and return the strongest concrete answer with an explicit audit trace when strict verification still rejects it.
  - 4. Add deterministic regression coverage for normal acceptance, repair acceptance, generated candidate tasks, and two-stage best-effort verification.
- notes:
## 2026-09-10T00:50:23+08:00 - feat: add staged custom2 reasoning workflow

- source_branch: `main`
- target_branch: `judge`
- commit_sha: `80c6ad070927081ce238879a512346be6e0960ea`
- timestamp: `2026-09-10T00:50:23+08:00`
- status: `submitted`
- score:
- score_source:
- score_updated_at:
- score_notes:
- validation: `292 tests passed with python -m pytest -q --ignore=tests/test_max_token_retry.py --ignore=tests/test_user_agent_trace.py; python -m py_compile passed; git diff --cached --check passed. Full collection requires optional lagent.`
- change_summary: Add a staged classification-strategy-solve-audit workflow, make it the default agent mode, and harden timeout recovery and result status reporting.
- logic_details:
  - 1. Add staged profiling, strategy planning, complete solving, targeted audit, repair, compact retry, and direct emergency solving.
  - 2. Normalize domain skill routing to canonical English categories with deterministic fallback and exhaustive-counting obligations.
  - 3. Enforce shared per-stage timeout budgets while retaining bounded HTTP retries and report placeholder outcomes as timeout or failure.
  - 4. Migrate runtime strategy materials to canonical skill2 directories and add deterministic contract and recovery tests.
- notes: Committed locally with main and master aligned; not synchronized to judge. Score pending future real evaluation.

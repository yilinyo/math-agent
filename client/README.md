# MathS-Agent Chat

React 18 + TypeScript + Vite chat interface for the existing FastAPI Session/Task API. Styling uses local CSS and Lucide icons; Markdown uses react-markdown, remark-gfm and remark-math, with locally bundled KaTeX fonts. No frontend model client, API key, replacement backend or Multi-Agent runtime is introduced. The visual layout is inspired by AI-chat-rag; its source was not copied.

## Development

Use Node >=22.12 (tested with 24.11.1). From the repository root:

```powershell
cd client
npm.cmd ci
$env:MATHS_BACKEND_URL = "http://127.0.0.1:8005"
npm.cmd run dev -- --port 5173
```

Open `http://127.0.0.1:5173/chat/`. The FastAPI backend must already be running. The default proxy target is port 8005; change the non-secret `MATHS_BACKEND_URL` only when choosing a different backend. Vite proxies `/v1`, `/health` and the legacy Trace/documentation routes, so no permissive CORS configuration is required. Vite binds loopback; do not expose either service publicly without the existing authentication/proxy deployment boundary.

The UI's runtime badge reflects `/health/ready`: `langgraph_staged` selects the real workflow; names containing `fake` are explicitly labelled demonstration runtimes. Readiness is not proof that a model key/endpoint is valid. Sending to a real workflow consumes the provided model's quota. Never put secrets in frontend files, `VITE_*` variables, browser storage or bundles; model credentials remain with the existing backend bootstrap.

## Build And Serve

```powershell
cd client
npm.cmd test
npm.cmd run build
cd ..
.\.venv-platform\Scripts\python.exe -m agent_platform --port 8006
```

That example launches a **Fake** backend. To solve genuinely, use the existing `--runtime langgraph --client-provider ... --client-identity ...` command instead. Build output goes to ignored `agent_platform/static/chat/`. A newly started FastAPI app serves `/chat/` and its assets without a Node server; the original `/trace-viewer` and root redirect remain unchanged. An unbuilt UI returns fixed HTTP 503 `chat_not_built`, and missing assets return 404. Restart a backend started before frontend integration to register the new routes. The Dockerfile builds the frontend in an isolated Node stage and copies only bundled assets into the Python runtime; actual Docker/remote CI execution remains pending.

## Behavior And Boundaries

- First send creates a Session, then submits to `/v1/sessions/{session}/tasks` with an idempotency key. A retry of the same question/session after a failed acknowledgement retains that key within the current page lifetime.
- Task SSE streams use incremental CRLF/multiline parsing, sequence-based deduplication, reconnect cursors, bounded backoff and three-second authoritative status checks. Completed historical events do not override a newer snapshot. Switching sessions aborts the old observer, not the backend task.
- Progress represents actual started/completed stages, not fabricated completion percentages. Optional/unvisited stages are not marked complete; interrupted stages remain unfinished. Repair can revisit a previously executed stage.
- Cancel and resume use existing endpoints. Cancellation does not pretend to forcibly terminate an uncooperative client's in-flight HTTP/model thread; that remains the runtime/client boundary. Final answers are displayed in full only when supplied by the backend, without a fake typewriter stream.
- Settings → conversation preferences selects `auto` (follow the current question), `answer`, `brief` or `detailed` through the task's `response_style` field. Explicit selection takes precedence over text preferences. Auto reuses the existing profile model call to classify presentation and defaults to brief when that field is absent/invalid. The platform adapter retains accepted public solution sections; proof bodies are preserved even in answer-only mode. Missing steps are reported rather than invented. An older backend exposes a restart notice and keeps legacy submission usable without sending the unsupported field.
- Markdown supports dollar math, `\(...\)`, `\[...\]` and single-line bare `\boxed{...}`. A Markdown parser protects code/HTML ranges during delimiter normalization. Raw HTML is not executed, KaTeX trust is disabled, expansion is bounded, unsafe links are blocked, and model-provided remote images are not loaded. Wide equations/code/tables scroll inside their container.
- When `/health/ready` advertises `server_history: true`, the sidebar loads paginated Sessions from the server and selected conversations load paginated Tasks, including public answers. Browser storage retains only the selected Session ID under `maths-chat-selected-v1`; successful history loading removes the old question cache. Clearing browser storage does not erase server history. Session/task pages use 30/20 items, with explicit load-more controls. Session pages are newest-created first; Task pages are newest-accepted first and are displayed chronologically. Refreshing the sidebar discovers Sessions created elsewhere. This is a local single-user history, not an account-based cross-device synchronization feature.
- Older backends without `server_history` retain the legacy browser index (30 Sessions/20 Tasks each, no answers/Trace); they do not gain persistence automatically. A process-local backend can provide server history while it is running, but still loses it on restart. Redis must be configured and readiness must report `restart_durable: true` before claiming restart durability. No server-side deletion UI is added.
- Only the selected Session's latest Task is observed live. Other known Task snapshots load when that Session is selected. At most one known active Task per selected Session can be submitted through this composer; backend admission still remains authoritative.
- Reference-attachment upload, selection, polling and citation displays have been removed from chat. Both text and question submissions explicitly use `document_ids: []`, including when connected to an older RAG-enabled backend. The UI makes no document API requests. Existing history and stored files are not deleted; shared backend/Trace RAG adapters remain available outside chat. The current local chat server runs without `--rag-dir` or embedding flags.
- Scanned PDFs without extractable text fail; OCR and document deletion/download/retry administration remain outside this increment. The old Trace workspace remains available.

## Live Execution And Answers

Text and file questions display a collapsible chronological timeline. Each actual stage execution retains its public mathematical explanation, verification evidence and draft, including repeated repair rounds. Model and tool activity appears in per-stage run logs. Explanations come from existing structured results through `stage.explanation` events, without additional model calls. Private thought, raw replies and prompts are excluded. Older tasks show only their recorded content.

The default model client requests upstream SSE during solution calls. Public solution sections are buffered to complete lines, redacted, and published during generation using `answer.started` (`preview: true`), ordered `answer.delta` events (`stream_id`, zero-based `index`, `text`) and `answer.completed`. Private thought channels, private tags and executable check blocks are excluded. The timeline labels these drafts as unverified and retains previous rounds when a new call starts; `answer.discarded` retracts a failed call. Nonstreaming clients publish public drafts at stage completion. Explicit streaming capability is required from custom injected clients. Verification, repair and presentation still run before final commit, without another model call for display. Accepted text is sent without artificial playback delays; its final `task.succeeded` snapshot remains authoritative for copy, export and saved answers.

The client deduplicates replayed chunks, validates stream IDs and contiguous indices, and rebuilds previews from the existing trace/SSE replay. Cancellation, interruption, failure and explicit resume clear previous previews; previews never become stored assistant messages. File questions use the same selected-task observer as text questions. Historical task snapshots continue to work without stream events, and older backends still display their complete final responses.

Each task shows total elapsed time, initial queue time, processing elapsed time and measured final answer delivery duration. Task snapshots and lifecycle events carry a millisecond `timing` object. The existing one-second page clock updates active tasks; terminal and interrupted snapshots use recorded durations. Total and processing times include pauses and later recovery waits; answer delivery is part of processing, not an additional duration. Its backend monotonic measurement covers accepted-answer event writes, not browser receipt time or model generation. Preview generation and completed stage/model events show their measured `duration_ms` in the summary. File exports include recorded total elapsed time. Legacy timestamps remain usable; unknown legacy interruption times display `--`.

## Question Attachment Mode

The backend must start with `--question-dir local_state/chat_questions`; persistent use also requires the existing Redis configuration. One composer supports text-only questions, question files without instructions, and files with optional instructions; there is no mode switch. The upload button sits above the input. Upload only parses and previews questions: no Task or model call starts until Enter/send. With an attached file the text may be empty; without a file nonempty text is required. Shift+Enter inserts a newline; attachment instructions are limited to 4,000 characters and apply to every question in that batch. Explicit presentation choices take precedence over automatic inference. The UI requires readiness capability `question_submission: explicit_send`, so it cannot accidentally upload to an older auto-start backend. Use explicit question headings (`## Question 1`, `## Question 2`, or `第1题：...`); nested subparts remain in their parent question. The question upload is not reference indexing and does not need an embedding model.

Pending attachments appear next to the composer and can be removed from the current submission without deleting their server records. Clicking a pending file in history attaches it again; completed/cancelled history does not attach to new text submissions. Pending attachments restore on reload. Starting a batch clears its composer attachment, and no repeated empty Enter replays a completed batch.

The workspace restores paginated batch history, renders question formulas/answers and PDF page ranges, displays actual per-question state, supports batch/per-question cancellation, explicit interrupted-task resume, failed/cancelled-question retry (maximum two), and Markdown result export. Counts distinguish successful, failed and cancelled questions; file processing completion is not a claim that all answers succeeded. It continues tracking batches when switching to text mode; manual text submission is blocked while the selected Session has an active batch. Switching Sessions does not cancel backend work.

Limits are 20 MiB/file and 24,000 characters/question. Scans/OCR, images, Word files, semantic splitting of ambiguous question sets and complex PDF layout recovery are unsupported. Same-content uploads reuse the original batch with the same options. Server data is in Redis plus `local_state/chat_questions`, not browser storage. Original question blobs and batch metadata currently have no automatic cleanup. See the platform README and question-attachment validation record for local-single-owner boundaries.

## Validation

The chat header has one settings button. Hash routes `/chat/#/settings/general`, `/chat/#/settings/agents`, and `/chat/#/settings/library` open a dedicated settings page for conversation preferences, model profiles, and custom knowledge. The chat stays mounted to preserve drafts, attachments, and task subscriptions; configuration editors guard navigation with unsaved changes. Progress is opened on demand from the chat header.

`ResourcesPanel` is embedded in settings when readiness advertises `knowledge_resources`. It lists existing `skill2_en` domain handbooks and the strategy corpus through `/v1/resources/{skill|strategy}`. Existing resources can be previewed and edited with revision checks; strategy saves update lexical indexes and the changed document vector using the backend's local embedding model. The original runtime selection and retrieval paths consume these edits. Saves are rejected while graph tasks hold a resource lease, and resource changes invalidate earlier checkpoints. The legacy SQLite `/v1/library` API remains available for compatibility but is not this page's data source.

The strategy tab also creates strategies through `POST /v1/resources/strategy` with `{content: string}`. The editor starts from the existing corpus schema, including `example.problem` and `example.solution`. The backend assigns the next integer ID under the resource write lock and publishes the appended vector and updated indexes together. Clients must omit `id` on creation. Skill creation is not exposed.

Settings browser QA uses `scripts/check_settings_ui.py` against a disposable Fake backend with fixture resources. Never point edit tests at production handbooks or strategy corpora. Resource API and transactional index tests use temporary fixtures and an injected deterministic embedder, without model downloads or live LLM calls.

```powershell
cd client
npm.cmd test
npm.cmd run build
cd ..
.\.venv-platform\Scripts\python.exe -m pytest tests/test_platform_frontend.py tests/test_platform_api.py -q
.\.venv-platform\Scripts\python.exe scripts/check_chat_ui.py --url http://127.0.0.1:8006/chat/
```

Browser QA requires Playwright and installed Edge. It refuses non-Fake runtimes before submitting anything. It exercises the actual API workflow, cancellation, reload and dropped-SSE reconnect; separately labelled synthetic responses test Markdown/math rendering, safety, copy and wide formulas. Those fixtures are not model answers or quality evaluation data. Screenshots/logs stay under ignored `sample_outputs/chat_qa/`.

For question attachment QA, with dedicated AOF/always Redis already running:

```powershell
$env:MATHS_CHAT_REDIS_URL = "redis://127.0.0.1:6388/0"
.\.venv-platform\Scripts\python.exe scripts/check_question_attachment_ui.py
```

Run from the repository root; port 8008 must be free. The script owns a private Fake API, random Redis namespace and ignored `sample_outputs/question_attachment_qa/` directory. It uses actual isolated PDF/Markdown parsing and tests text-only, file-only and file-plus-instruction submissions, upload without solving, empty input rejection without files, attachment removal/reattachment, Shift+Enter, pending restart, sequential dispatch, formulas, page provenance, export, cancellation, cleared browser storage and Session isolation at four viewports. It also checks that reference controls and document requests are absent. It stops its own API and removes only its own Redis namespace. Playwright, Edge and psutil are required; no generative model call occurs. The obsolete reference-upload browser script has been removed; reusable RAG backend tests remain.

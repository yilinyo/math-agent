# MathS-Agent Web Backend

This package provides the FastAPI backend for the standalone Web application. It defaults to a process-local Fake demo; real solving uses the staged-method adapter and LangGraph with an explicitly supplied model client. Redis persistence, typed tools, Function Calling and SDK MCP stdio remain available. Competition entrypoints and offline evaluation tools have been removed. See the root README for the current quick start. M2-M6 labels below identify historical implementation milestones.

M6 adds a separate PostgreSQL/Celery deployment. The M2-M5 commands and limitations below remain descriptions of the reference adapters, not the distributed deployment. See [M6 distributed delivery](#m6-distributed-delivery) and the explicit pending gates in `docs/design/single-agent-platform/m6-validation.md`.

## Start

The optional React chat page is available at `/chat/` after building `client/`. For development, run `npm.cmd ci` then `npm.cmd run dev -- --port 5173` in `client/`; its default backend proxy is `http://127.0.0.1:8005`. Chat retains text questions, question-file uploads, server history, formulas and task progress. Reference-attachment controls and citation displays have been removed; chat never selects historical reference documents. `/trace-viewer` and optional backend document APIs remain separate diagnostic/experimental capabilities.

## Persistent Local Chat And History

For local chat, use `RedisTaskStore` with an isolated namespace and AOF/always. A dedicated Redis avoids changing shared demonstration services. From the repository root, create the non-versioned data directory and start Redis using the installed binary:

```powershell
New-Item -ItemType Directory -Force local_state/chat_redis
redis-server deploy/redis-chat.conf
```

If `redis-server` is not on PATH, use the absolute path of your installed executable. Start the backend in a second terminal that already has the real model's environment configured:

```powershell
$env:MATHS_CHAT_REDIS_URL = "redis://127.0.0.1:6388/0"
.\.venv-platform\Scripts\python.exe -m agent_platform --port 8009 --runtime langgraph --client-provider deployment_bootstrap:provided_client --client-identity intern/intern-s2/local-v1 --function-calling off --redis-url-env MATHS_CHAT_REDIS_URL --namespace maths:chat:v1 --question-dir local_state/chat_questions
```

The provider and versioned identity must match your trusted integration, not a replacement model client. Build `client/` and open `http://127.0.0.1:8009/chat/`. For Vite, set `MATHS_BACKEND_URL` to this backend before starting Vite. Readiness must show `storage: redis_reference`, `restart_durable: true` and `server_history: true`. There is no silent memory fallback if Redis is unavailable or AOF is misconfigured. Redis/API do not automatically start after a machine reboot; start both again with the same directory, namespace and client identity. Back up `local_state/chat_redis` using a Redis-aware backup procedure; do not delete it during output cleanup. Local Redis is loopback-only and is not an Internet-safe deployment.

- `GET /v1/sessions?limit=30&cursor=...`: public summaries (`id`, `title`, creation/last-submission time, Task count), newest-created first.
- `GET /v1/sessions/{id}`: basic Session settings, no message-memory dump.
- `GET /v1/sessions/{id}/tasks?limit=20&cursor=...`: public task status, problem and answer, newest-accepted first.
- All list pages return `items` and `next_cursor`; limits are 1-50. Opaque keyset cursors bind to the collection/Session. Inserting newer records does not shift older pages. These are live views, not transactional snapshots across multiple HTTP requests. Responses use `Cache-Control: no-store`; no checkpoint/tool ledger/private prompt is exposed.
- The Redis history indexes and summaries are written atomically with Session/Task creation. Use a **new namespace** for this increment: old Redis namespaces have no history indexes and require an explicit separately validated backfill before reuse. Missing indexed summaries fail closed. This increment does not add Redis retention/compaction.
- Switching from process memory does **not** migrate old chat records. Keep the old service running or export needed records before replacing it. A leftover browser question index cannot reconstruct lost answers.
- Global Session discovery is intentionally single-user. Keep the service on loopback or behind an authenticated single-user proxy. Do not expose it to unrelated users; account ownership/RBAC is not implemented.
- PostgreSQL implements the same history methods; its explicit `migrate` command adds compatible history indexes to schema v2. Full PostgreSQL/Celery deployment remains a separate option, not a prerequisite for this local Redis increment.

### Optional Backend RAG (Not Chat)

Install `requirements-platform-m5.txt` and ensure the existing local embedding weights are complete. Add these flags to the persistent real-backend command above:

```powershell
--rag-dir local_state/chat_rag --embedding-model-dir strategyrag/Qwen3-Embedding-0.6B --embedding-threads 4
```

These flags are for optional backend/Trace experiments, not the current chat service on port 8009. Chat starts without these flags; readiness reports `document_search: unavailable` and `question_attachments: true`. The old `local_state/chat_rag` directory remains untouched, but is not loaded. Redis history/checkpoints and `local_state/chat_questions` remain in use. Disabling document tools changes checkpoint compatibility; completed history remains available, but incompatible interrupted Tasks cannot silently resume. An explicitly RAG-enabled experimental backend must report `document_search: ready`; readiness is not proof of a successful answer. Run one API owner per document directory. The embedding thread setting is 1-16, default 4.

Chat no longer uploads or lists reference documents or renders source snapshots. It explicitly sends `metadata.document_ids: []` for all new text Tasks and question batches, even against a legacy RAG-enabled backend. Optional document APIs still accept PDF/Markdown and support scoped selection; `[]` means no document retrieval, while absent selection retains legacy all-ready-in-Session behavior. New Task admission checks scope/readiness and validates at most 100 IDs before sanitizer truncation. Accepted idempotent retries reuse the original Task even if attachments later expire; prerequisite validation cannot create partial Task/message records. Model-requested document searches cannot expand beyond the Task's selected IDs.

`GET /v1/sessions/{id}/documents?limit=20&cursor=...` returns `items`/`next_cursor`, public document status and no private storage key. Limits are 1-50, with scoped keyset cursors and `Cache-Control: no-store`; SQLite and PostgreSQL execute bounded scoped queries. Public Task status and Task history include at most 20 deduplicated `references` from validated successful/fallback document-search results. Snapshots include filename, heading, page range and excerpt, filtered by Task selection. `mentioned_in_answer` only records that the final public answer contains the retrieved Chunk ID; otherwise the status is `retrieved`. It is not a usage/correctness certificate and is not inferred from a rejected draft.

The actual retrieve node injects retrieved passages as untrusted data into the existing solver path. Enabling RAG changes checkpoint compatibility identity: finished histories remain available, but older incompatible interrupted Tasks cannot silently resume. Files retain the existing 90-day expiry, format/size/parser limits, no-OCR rule and duplicate-content reservation. No delete/retry/download endpoint or account/RBAC is introduced. See `docs/design/single-agent-platform/chat-rag-validation.md` for functional evidence and remaining quality gates.

### Question Attachments (Local Single Owner)

Install the updated `requirements-platform-m5.txt`, build `client/`, then start the Redis backend with `--question-dir local_state/chat_questions` as above. `/health/ready` advertises `question_attachments: true` and `question_submission: explicit_send`. Chat uses one composer for text, question files, or files with optional instructions. Upload parses only, ending in `ready` with no Tasks or model calls; Enter/send is required to start solving, including file-only submissions. Explicit start dispatches sequential solving and consumes the injected model quota. No document RAG, embedding or extraction-model call is needed. Each question has its own Task, deadline, checkpoint, cancellation and answer. Batch cancellation includes pending `ready` batches and prevents further dispatch; failed/cancelled questions can be explicitly retried up to twice unless the whole batch was cancelled. An interrupted checkpoint requires explicit resume. The file-level `completed` status means processing ended; inspect per-question success/failure counts.

Use explicit same-level headings such as `## Question 1`, `## Question 2`, or standalone `第1题：...`, `第2题：...`. Top-level ascending numbered lists are also supported; nested list items remain subparts. A plain single question is accepted. The introductory stem is included in every question; PDF page ranges refer to the question body. Limits: 20 MiB/file, 500 PDF pages, 20 questions, 24,000 characters/question. Ambiguous structures, repeated labels, answer/solution headings or colon-labelled solutions, broken fences/formulas and PDFs with missing extractable page text are rejected before Task submission. This is conservative structural parsing, not semantic question detection or mathematical OCR. Extracted formulas/layout still require user inspection.

Question files never enter the RAG index. Chat submits an empty reference selection and each question has empty Session memory; source and instruction metadata are server-owned, rejected on public Task submission. The reusable backend still accepts explicit reference selections from non-chat integrations. Same-content uploads in the same Session with identical upload options return the existing batch; different options conflict. Explicit start separately stores presentation style and instruction. Batch lists use scoped keyset cursors with limits 1-10. Routes are `/v1/sessions/{id}/question-batches`, `/{batch}/start`, `/{batch}/cancel`, and `/{batch}/questions/{number}/retry`. Start accepts `{ "prompt": "...", "response_style": "auto" }`; prompt defaults to an empty string, is trimmed, and allows at most 4,000 characters. Empty/omitted prompt means solve the original questions without an extra instruction, not an automatic upload trigger. Non-string values remain invalid. Identical accepted start retries reuse the batch without new Tasks; different instructions/styles conflict. Public responses include sanitized `user_instruction`, filename/pages/question/Task projection but no private blob path. Pending batches stay pending after restart; already solving historical batches continue under their original settings.

`local_state/chat_questions` holds original blobs and SQLite WAL/FULL batch metadata, separately from Redis Tasks and `local_state/chat_rag`. Preserve all three stores and keep one API owner per directory; an OS lock prevents overlapping owners. The stable per-question idempotency key reconnects a Task accepted before a lost batch acknowledgement. Capacity is 16 active batches total, one per Session; temporary Task admission/storage unavailability is retried. Batch data has no automatic retention, deletion or backup-coordination feature yet. Question mode is enabled by the local CLI only, not the M6 distributed launcher; do not claim distributed batch support or restart durability with an in-memory Task store.

Validation and explicit pending work: `docs/design/single-agent-platform/question-attachments-validation.md`. Fake browser QA, including actual isolated PDF/Markdown parsing, is `scripts/check_question_attachment_ui.py`; it owns port 8008, a random Redis namespace and private ignored output directory. No live generative request is made.

History-specific checks (Fake-only, no paid requests):

```powershell
.\.venv-platform\Scripts\python.exe -m pytest tests/test_platform_history.py tests/integration/test_platform_redis.py -q
.\.venv-platform\Scripts\python.exe scripts/smoke_redis_restart.py --redis-server "<installed Redis executable>" --port 6389
$env:MATHS_HISTORY_QA_REDIS_URL = "redis://127.0.0.1:6388/0"
.\.venv-platform\Scripts\python.exe scripts/smoke_chat_history.py --redis-url-env MATHS_HISTORY_QA_REDIS_URL --port 8008
```

The browser smoke owns a random namespace and private Fake API process, tests history pagination, cleared browser storage and API restart, then removes only its own keys/process. It never restarts a shared Redis.

From the repository root on Windows:

```powershell
python -m venv .venv-platform
.\.venv-platform\Scripts\python.exe -m pip install -r requirements-platform.txt
.\.venv-platform\Scripts\python.exe -m agent_platform --port 8000
```

On Linux/macOS use `.venv-platform/bin/python` instead of the Windows executable path. The service binds to loopback. Open `http://127.0.0.1:8000/trace-viewer` or `http://127.0.0.1:8000/docs`. Use another `--port` when 8000 is occupied.

## Delivered behavior

- Isolated sessions with random UUIDv4 identifiers and immutable bounded memory snapshots at task acceptance.
- Async submission, eight process-local execution slots, a 256-task admission cap, creation idempotency, and rate limits.
- Atomic task/event/checkpoint updates through the `TaskStore` protocol and `InMemoryTaskStore` reference adapter.
- SSE ordered numeric IDs, replay with `Last-Event-ID`/`after`, 15-second heartbeat comments, 64 total/eight per-task streams, and disconnect cleanup.
- Cancellation is terminal; generation checks prevent old executions from overwriting resumed or cancelled work.
- Process-local checkpoints can resume explicitly after a service interruption when the same store object survives. Active runtime has a 1,200-second budget including a 25-second finalization reserve.
- Sanitized task responses, event/trace history, errors, candidates, and assistant memory; reserved metadata fields are rejected.
- Minimal session/task/Trace viewer, live and ready health endpoints, generated OpenAPI.

## Runtime/storage integration

Use `create_app(store=..., runtime=...)` to inject implementations. `AgentRuntime.run(RuntimeContext)` is asynchronous, and `TaskStore` lists the atomic operations required by the service. Async runtimes must cooperate with cancellation and honor the supplied task lifecycle; `RuntimeContext.progress` writes only declared stages and `save_response` retains a sanitized candidate for timeout finalization.

The default Fake Runtime walks the eight stage names and produces an explicitly labelled non-mathematical demo result. Switching storage does not switch its runtime.

### Chat presentation

Task creation accepts optional `response_style`: `auto`, `answer`, `brief`, or `detailed`. The React chat defaults to auto; callers omitting this field retain legacy answer rendering. An explicit style overrides presentation requests in the problem. Auto adds one validated enum field to the existing classifier call, removes it before validating the original ProblemProfile, and defaults to brief if absent/invalid; no extra model call is added.

`StagedAdapter` in `agent_platform/agent/stage_engine.py` applies the existing presentation instructions from `agent_platform/presentation/`. The old `agent_platform.staged_adapter` import remains available. Brief retains the public solution steps and final answer; detailed also retains problem analysis and verification notes. Answer-only extracts the result, except that proofs retain necessary proof steps. Only declared solution sections are presented, without private thought tags or executable-check blocks, and the existing secret/path sanitizer still applies. These are generated mathematical explanations, not private model reasoning. Missing steps are explicitly reported; the platform never reconstructs an invented proof from a result.

The requested style lives in validated Task metadata and participates in creation idempotency; resolved auto style lives in the adapter checkpoint. Both remain bound during recovery, candidate replacement and timeout delivery. Schema `staged-graph-v5` and the source/config/resource hash reject incompatible older checkpoints. `/health/ready` advertises supported `response_styles`; task status exposes the requested style. Fake demos accept this request field but still do not generate mathematical answers. The underlying reasoning modules remain shared with the Web backend. See `docs/design/single-agent-platform/chat-presentation-validation.md` for the earlier presentation checks.

## M3 real runtime and persistence

Install `requirements-platform-m3.txt` for this optional integration. This includes the pinned tested LangGraph version, Redis client, NumPy/SymPy used by the existing agent, and fakeredis for deterministic transaction tests. The current graph defaults to structured hybrid strategy retrieval. Full vector recall requires `requirements-platform-m5.txt` and local `strategyrag/Qwen3-Embedding-0.6B` weights. Strategy retrieval is separate from optional document RAG; installing the encoder does not enable document ingestion. Set `STAGED_STRATEGY_RETRIEVAL_MODE=lexical` for explicit lexical-only recall. A missing vector channel is recorded as degraded; hybrid confidence filtering omits cards without sufficient vector similarity.

The application owner supplies the model client. No key, secret file, SDK client, or alternate model endpoint is constructed by the platform adapter:

```python
from agent_platform.app import create_app
from agent_platform.graph_runtime import LangGraphRuntime
from agent_platform.redis_store import RedisTaskStore

# client and redis_client are supplied by the application's trusted bootstrap.
app = create_app(
    runtime=LangGraphRuntime(client=client, client_identity="provider/model/version"),
    store=RedisTaskStore(redis_client, namespace="maths:deployment"),
)
```

`redis_client` must use `decode_responses=True`, bounded socket timeouts, and a dedicated namespace. Redis must enable AOF with `appendfsync=always`; readiness and writes fail closed if that durability configuration is absent. `require_aof=False` exists for test doubles and reports `restart_durable: false`, not a persistence guarantee.

A trusted deployment module may expose a zero-argument function returning its injected model client. Launch with:

```powershell
.\.venv-platform\Scripts\python.exe -m pip install -r requirements-platform-m3.txt
$env:MATHS_REDIS_URL="redis://127.0.0.1:6379/0"
.\.venv-platform\Scripts\python.exe -m agent_platform --port 8001 --runtime langgraph --client-provider deployment_bootstrap:provided_client --client-identity provider/model/version --redis-url-env MATHS_REDIS_URL
```

The included `deployment_bootstrap:provided_client` reads backend model settings from environment variables. A custom trusted provider may implement the same `chat` interface. Without `--runtime langgraph`, the same Redis flags launch a durable **Fake** demo. Do not expose this loopback service externally without the previously designed authentication proxy.

The graph reuses the staged profile, plan, solve, local checks, fidelity/audit, classified recovery and final acceptance. Its retrieve node generates the same structural query as the reference workflow, then calls typed local strategy search with the full problem, query, domain and proof obligations. The `tools-v3` response carries confidence-filtered planner/executor cards, preserving their complete examples only for high-confidence matches. Retrieval failure does not block solving. Local strategy calls can use the remaining retrieval pool up to 360 seconds; other tools retain the 30-second cap. The optional MCP server retains its own 30-second transport cap.

Each node gets a fresh adapter; JSON state retains the workflow start time, candidate drafts, individual audits/fidelity/checks and selected response. Evidence-backed audits route to local repair, proof completion, strategy rethink or global restart. Exhausted repairs enter final arbitration; missing primary output enters emergency recovery. These two internal nodes map to the existing public solve/verify stages, preserving HTTP/SSE stage names. Every final path applies bounded local acceptance checks before rendering. Failed assertions and evidence-refuted candidates cannot be returned merely because time ran out. Private thought tags are removed before candidate persistence.

Checkpoints are explicit **node-boundary AgentState snapshots owned by TaskStore**, not LangGraph's opaque internal saver format. LangGraph executes the edges; recovery validates the snapshot and enters its persisted `next_stage`. This keeps a node's checkpoint and completion event in the same Redis transaction instead of two independent commits. No automatic graph-node retry is configured; an incomplete node may repeat after recovery, while completed nodes are skipped. Provider calls inside an incomplete node are not exactly-once.

Redis records include Session, Task, immutable memory snapshot, accepted candidate, operation ledger/call counts, checkpoint and append-only events. WATCH/MULTI fences generations and makes checkpoint/completion atomic. Ten-second execution leases renew every three seconds; a scanner runs every five seconds, discovers expired leases, marks outstanding operations interrupted, and prioritizes compatible recovered tasks. Queued deliveries are reconciled from persistent state. Cancellation is terminal. Incompatible schema/code/prompt/config/client-identity snapshots stay interrupted with `checkpoint_incompatible`.

The shared staged runtime remains a library implementation; no submission runner or offline evaluator is restored. Deterministic parity tests compare model request messages, thinking flags, temperatures, token limits and outputs across normal, compact, repair, arbitration and emergency paths, and test recovery at node boundaries. This does not establish live-model answer accuracy or exactly-once provider execution. Started emergency/arbitration calls consume their persisted call budget even when interrupted; they cannot be freely replayed after a crash.

## Limits and later stages

Run one API worker for this reference deployment. In-memory mode loses all records on process restart; configured Redis AOF mode preserves them and readiness reports the selected storage/runtime truthfully. Both adapters use UUIDv4 IDs and numeric event cursors. Redis bounds active task claims across services sharing its namespace, but model permits, rate limiting, stream limits and task delivery remain process-local. Saturated recovery pickup, distributed model permits, Redis replication/failover, lifecycle retention and Redis Cluster are not production-complete.

Synchronous injected calls run off the event loop. Cancelling a task cannot forcibly terminate its client's thread: results/new calls are fenced and the model permit is held until that invocation actually returns. The injected client must honor its own timeouts and rate limits. Shutdown does not wait for uncooperative model threads. No new call is allowed after lost lease/storage authority. The 1,200-second absolute deadline is retained across recovery (downtime conservatively consumes remaining budget), with at least a 25-second return reserve.

For the M2-M5 reference commands, distributed deployment remains outside their boundary; use the separate M6 entrypoint below. M6 resolves the recorded offline baseline failures and adds PostgreSQL/Celery, deployment files, without claiming that container/quality gates have already passed. No live-model quality/latency/accuracy measurement has been performed.

## M4 typed tools and Function Calling

Install `requirements-platform-m4.txt`. Local tools and private MCP tools share Pydantic input/result schemas and the registry's timeout, retry, cancellation and trace policy. Only `strategy_search` and `math_verify` are exposed by the official SDK server; `sympy_calculate` stays local. Without the optional M5 document backend, `document_search` validates its Session scope but returns `unavailable`, never invented passages.

```powershell
.\.venv-platform\Scripts\python.exe -m pip install -r requirements-platform-m4.txt
# Supply your existing trusted client provider, not a replacement model client.
.\.venv-platform\Scripts\python.exe -m agent_platform --port 8003 --runtime langgraph --client-provider deployment_bootstrap:provided_client --mcp-tools --function-calling auto
```

`auto` enables native Function Calling only when the injected client's `chat` declares `tools`, or the client explicitly declares `supports_tools=True`. Minimal text-only clients keep the original protocol. `json` explicitly enables a bounded typed JSON tool-request fallback; `off` disables model-requested tools without disabling deterministic workflow tools. `native` is for a provider known to support native calls. The sample `InternChatClient` already declares native tool support; no sample-client changes are needed. Solver/repair calls allow two tool rounds, four calls per round and three total model turns; every model turn consumes the durable solver-call budget. The original call deadline is shared across the loop.

Calls use task/stage-scoped UUIDv5 IDs and bounded argument hashes/length summaries, not copies of raw problems or candidate text. This reference ledger does not implement the future PostgreSQL UUIDv7 entity model. At most 64 calls are retained per task. Completion results and events commit atomically, so a result committed before a node checkpoint is reused after recovery. Started attempts consume their budget even after a crash. Each call permits at most three transport attempts (30 seconds each by default), checking the remaining task budget first; only declared temporary failures retry. One separately recorded equivalent-local fallback is allowed for MCP search/verification transport failures. Schema drift or invalid results never trigger fallback. Concurrent duplicates within one execution share a lock; stale generations cannot commit late outcomes.

Every MCP connection checks names, input/output schemas and schema version before execution. The adapter only launches this repository's fixed stdio server, forwards no model credentials and opens no public listener. Each call has a fresh SDK session; connection startup overhead is included in the timeout. Results are capped at 64 KiB and sanitized at the application boundary. This is not a framing-level cap on arbitrary hostile SDK streams: only trusted private stdio transport is supported.

SymPy receives only an allow-listed AST constructed without `eval`, `sympify` or `parse_expr` of user strings. Numeric/node/exponent/function limits apply before calculation. Subprocesses are capped at 256 MiB, 5 seconds CPU and 5 seconds wall time. Windows uses a Job Object with kill-on-close/process memory/CPU limits; POSIX uses resource limits. Workers do not receive application secrets, and a Python audit hook denies socket operations and subprocess execution. Together with the fixed parser, this is a trusted mathematical worker, **not** an OS network namespace/AppContainer sandbox for arbitrary hostile Python or native extensions. Windows fails closed when Job attachment is unavailable. Other hosts must verify their resource-limit support before claiming parity.

`math_verify` checks explicitly extracted numeric equalities and reports concrete contradictions. It does not certify whole proofs, symbolic correspondence, all constraints or exhaustive boundaries: unsupported verification stays `uncertain` and enters fidelity/audit even at low risk. Existing formatting checks remain separate. Tool failure never creates a replacement value or deletes the accepted candidate.

M4 uses checkpoint schema `staged-graph-v2`. Old code/config/v1 snapshots remain interrupted rather than being silently migrated across changed verification/tool semantics. No live provider or RAG-quality evaluation was run. See `docs/design/single-agent-platform/m4-validation.md`.

An explicitly labelled Fake workflow can display the four real tool transports without calling a model:

```powershell
.\.venv-platform\Scripts\python.exe scripts/serve_platform_m4_demo.py --port 8002
```

Open `http://127.0.0.1:8002/trace-viewer`. This demo uses process-local storage, protocol fixtures and a non-mathematical final message, not real solving. The real graph is separately tested with injected protocol clients.

## Validation

M5-specific functional checks are documented below; labelled offline evaluation tooling has been removed.

```powershell
.\.venv-platform\Scripts\python.exe -m pytest tests/unit/test_platform_storage.py tests/test_platform_api.py -q
.\.venv-platform\Scripts\python.exe -m pytest tests/integration/test_platform_graph.py tests/integration/test_platform_redis.py -q
.\.venv-platform\Scripts\python.exe -m coverage run --branch --source=agent_platform --omit=agent_platform/__main__.py -m pytest tests/unit/test_platform_storage.py tests/test_platform_api.py -q
.\.venv-platform\Scripts\python.exe -m coverage report -m
.\.venv-platform\Scripts\python.exe scripts/smoke_platform.py --url http://127.0.0.1:8000
$env:MATHS_REDIS_URL="redis://127.0.0.1:6379/0"
.\.venv-platform\Scripts\python.exe scripts/smoke_platform_m3.py
# An unused port and a supplied redis-server executable are required:
.\.venv-platform\Scripts\python.exe scripts/smoke_redis_restart.py --redis-server redis-server --port 6388
```

Optional browser validation uses `pip install playwright` in this environment followed by `python scripts/check_platform_ui.py --channel msedge`. For a downloaded Chromium browser, install it with Playwright and adapt the browser channel to the available installation. Screenshots and coverage exports go under ignored `sample_outputs/platform_qa/`.

The HTTP test module skips explicitly when FastAPI/httpx are absent; installing the default Web requirements enables it. Pure storage and reasoning tests do not need HTTP dependencies.

M3 smoke uses fixed **protocol fixtures**, not math benchmarks. It abruptly exits a graph worker after the completed solve checkpoint and resumes it using fresh service/runtime/store/client objects; it asserts no completed-solve replay. The Redis restart script creates and kills only its own dedicated temporary Redis process, verifies AOF recovery of Session/Task/checkpoint/events, and removes its generated temporary data. These scripts never load reference answers or call a live model.

M4 tool tests: `python -m pytest tests/test_platform_tools.py tests/test_platform_tool_isolation.py tests/test_platform_function_calling.py tests/test_platform_mcp.py -q`. `scripts/smoke_platform_m4.py` uses the Redis URL environment variable to crash after a real MCP outcome commits, then asserts recovery with zero completed-tool reexecution. Browser QA for the M4 fake demo: `python scripts/check_platform_ui.py --url http://127.0.0.1:8002 --expected-events 31`.

## M5 document ingestion and hybrid RAG

Install `requirements-platform-m5.txt`; weights must already exist locally. Neither the application nor the encoder downloads weights or calls an embedding API. The only generative client remains application-injected. Minimal real-retrieval/Fake-reasoning demo:

```powershell
.\.venv-platform\Scripts\python.exe -m pip install -r requirements-platform-m5.txt
.\.venv-platform\Scripts\python.exe scripts/serve_platform_m5_demo.py --port 8003
```

Open `http://127.0.0.1:8003/trace-viewer`, select a Session, upload PDF/Markdown and wait for `ready`, then submit a problem. This demo retrieves real references but explicitly generates no mathematical answer. Normal chat does not use this experimental reference workflow.

To connect the real LangGraph workflow with your injected client, choose an unused port and add these flags to the M3/M4 launch command:

```powershell
--rag-dir sample_outputs/platform_rag --embedding-model-dir strategyrag/Qwen3-Embedding-0.6B
```

Use persistent Redis Session/Task storage for Session IDs to survive API restarts. Document metadata and Qdrant persist independently, but memory-only Session records do not. Run **one process** per private RAG directory; an OS file lock rejects a second owner, including an offline evaluator while that server is running. Remote Qdrant clients can be injected into `DocumentService`, but collections must be dedicated to this document service, never shared between independent authorities. Distributed ownership, PostgreSQL metadata and deployment workers remain M6.

`POST /v1/sessions/{session_id}/documents` takes multipart `file`, plus optional `domain`, `problem_type`, `source`. Accepted pairs are `.pdf`/`application/pdf` and `.md` or `.markdown`/`text/markdown`. The body is bounded before multipart parsing (20 MiB + 64 KiB framing allowance); the file itself is capped at 20 MiB, with signature/UTF-8/parser checks. The response is `202` with a status URL; `GET` that URL returns indexing/ready/failed/expired, chunk/page counts, versions and a fixed error code, never private storage keys. Ready documents become searchable only after all dense/sparse points and catalog records commit.

SQLite WAL/FULL is the **reference metadata authority**, not a replacement for the approved PostgreSQL selection. Quarantine blobs are hashed/fsynced/renamed before metadata reservation. Same-content uploads within a Session return `409`; this reference catalog retains the uniqueness reservation even for failed/expired records. Up to 16 documents may be indexing. New uploads reject insufficient disk space. A single ingestion worker scans durable indexing records on startup; shutdown waits for actual index threads before releasing ownership. Complete, immutable Session collections are published by an atomic catalog pointer change. Failed shadow writes cannot replace the old snapshot. Maintenance every ten seconds removes unreferenced collections and blobs older than one hour; 90-day expired documents are excluded immediately and then their points/blobs/chunks are cleaned.

The fixed parser subprocess is read-only/no-socket/no-child-execution through audit hooks, with Windows Job or POSIX resource limits: 512 MiB, 30 seconds CPU/wall, 500 pages, 10,000 chunks and two million extracted characters. Scans without extractable text fail; OCR is not implemented. This is not an OS network/filesystem sandbox for arbitrary hostile native code. POSIX host behavior needs separate validation. Markdown display/inline math and code fences remain atomic; blocks over 2,000 characters fail instead of splitting a formula. Chunks target 1,200 characters and keep PDF page numbers and Markdown headings.

The offline encoder uses local Qwen3-Embedding-0.6B, normalized 1,024-dimensional vectors, 512-token input and batch size four. Its identity hashes weights and model/tokenizer/pooling/prompt configuration. BM25L (`rank-bm25==0.2.2`, k1=1.5, b=0.75, delta=0.5) uses versioned Unicode/Chinese-bigram/Latin/LaTeX tokens; inserting a document rebuilds the Session's sparse corpus and reuses existing dense vectors. Each route recalls up to 20 candidates; their union has at most 40. D-6 reranks with `0.45*dense_rank + 0.35*sparse_rank + 0.10*formula_jaccard + 0.10*metadata_match`, rank score `61/(60+rank)`, then Chunk-ID ties. This deterministic feature reranker is not a learned cross-encoder. The workflow takes final top-five; the typed tool permits an explicit top-k up to 20. Session, ready document IDs, index version and supplied metadata filters all apply in Qdrant and are checked at egress.

Retrieve-node passages enter a separate `untrusted_reference_evidence` user payload, including the default compressed solver path, never the system instructions or a tool request. Accepted evidence is bounded and checkpointed. Trace references contain Chunk/Document IDs, pages, source metadata, component scores and versions, not document bodies. Retrieval success means `available_not_proven_used`; only a draft containing a retrieved Chunk ID creates `retrieval.cited`, explicitly labelled model-reported rather than independently verified usage. Prompt delimiting cannot guarantee a model ignores every injection. Verification still operates against the original problem.

M5 uses `tools-v2` and graph schema `staged-graph-v3`. RAG configuration participates in checkpoint identity; incompatible old snapshots remain interrupted. Retrieval/tool failures do not erase accepted candidates. Model-requested document searches use the same typed scope, timeout, result-replay and trace policy.

Functional verification:

```powershell
.\.venv-platform\Scripts\python.exe -m pytest tests/test_platform_rag.py tests/test_platform_rag_graph.py tests/test_platform_rag_isolation.py -q
.\.venv-platform\Scripts\python.exe scripts/smoke_platform_m5.py
.\.venv-platform\Scripts\python.exe scripts/check_platform_m5_ui.py --url http://127.0.0.1:8003
```

## M6 distributed delivery

Status: engineering code and native transport tests delivered; release acceptance is **partial**. Docker is unavailable on the development machine. Image versions, container builds, remote Qdrant, container RAG and GitHub CI are not verified here. The user requested wrap-up without forcing these gates closed.

With Docker Engine/Compose installed and a URL-safe PostgreSQL password supplied through the environment:

```powershell
$env:MATHS_DB_PASSWORD = "<operator-provided URL-safe password>"
docker compose up --build --wait
```

Defaults: `http://127.0.0.1:8004/trace-viewer`, `/docs`, `/metrics`; Prometheus at `http://127.0.0.1:9094`. Change `MATHS_API_PORT` / `MATHS_METRICS_PORT` if occupied. Only API/Prometheus bind host loopback; database, broker and vector ports stay internal. Named volumes retain data. `docker compose down` stops services without deleting those volumes. Do not use `down --volumes` on data you need.

Services are PostgreSQL, Redis AOF/always, Qdrant, explicit one-shot migration, API, normal Celery Worker, reserved recovery Worker and Prometheus. Default runtime is visibly **Fake**, with no model calls and document RAG disabled. The API discovers committed queued rows instead of executing the graph in-process. Celery messages contain Session/Task IDs only; its Redis keys share the deployment namespace prefix. PostgreSQL transactions fence generations and atomically persist checkpoints, tool outcomes and events. Redis Streams are a delivery cache; missing/expired/broken streams replay authoritative PostgreSQL events.

There are eight global task leases and eight global model slots. Normal workers admit at most seven model calls, leaving one for recovery; the dedicated recovery worker admits up to the total eight. Redis capacity loss starts no new calls and discards late results after failed renewal. Call timeouts are bounded at 720 seconds, with 780-second renewed permits. Uncooperative injected clients and repeated crashes of recovery workers can still defeat a 30-second saturated recovery target; no such SLO is claimed. The observed 12.17-second crash recovery used Fake reasoning.

Use one API process per ingestion volume. PostgreSQL is the document catalog in M6; readers use shared advisory locks and ingestion/cleanup uses an exclusive index lock. Worker readers do not need blob access. No SQLite document authority is used by this entrypoint. API resource shutdown closes the injected infrastructure clients after its ingestion/service shutdown.

### Real provider and document RAG

The trusted `MATHS_CLIENT_PROVIDER=module:function` returns the application's model client with a compatible `chat` interface. Configure credentials in the application bootstrap, outside reasoning nodes. `MATHS_CLIENT_IDENTITY` is a versioned provider/model identity. Mount operator-owned integration code and frozen local Qwen weights using:

```powershell
$env:MATHS_RUNTIME = "langgraph"
$env:MATHS_CLIENT_PROVIDER = "deployment_bootstrap:provided_client"
$env:MATHS_CLIENT_IDENTITY = "provider/model/version"
$env:MATHS_INTEGRATION_DIR = "<trusted integration directory>"
$env:MATHS_EMBEDDING_MODEL_DIR = "<frozen local Qwen model directory>"
docker compose -f compose.yaml -f compose.rag.yaml up --build --wait
```

The `rag` image installs the optional encoder runtime but includes no weights. It does not download weights at startup. Configure any provider-specific secret passthrough in an operator-owned Compose override or secret mechanism; secrets are not built into the image. The Docker allow-list excludes datasets, generated outputs, local models and `.env`. Existing `strategy_data` is intentionally not packaged; mount your frozen strategy corpus separately for legacy lexical strategy lookup. A missing strategy corpus degrades retrieval, never invents evidence.

### Verification and metrics

```powershell
python -m pip install -r requirements-platform-dev.txt
$env:MATHS_TEST_DATABASE_URL = "<disposable PostgreSQL connection URL>"
python scripts/check_platform_ci.py
python scripts/smoke_platform_m6.py --url http://127.0.0.1:8004 --compose
```

Without `MATHS_TEST_DATABASE_URL`, integration tests explicitly skip and the checkpoint coverage gate is expected to fail. The gate runs lint, 14 typed interface/deployment modules and all tests, then enforces pure branch coverage separately for routing, checkpoint, tool-error, answer-recovery and API groups. It does not claim that every legacy module is statically typed. GitHub CI additionally builds the minimal runtime image and runs Compose/Fake smoke, with a ten-minute job timeout; actual runner timing is pending.

On Windows without Docker, an explicitly limited transport fixture is available:

```powershell
$env:MATHS_TEST_DATABASE_URL = "<scratch PostgreSQL URL>"
$env:MATHS_TEST_REDIS_URL = "<Redis URL with AOF/always>"
python scripts/smoke_platform_m6_native.py
```

It owns three private subprocesses on unused port 8004, a random database schema and namespaced broker keys. It uses **embedded Qdrant and Fake reasoning**, measures 30 task submissions at 10 RPS across six Sessions, kills only its own normal Worker, verifies reserved-worker recovery and completed-stage replay, then stops its processes and removes only its scratch schema/keys. It neither stops existing demos nor validates Docker/remote Qdrant.

Prometheus exposes finite-label API/operation/task histograms, token counts and missing-usage counters, tool outcomes, repair-stage counts, authoritative task states and recovered terminal outcomes. Acceptance-to-first-SSE is persisted once per Task, separate from per-connection first-frame latency. P50/P95 derive from histograms; repair-stage counts measure execution frequency and do not establish mathematical correctness. Rules cover API availability, admission latency, first status, heartbeat gaps, unresolved interruptions, missing usage, stalled discovery, cleanup failure and document-volume disk thresholds.

`GET /health/summary` adds bounded operational diagnostics to readiness. Unavailable required dependencies still return **503**; warning-only conditions return **200** with `status: degraded`, so monitoring failures or a cleanup error do not trigger an unhealthy-service restart loop. `/health/ready` retains its existing response contract. Database/dependency probes run outside the event loop. The summary exposes the four discovery phases (`cleanup`, `recovery`, `dispatch`, `events`), cumulative process-local failure counts, last-success times (monotonic seconds, not timestamps), and time since the last cycle. Each phase continues independently; one failed task does not block other recovery/dispatch attempts. Cleanup failure retries after 60 seconds; successful cleanup runs hourly. Shutdown waits for the in-flight discovery thread before infrastructure clients close.

With RAG enabled, the API samples its document-volume filesystem every 15 seconds: **70%** usage warns and **85%** is critical. This is not document quota accounting and does **not** monitor PostgreSQL, Redis, Qdrant or Prometheus storage volumes. Their capacity monitoring remains operator work. No disk path enters metrics or health responses. New metrics are `maths_operational_degraded`, `maths_dispatcher_cycle_age_seconds`, `maths_background_failures_total{phase=...}`, `maths_document_filesystem_usage_ratio` and `maths_document_filesystem_free_bytes`; disk metrics are absent when RAG is disabled or a disk sample fails.

Optional `MATHS_PROMETHEUS_URL` enables cached `/api/v1/alerts` polling. Compose supplies `http://prometheus:9090` to the API only. The internal trusted URL must be HTTP(S), without embedded credentials. Polling has a two-second HTTP timeout, a 64-KiB decoded response limit and a 256-alert limit; redirects and ambient HTTP proxies are disabled. Only recognized firing alert names are exposed, never labels/annotations. HTTP summary/metrics requests do not query Prometheus. Poll failures are reported as `prometheus_unavailable`; a sample older than twice the interval plus two seconds is `monitor_stale`. Real Prometheus and its rule evaluation under Compose have not been executed on this machine; deterministic protocol/fault tests are not a replacement for that deployment check.

Terminal Task/message/event/idempotency records older than 30 days are cleaned in hourly bounded batches; active/interrupted tasks are retained. Document blobs/chunks expire at 90 days through ingestion maintenance. Expired/failed document catalog tombstones and Sessions linked to them remain retained; full lifecycle compaction is not delivered. Local diagnostic artifacts are never part of automatic cleanup.

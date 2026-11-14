"""Synthetic solver-profile and routing checks; no external model requests."""
import asyncio
import copy
import json
import threading
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import pytest

from agent_platform.agent.execution import TracedClient
from agent_platform.app import create_app
from agent_platform.bootstrap import ConfiguredSolveClient, SolveClientRouter, build_solve_client
from agent_platform.models import PlatformError
from agent_platform.reasoning_runtime import LangGraphRuntime
from agent_platform.runtime import CheckpointIncompatible, FakeRuntime, RuntimeResult
from agent_platform.service import TaskService
from agent_platform.solve_agents import (
    BUILTIN_ID, REQUEST_KEY, SNAPSHOT_KEY, SOLVE_CALLS, SolveAgentDraft, SolveAgents, snapshot_hash,
)
from agent_platform.storage import InMemoryTaskStore
from test_platform_graph import ScriptedClient, config, context, draft


def profile(**updates):
    return SolveAgentDraft.model_validate({"name": "Custom solver", "model": "solver-v1",
        "api_url": "https://models.example/v1/chat/completions", **updates})


def test_metadata_sanitization_preserves_public_urls_and_redacts_windows_paths():
    from agent_platform.safety import sanitize_text
    assert sanitize_text("https://example.com/v1/chat/completions") == "https://example.com/v1/chat/completions"
    assert sanitize_text(r"error at C:\Users\admin\data") == "error at [local path]"


def test_catalog_versions_default_and_retained_snapshots(tmp_path):
    agents = SolveAgents(tmp_path)
    item = agents.save(profile())
    frozen = agents.freeze(item["id"])
    agents.default(item["id"], 1)
    assert agents.freeze() == frozen
    updated = agents.save(profile(model="solver-v2"), item["id"], 1)
    assert updated["revision"] == 2
    assert agents.freeze()["model"] == "solver-v2"
    assert frozen["model"] == "solver-v1"
    with pytest.raises(PlatformError, match="solve_agent_conflict"):
        agents.delete(item["id"], 1)
    disabled = agents.save(profile(enabled=False), item["id"], 2)
    assert agents.list()["default_id"] == BUILTIN_ID
    with pytest.raises(PlatformError, match="solve_agent_disabled"):
        agents.freeze(item["id"])
    agents.delete(item["id"], disabled["revision"])
    assert len(agents.list()["items"]) == 1
    assert agents.db.execute("SELECT count(*) FROM agent_revisions").fetchone()[0] == 3
    assert SolveAgents(tmp_path).list()["items"] == agents.list()["items"]


@pytest.mark.parametrize("updates", [
    {"api_url": "https://user:password@example.com/v1/chat/completions"},
    {"api_url": "https://example.com/v1/chat/completions?api_key=secret"},
    {"api_url": "file:///some/path"}, {"api_url": "https://example.com/v1"},
    {"credential_env": "HOME"}, {"credential_env": "actual-secret"},
    {"name": " "}, {"model": " "}, {"temperature": float("nan")},
])
def test_invalid_or_secret_config_never_echoed(tmp_path, updates):
    with TestClient(create_app(solve_agents=SolveAgents(tmp_path), rate_limits=False)) as api:
        body = profile().model_dump()
        body.update(updates)
        # JSON forbids NaN at the transport boundary as well.
        response = api.post("/v1/solve-agents", content=json.dumps(body), headers={"Content-Type": "application/json"})
        assert response.status_code == 400
        assert response.json() == {"error": {"code": "invalid_request"}}


def test_credential_references_and_api_crud_do_not_make_model_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_SOLVER_API_KEY", "private-testing-value-54321")
    tester = Mock(side_effect=TimeoutError("private-testing-value-54321"))
    agents = SolveAgents(tmp_path, tester=tester)
    with TestClient(create_app(solve_agents=agents, rate_limits=False)) as api:
        item = api.post("/v1/solve-agents", json=profile(credential_env="QA_SOLVER_API_KEY").model_dump()).json()
        url = "/v1/solve-agents/" + item["id"]
        assert item["credential_ready"] and not tester.called
        assert "private-testing-value" not in api.get("/v1/solve-agents").text
        result = api.post(url + "/test?revision=1")
        assert result.json() == {"ok": False, "error_code": "model_timeout"}
        assert "private-testing-value" not in result.text
        assert tester.call_count == 1
        assert api.post(url + "/default?revision=1").status_code == 200
        assert api.delete(url + "?revision=1").status_code == 200
        assert api.post("/v1/solve-agents", json=profile(preference="private-testing-value-54321").model_dump()).status_code == 400
    monkeypatch.delenv("QA_SOLVER_API_KEY")
    item = agents.save(profile(credential_env="QA_SOLVER_API_KEY"))
    with pytest.raises(PlatformError, match="solve_agent_credential_missing"):
        agents.freeze(item["id"])


@pytest.mark.parametrize("storage", ["memory", "redis"])
def test_submission_freezes_and_idempotency_replays_original_after_edit_delete(tmp_path, storage):
    agents = SolveAgents(tmp_path)
    item = agents.save(profile())
    agents.default(item["id"], 1)
    store = InMemoryTaskStore()
    if storage == "redis":
        from agent_platform.redis_store import RedisTaskStore
        import fakeredis
        store = RedisTaskStore(fakeredis.FakeRedis(decode_responses=True), require_aof=False)
    session = store.create_session(4000).id
    service = TaskService(store, FakeRuntime())
    service.accepting, service.solve_agents = True, agents
    first = service.submit(session, "Question", {}, "request")
    changed = agents.save(profile(model="v2"), item["id"], 1)
    agents.delete(changed["id"], 2)
    replay = service.submit(session, "Question", {}, "request")
    assert replay.id == first.id
    assert replay.metadata[SNAPSHOT_KEY]["model"] == "solver-v1"
    with pytest.raises(PlatformError, match="idempotency_conflict"):
        service.submit(session, "Question", {}, "request", solve_agent_id=BUILTIN_ID)
    with pytest.raises(PlatformError, match="idempotency_conflict"):
        service.submit(session, "Different question", {}, "request")
    assert store.get_task(session, first.id).metadata == first.metadata
    assert service.submit(session, "New question", {}, "new").metadata[SNAPSHOT_KEY]["id"] == BUILTIN_ID


def test_legacy_submission_replay_keeps_original_metadata(tmp_path):
    store = InMemoryTaskStore()
    session = store.create_session(4000).id
    original, _ = store.create_task(session, "Question", {}, "fake", "legacy")
    service = TaskService(store, FakeRuntime())
    service.accepting, service.solve_agents = True, SolveAgents(tmp_path)
    replay = service.submit(session, "Question", {}, "legacy")
    assert replay.id == original.id and replay.metadata == {}


def test_solver_snapshot_survives_storage_metadata_field_limit(tmp_path):
    from agent_platform.redis_store import RedisTaskStore
    import fakeredis
    store = RedisTaskStore(fakeredis.FakeRedis(decode_responses=True), require_aof=False)
    session = store.create_session(4000).id
    agents = SolveAgents(tmp_path)
    item = agents.save(profile())
    service = TaskService(store, FakeRuntime())
    service.accepting, service.solve_agents = True, agents
    task = service.submit(session, "Question", {str(index): index for index in range(100)}, "key", solve_agent_id=item["id"])
    assert task.metadata[SNAPSHOT_KEY] == agents.freeze(item["id"])


def test_api_task_selection_public_summary_and_reserved_metadata(tmp_path):
    agents = SolveAgents(tmp_path)
    item = agents.save(profile())
    with TestClient(create_app(runtime=FakeRuntime(.001), solve_agents=agents, rate_limits=False)) as api:
        session = api.post("/v1/sessions", json={}).json()["id"]
        path = f"/v1/sessions/{session}/tasks"
        response = api.post(path, json={"problem": "Question", "solve_agent_id": item["id"]})
        assert response.status_code == 202
        summary = response.json()["solve_agent"]
        assert summary == {"id": item["id"], "revision": 1, "name": item["name"], "model": item["model"]}
        assert "api_url" not in response.text and "credential_env" not in response.text
        for key in (SNAPSHOT_KEY, REQUEST_KEY):
            assert api.post(path, json={"problem": "Question", "metadata": {key: {}}}).status_code == 400


@pytest.mark.parametrize("role", [*sorted(SOLVE_CALLS), "classifier", "strategy", "targeted_audit", "model_fidelity", "final_arbitrator"])
def test_all_roles_route_and_trace_actual_agent(tmp_path, role):
    agents = SolveAgents(tmp_path)
    snapshot = agents.freeze(agents.save(profile())["id"])
    default, solver = ScriptedClient(["default"]), ScriptedClient(["solver"])
    default.model, solver.model = "control-v1", "solver-v1"
    ctx, events, _ = context()
    ctx.function_calling = "off"
    proxy = TracedClient(SolveClientRouter(default, solver, snapshot), ctx, "solve", threading.BoundedSemaphore(1))
    proxy.call_type = role
    result = proxy.chat(messages=[], temperature=.3, max_tokens=100, request_timeout=10)
    selected = role in SOLVE_CALLS
    assert result == ("solver" if selected else "default")
    details = [payload["agent"] for _, kind, payload in events if kind.startswith("model.")]
    assert len(details) == 2
    assert all(value["id"] == (snapshot["id"] if selected else BUILTIN_ID) for value in details)
    assert all(value["role"] == ("solve" if selected else "control") for value in details)
    assert "api_url" not in json.dumps(events)


def test_generic_client_uses_instance_credentials_and_omits_intern_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("QA_SOLVER_API_KEY", "test-credential")
    monkeypatch.setenv("INTERN_API_KEY", "original-default-credential")
    agents = SolveAgents(tmp_path)
    item = agents.save(profile(credential_env="QA_SOLVER_API_KEY", max_tokens=1024, timeout=30, preference="Use exact arithmetic."))
    client = build_solve_client(agents.freeze(item["id"]))
    response = Mock()
    response.json.return_value = {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}
    with patch("llm_client.requests.post", return_value=response) as post:
        assert client.chat(messages=[], max_tokens=4096, request_timeout=10, thinking_mode=True) == "OK"
    sent = post.call_args.kwargs
    payload = json.loads(sent["data"])
    assert payload["model"] == "solver-v1" and payload["max_tokens"] == 1024
    assert "thinking_mode" not in payload
    assert payload["temperature"] == .3
    assert "Use exact arithmetic." in payload["messages"][-1]["content"]
    assert sent["headers"]["Authorization"] == "Bearer test-credential"
    import os
    assert os.environ["INTERN_API_KEY"] == "original-default-credential"
    assert sent["timeout"] <= 10


def test_configured_limits_cannot_extend_phase_budget():
    client = Mock(model="test")
    client.chat.return_value = "result"
    wrapped = ConfiguredSolveClient(client, profile(timeout=600, max_tokens=8192))
    ctx, _, _ = context()
    ctx.function_calling = "off"
    proxy = TracedClient(wrapped, ctx, "solve", threading.BoundedSemaphore(1))
    proxy.chat(messages=[], request_timeout=3, max_tokens=300)
    assert 0 < client.chat.call_args.kwargs["request_timeout"] <= 3
    assert client.chat.call_args.kwargs["max_tokens"] == 300


def test_concurrent_tasks_have_separate_solver_clients_and_shared_permits(tmp_path, monkeypatch):
    agents = SolveAgents(tmp_path)
    snapshots = [agents.freeze(agents.save(profile(model=model))["id"]) for model in ("one", "two")]
    default = Mock(model="control")
    def factory(snapshot):
        return Mock(model=snapshot["model"])
    runtime = LangGraphRuntime(default, config(), solve_client_factory=factory, solve_router_factory=SolveClientRouter)

    async def inspect(task_runtime, ctx, digest):
        await asyncio.sleep(.01)
        actual, summary = task_runtime.client.resolve("solver")
        assert actual.model == ctx.metadata[SNAPSHOT_KEY]["model"]
        assert task_runtime.client.resolve("targeted_audit")[0] is default
        assert task_runtime.permits is runtime.permits
        return RuntimeResult(summary["model"])

    monkeypatch.setattr(LangGraphRuntime, "_run", inspect)
    async def concurrent():
        contexts = [context()[0] for _ in snapshots]
        for ctx, snapshot in zip(contexts, snapshots):
            ctx.metadata[SNAPSHOT_KEY] = snapshot
        results = await asyncio.gather(*(runtime.run(ctx) for ctx in contexts))
        return [result.final_response for result in results]
    assert asyncio.run(concurrent()) == ["one", "two"]
    assert runtime.client is default


def test_graph_checkpoint_binds_only_frozen_solver_and_recovers_after_catalog_changes(tmp_path):
    agents = SolveAgents(tmp_path)
    item = agents.save(profile())
    snapshot = agents.freeze(item["id"])
    default = ScriptedClient(['{"answer_mode":"computation","domain":"linear_algebra"}',
                              '{"risk_level":"high"}', '{"verdict":"pass"}', '{"verdict":"pass"}'])
    solver = ScriptedClient([draft()])
    runtime = LangGraphRuntime(default, config(), solve_client_factory=lambda _: solver, solve_router_factory=SolveClientRouter)
    ctx, events, checkpoints = context()
    ctx.metadata[SNAPSHOT_KEY] = snapshot
    assert asyncio.run(runtime.run(ctx)).final_response == r"\boxed{2}"
    assert len(default.calls) == 4 and len(solver.calls) == 1
    assert checkpoints[-1]["solve_agent_hash"] == snapshot_hash(snapshot)
    agents.save(profile(name="Unrelated", model="other"))
    agents.delete(item["id"], 1)
    assert all(runtime.checkpoint_compatible(value) for value in checkpoints)
    for index in (2, 4, 6):
        state = copy.deepcopy(checkpoints[index])
        default.responses = ['{"verdict":"pass"}', '{"verdict":"pass"}'] if index == 4 else (
            ['{"verdict":"pass"}', '{"verdict":"pass"}'] if index == 2 else [])
        solver.responses = [draft()] if index == 2 else []
        resumed, _, _ = context(state, ctx.deadline_at)
        resumed.metadata[SNAPSHOT_KEY] = snapshot
        assert asyncio.run(runtime.run(resumed)).final_response == r"\boxed{2}"
    tampered, _, _ = context(checkpoints[-1], ctx.deadline_at)
    tampered.metadata[SNAPSHOT_KEY] = {**snapshot, "model": "different"}
    with pytest.raises(CheckpointIncompatible):
        asyncio.run(runtime.run(tampered))
    assert not runtime.checkpoint_compatible({**checkpoints[-1], "solve_agent_hash": []})


def test_question_batch_freezes_on_begin_and_retries_original_profile(tmp_path):
    from agent_platform.question_batches import QuestionBatchService
    from agent_platform.models import utc_now

    agents = SolveAgents(tmp_path / "agents")
    item = agents.save(profile())
    store = InMemoryTaskStore()
    session = store.create_session(4000).id
    tasks = TaskService(store, FakeRuntime())
    tasks.accepting, tasks.solve_agents = True, agents
    batches = QuestionBatchService(tmp_path / "questions", tasks)
    batches.accepting = True
    batch = {"id": "batch", "session_id": session, "content_hash": "hash", "status": "ready",
        "created_at": utc_now().isoformat(), "original_name": "test.md", "options": {"document_ids": [], "response_style": "auto"},
        "questions": [{"number": 1, "label": "One", "problem": "Question", "page_start": None, "page_end": None, "task_id": None, "attempt": 0}]}
    batches.catalog.create(batch)
    frozen = batches.begin(session, "batch", "Explain", "auto", item["id"])
    updated = agents.save(profile(model="new-model"), item["id"], 1)
    agents.delete(item["id"], updated["revision"])
    assert batches.begin(session, "batch", "Explain", "auto", item["id"])["solve_agent"] == frozen["solve_agent"]
    with pytest.raises(PlatformError, match="question_start_conflict"):
        batches.begin(session, "batch", "Explain", "auto", BUILTIN_ID)
    asyncio.run(batches._advance(frozen))
    batch = batches.catalog.get(session, "batch")
    task = store.get_task(session, batch["questions"][0]["task_id"])
    assert task.metadata[SNAPSHOT_KEY]["model"] == "solver-v1"
    store.cancel(session, task.id)
    retry = batches.retry(session, "batch", 1)
    asyncio.run(batches._advance(retry))
    batch = batches.catalog.get(session, "batch")
    task = store.get_task(session, batch["questions"][0]["task_id"])
    assert task.metadata[SNAPSHOT_KEY] == frozen["solve_agent"]
    asyncio.run(batches.stop())

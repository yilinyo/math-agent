import asyncio
import copy
import threading
from unittest.mock import Mock

import pytest
from langgraph.graph import StateGraph, START, END

from agent_platform import observability as obs


def test_tracing_requires_own_key(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("INTERN_API_KEY", "unrelated")
    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        obs.tracing_enabled()


def test_redaction_keeps_debug_content_but_removes_credentials(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "live-model-credential")

    class Client:
        def __repr__(self):
            raise AssertionError("Never serialize a client with repr")

    inputs = {"prompt": "Solve x+1=2. live-model-credential",
              "headers": {"Authorization": "Bearer hidden"},
              "nested": {"api_key": "hidden", "client": Client()},
              "object": Client(), "path": "/Users/example/project/private.py"}
    operations = [{"id": "run", "name": "solve", "error": "secret path response",
                   "inputs": inputs, "outputs": {"state": {"draft": "x=1"}},
                   "extra": {"metadata": {"ls_model_name": "test-model"}},
                   "serialized": "private", "attachments": "private"}]
    result = obs.redact_runs(copy.deepcopy(operations))
    assert result[0]["id"] == "run"
    assert result[0]["inputs"]["prompt"] == "Solve x+1=2. [redacted]"
    assert result[0]["outputs"] == {"state": {"draft": "x=1"}}
    assert result[0]["extra"]["metadata"]["ls_model_name"] == "test-model"
    assert result[0]["inputs"]["object"] == "[unsupported object]"
    assert "hidden" not in str(result) and "live-model-credential" not in str(result)
    assert "/Users/" not in str(result) and "private" not in str(result)
    assert inputs["prompt"].endswith("live-model-credential")


@pytest.mark.parametrize("raw,expected_counts", [
    ({"content": "x=1", "_usage": {"prompt_tokens": 10, "completion_tokens": 3}},
     {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}),
    ({"content": "x=1", "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}},
     {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}),
    ("x=1", {}),
])
def test_model_trace_captures_messages_response_and_usage(monkeypatch, raw, expected_counts):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    client = Mock()
    monkeypatch.setattr(obs, "tracing_client", lambda: client)
    model = Mock(model="test-model")
    model.chat.return_value = raw
    assert obs.invoke_model(model, {"messages": [{"role": "user", "content": "Solve x+1=2"}]}, "solve") is raw
    start = client.create_run.call_args.kwargs
    assert start["inputs"]["messages"][0]["content"] == "Solve x+1=2"
    outputs = client.update_run.call_args.kwargs["outputs"]
    assert outputs["choices"][0]["message"]["content"] == "x=1"
    assert outputs.get("usage_metadata", {}) == expected_counts


def test_graph_and_model_have_parent_child_traces(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    client = Mock()
    monkeypatch.setattr(obs, "tracing_client", lambda: client)
    model = Mock()
    model.chat.return_value = "unchanged"

    async def solve(state):
        from agent_platform.agent.execution import TracedClient
        from agent_platform.runtime import RuntimeContext

        context = RuntimeContext("task", "session", "private problem", {}, (), None, lambda *args: None)
        proxy = TracedClient(model, context, "solve", threading.BoundedSemaphore(1))
        proxy.call_type = "solver"
        results = []

        def invoke_in_legacy_thread():
            thread = threading.Thread(target=lambda: results.append(proxy._chat_once(messages=[])))
            thread.start()
            thread.join()
            return results[0]

        result = await asyncio.to_thread(invoke_in_legacy_thread)
        return {"result": result}

    graph = StateGraph(dict)
    graph.add_node("solve", solve)
    graph.add_edge(START, "solve")
    graph.add_edge("solve", END)

    async def run():
        with obs.graph_tracing("test-task") as config:
            return await graph.compile().ainvoke({}, config)

    assert asyncio.run(run()) == {"result": "unchanged"}
    from langchain_core.tracers.langchain import wait_for_all_tracers
    wait_for_all_tracers()
    starts = [call.kwargs for call in client.create_run.call_args_list]
    solver = next(run for run in starts if run.get("name") == "solver")
    node = next(run for run in starts if run.get("name") == "solve")
    assert str(solver["parent_run_id"]) == str(node["id"])
    client.flush.assert_called_once_with(timeout=0)


def test_runtime_logs_progress_counts_but_never_payload_text(capsys):
    from agent_platform.runtime import RuntimeContext

    context = RuntimeContext("task", "session", "private problem", {}, (), None, lambda *args: None)
    context.progress("retrieve")
    context.record("retrieve", "retrieval.completed", {"hit_count": 3, "references": ["private strategy"]})
    context.record("solve", "model.completed", {
        "duration_ms": 12, "usage": {"total_tokens": 20}, "content": "private response"})
    context.progress("retrieve", completed=True, checkpoint={"private state": "secret"})
    output = capsys.readouterr().out
    assert "[节点开始] retrieve" in output and "[节点完成] retrieve" in output
    assert "命中条数=3" in output and "total_tokens=20" in output
    assert "private" not in output and "secret" not in output

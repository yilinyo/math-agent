"""Verify the environment switch at the model HTTP and public-event boundaries."""
import json
import threading
from unittest.mock import Mock, patch

import pytest

from agent_platform.agent.execution import TracedClient
from agent_platform.runtime import RuntimeContext
from llm_client import InternChatClient


@pytest.mark.parametrize("setting,streaming", [(None, True), ("true", True), ("false", False)])
@pytest.mark.parametrize("call_type", [
    "solver", "solver_compressed", "solver_repair",
    "emergency_direct_solver", "emergency_integrator", "final_arbitrator",
])
def test_model_streaming_switch_preserves_complete_answers_and_usage(monkeypatch, setting, streaming, call_type):
    monkeypatch.setenv("INTERN_API_KEY", "test-credential")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    if setting is None:
        monkeypatch.delenv("MATHS_MODEL_STREAMING", raising=False)
    else:
        monkeypatch.setenv("MATHS_MODEL_STREAMING", setting)
    events = []
    context = RuntimeContext("task", "session", "problem", {}, (), None, lambda *args: None,
                             record=lambda stage, kind, payload: events.append((kind, payload)))
    context.function_calling = "off"
    proxy = TracedClient(InternChatClient(), context, "solve", threading.BoundedSemaphore(1))
    proxy.call_type = call_type
    proxy.public_sections = ("Final Answer",)
    content = "## Final Answer\nx=2\n"
    usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    http = Mock()
    if streaming:
        http.headers = {"Content-Type": "text/event-stream"}
        http.iter_lines.return_value = [
            ("data: " + json.dumps({"choices": [{
                "index": 0, "delta": {"content": content}, "finish_reason": "stop",
            }], "usage": usage})).encode(), b"", b"data: [DONE]", b"",
        ]
    else:
        http.json.return_value = {"choices": [{
            "message": {"role": "assistant", "content": content}, "finish_reason": "stop",
        }], "usage": usage}

    with patch("llm_client.requests.post", return_value=http) as post:
        result = proxy.chat(messages=[], return_message=True, thinking_mode=True, max_tokens=131072)

    request = post.call_args.kwargs
    payload = json.loads(request["data"])
    assert payload.get("stream", False) is streaming
    assert request.get("stream", False) is streaming
    assert payload["thinking_mode"] is True and payload["max_tokens"] == 131072
    assert result["content"] == content and result["_finish_reason"] == "stop"
    assert result["_usage"] == usage
    assert any(kind == "model.started" for kind, _ in events)
    completed = next(data for kind, data in events if kind == "model.completed")
    assert completed["content_length"] == len(content) and completed["usage"] == usage
    assert any(kind == "answer.delta" for kind, _ in events) is streaming
    if streaming:
        http.json.assert_not_called()
    else:
        http.json.assert_called_once()
        http.iter_lines.assert_not_called()
        assert not any(kind.startswith("answer.") for kind, _ in events)


@pytest.mark.parametrize("supports_stream,public_sections", [(False, ("Final Answer",)), (True, None)])
def test_streaming_switch_respects_client_capability_and_non_answer_calls(monkeypatch, supports_stream, public_sections):
    monkeypatch.setenv("MATHS_MODEL_STREAMING", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    client = Mock()
    client.resolve = None
    client.supports_content_stream = supports_stream
    client.chat.return_value = {"content": "complete result"}
    context = RuntimeContext("task", "session", "problem", {}, (), None, lambda *args: None)
    context.function_calling = "off"
    proxy = TracedClient(client, context, "verify", threading.BoundedSemaphore(1))
    proxy.public_sections = public_sections

    assert proxy.chat(messages=[]) == {"content": "complete result"}
    assert "on_content" not in client.chat.call_args.kwargs

"""Reasoning-only replies remain candidates, never automatic verification passes."""
import threading
import time
from unittest.mock import patch

import pytest

from agent_platform.agent.execution import TracedClient
from agent_platform.presentation.streaming import ModelReasoningStream
from agent_platform.runtime import RuntimeContext
from reasoning_agent.custom.config import AgentConfig
from reasoning_agent.custom2.models import AgentState
from reasoning_agent.custom2.staged_runtime import StagedReasoningRuntime
from reasoning_agent.custom2.staged_models import StagedStrategy
from reasoning_agent.custom2.text_models import ProblemProfile
from tests.test_staged_runtime_config import CaptureClient
from tests.unit.test_live_model_stream import frame, response
from llm_client import ChatCompletionError, InternChatClient


SOLUTION = (
    "## 问题分析\n直接计算。\n## 详细解题步骤\n1+1=2。\n"
    "## 最终答案\n\\boxed{2}\n## 关键验证点\n代回成立。"
)


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


def runtime_for(replies, **config):
    runtime = StagedReasoningRuntime(CaptureClient(replies), AgentConfig(**config))
    runtime.state = AgentState(problem="求 1+1。", efficient_runtime=True,
                               deadline_at=time.monotonic() + 1200, finalize_reserve_seconds=120)
    return runtime


@pytest.mark.parametrize("call_type", ["solver", "solver_compressed", "solver_repair",
                                      "emergency_integrator", "emergency_direct_solver", "final_arbitrator"])
def test_solution_calls_select_reasoning_only_after_completion(call_type):
    runtime = runtime_for([{"content": " \n", "reasoning_content": SOLUTION, "_finish_reason": "stop"}])
    assert runtime._call(call_type, "system", {}, max_tokens=1024) == SOLUTION
    event = runtime.trace[-1]
    assert event["type"] == "solution_candidate_selected"
    assert event["data"]["source"] == "reasoning_content"
    assert runtime._last_model_response.content == " \n"


def test_content_wins_and_structured_calls_do_not_promote_reasoning():
    runtime = runtime_for([
        {"content": SOLUTION, "reasoning_content": "discarded approach"},
        {"content": "", "reasoning_content": '{"verdict":"pass"}'},
    ])
    assert runtime._call("solver", "system", {}, max_tokens=1024) == SOLUTION
    assert runtime._structured("targeted_audit", "system", {}) is None
    assert not any(item["type"] == "solution_candidate_selected" for item in runtime.trace)


@pytest.mark.parametrize("compact", [False, True])
def test_reasoning_solution_uses_normal_candidate_checks_without_extra_recovery(compact):
    runtime = runtime_for([{"content": None, "reasoning_content": SOLUTION}],
                          staged_compact_reasoning_only=compact)
    assert runtime._solve("求 1+1。", ProblemProfile(), StagedStrategy(), "", attempt=1) == SOLUTION
    assert len(runtime.client.calls) == 1
    assert runtime._best_candidate_draft == SOLUTION


def test_unfinished_reasoning_still_requires_recovery():
    runtime = runtime_for([
        {"content": "", "reasoning_content": "Still exploring", "_finish_reason": "length"},
        {"content": SOLUTION},
    ], staged_compact_reasoning_only=False)
    assert runtime._solve("求 1+1。", ProblemProfile(), StagedStrategy(), "", attempt=1) == SOLUTION
    assert len(runtime.client.calls) == 2
    assert runtime._best_candidate_draft == SOLUTION


@pytest.mark.parametrize("reasoning_only", [False, True])
def test_transport_streams_channels_independently_and_waits_for_terminal_frame(monkeypatch, reasoning_only):
    monkeypatch.setenv("INTERN_API_KEY", "test-model-key")
    thinking, content = [], []

    def upstream():
        yield from frame({"content": "", "reasoning_content": "first\n"}, "")
        assert thinking == ["first\n"] and not content
        yield from frame({"reasoning_content": "second\n"}, "")
        yield from frame({"content": SOLUTION}, "")
        yield from frame({}, "stop")

    with patch("llm_client.requests.post", return_value=response(upstream())) as post:
        result = InternChatClient().chat([], on_reasoning=thinking.append,
                                        on_content=None if reasoning_only else content.append,
                                        return_message=True)
    assert result["reasoning_content"] == "first\nsecond\n" and result["content"] == SOLUTION
    assert content == ([] if reasoning_only else [SOLUTION])
    import json
    payload = json.loads(post.call_args.kwargs["data"])
    assert payload["stream"] is True and "on_reasoning" not in payload and "on_content" not in payload


def test_incomplete_reasoning_stream_is_not_promoted_or_retried(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-model-key")
    thinking = []
    with patch("llm_client.requests.post", return_value=response(frame({"reasoning_content": SOLUTION}))) as post:
        with pytest.raises(ChatCompletionError):
            InternChatClient().chat([], on_reasoning=thinking.append, return_message=True)
    assert thinking == [SOLUTION] and post.call_count == 1


def stream_context():
    events = []
    context = RuntimeContext("task", "session", "problem", {}, (), None, lambda *args: None,
                             record=lambda stage, kind, payload: events.append((kind, payload)))
    context.function_calling = "off"
    return context, events


def test_reasoning_stream_redacts_secrets_paths_and_prompt_echo_across_chunks(monkeypatch):
    monkeypatch.setenv("REASONING_TEST_SECRET", "split-credential-value")
    context, events = stream_context()
    prompt = "System instruction that must stay private."
    stream = ModelReasoningStream(context, "solve", lambda: None, "solver", [
        {"role": "system", "content": prompt},
    ])
    text = f"Visible math $x=2$.\nsplit-credential-value\nC:\\private\\key.txt\n{prompt}\nLast line"
    for char in text:
        stream.feed(char)
    assert any(kind == "reasoning.delta" for kind, _ in events)
    stream.complete()
    public = "".join(data["text"] for kind, data in events if kind == "reasoning.delta")
    assert "Visible math" in public and "Last line" in public
    assert "split-credential-value" not in public and "private" not in public and prompt not in public
    assert events[-1][0] == "reasoning.completed"


def test_reasoning_limit_and_interruption_do_not_change_candidate():
    context, events = stream_context()
    stream = ModelReasoningStream(context, "solve", lambda: None, "solver", [])
    stream.limit = 12
    stream.feed("visible\n")
    stream.feed("too much data")
    stream.complete()
    assert events[-1][1]["truncated"] is True
    stream = ModelReasoningStream(context, "solve", lambda: None, "solver", [])
    stream.feed("kept\nunfinished")
    stream.interrupt()
    assert events[-1][0] == "reasoning.interrupted"
    assert any(data.get("text") == "kept\n" for _, data in events)


@pytest.mark.parametrize("show,streaming,enabled", [(None, "true", False), ("true", "false", False),
                                                  ("true", "true", True)])
def test_reasoning_display_flag_and_live_events_leave_raw_response_unchanged(monkeypatch, show, streaming, enabled):
    monkeypatch.setenv("MATHS_MODEL_STREAMING", streaming)
    if show is None:
        monkeypatch.delenv("MATHS_SHOW_MODEL_REASONING", raising=False)
    else:
        monkeypatch.setenv("MATHS_SHOW_MODEL_REASONING", show)
    context, events = stream_context()

    class Client:
        supports_reasoning_stream = True

        def chat(self, on_reasoning=None, **kwargs):
            assert not any(kind == "model.completed" for kind, _ in events)
            if on_reasoning:
                on_reasoning(SOLUTION + "\n")
                assert any(kind == "reasoning.delta" for kind, _ in events)
            return {"content": "", "reasoning_content": SOLUTION}

    proxy = TracedClient(Client(), context, "verify", threading.BoundedSemaphore(1))
    proxy.call_type = "targeted_audit"
    assert proxy.chat(messages=[]) == {"content": "", "reasoning_content": SOLUTION}
    assert any(kind == "reasoning.completed" for kind, _ in events) is enabled

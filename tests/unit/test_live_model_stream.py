import asyncio
import json
import threading
from unittest.mock import Mock, patch

import pytest

from agent_platform.agent.execution import ExecutionStopped, TracedClient
from agent_platform.models import TaskStatus
from agent_platform.presentation.streaming import PublicAnswerStream
from agent_platform.runtime import RuntimeContext, RuntimeResult
from llm_client import ChatCompletionError, InternChatClient, chat_failure_diagnostics
from tests.unit.test_answer_stream import setup


def frame(delta=None, finish=None, **extra):
    return [b"data: " + json.dumps({"choices": [{"index": 0, "delta": delta or {},
                                                "finish_reason": finish}], **extra}).encode(), b""]


def response(lines):
    result = Mock()
    result.iter_lines.side_effect = lambda **kwargs: iter(lines)
    return result


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "stream-test-credential")
    return InternChatClient()


def test_client_emits_content_before_upstream_finishes_and_aggregates_tools_and_usage(client):
    observed = []

    def upstream():
        yield from frame({"reasoning_content": "private analysis"})
        yield from frame({"content": "first"})
        assert observed == ["first"]
        yield from frame({"content": " second", "tool_calls": [
            {"index": 0, "id": "call-1", "function": {"name": "calculate", "arguments": '{"x":'}}]})
        yield from frame({"tool_calls": [{"index": 0, "function": {"arguments": "2}"}}]}, "tool_calls")
        yield b'data: {"choices": [], "usage": {"total_tokens": 12}}'
        yield b""
        yield b"data: [DONE]"
        yield b""

    http = response(upstream())
    with patch("llm_client.requests.post", return_value=http) as post:
        result = client.chat([], on_content=observed.append, return_message=True)
    assert observed == ["first", " second"]
    assert result["content"] == "first second"
    assert result["reasoning_content"] == "private analysis"
    assert result["tool_calls"][0]["function"]["arguments"] == '{"x":2}'
    assert result["_usage"]["total_tokens"] == 12
    assert result["_finish_reason"] == "tool_calls"
    assert post.call_args.kwargs["stream"] is True
    assert json.loads(post.call_args.kwargs["data"])["stream"] is True
    http.close.assert_called_once()


@pytest.mark.parametrize("ending", [[], [b"data: invalid", b""], frame({}, None, error={"message": "bad"})])
def test_incomplete_or_invalid_stream_fails_without_retrying_a_published_prefix(client, ending):
    http = response(frame({"content": "prefix"}) + ending)
    with patch("llm_client.requests.post", return_value=http) as post:
        with pytest.raises(ChatCompletionError):
            client.chat([], on_content=lambda text: None)
    assert post.call_count == 1
    http.close.assert_called_once()


@pytest.mark.parametrize("ending", [frame({}, "stop")[:-1], frame({}, "stop") + [b"data: [DONE]"]])
def test_stream_consumes_complete_final_frame_without_blank_line(client, ending):
    http = response(frame({"content": "complete answer"}) + ending)
    with patch("llm_client.requests.post", return_value=http) as post:
        assert client.chat([], on_content=lambda text: None) == "complete answer"
    assert post.call_count == 1


def test_nullable_metadata_and_terminal_delta_are_supported(client):
    http = response(frame({"content": "answer", "tool_calls": None}) + [
        b'data: {"choices":[{"index":0,"delta":null,"finish_reason":"stop"}]}', b"",
        b'data: {"choices":null,"usage":{"total_tokens":10}}', b"",
        b"data: [DONE]",
    ])
    with patch("llm_client.requests.post", return_value=http):
        result = client.chat([], on_content=lambda text: None, return_message=True)
    assert result["content"] == "answer" and result["_usage"] == {"total_tokens": 10}


def test_empty_finish_reason_means_generation_is_still_in_progress(client):
    observed = []
    http = response(frame({"role": "assistant", "content": ""}, "")
                    + frame({"content": "answer"}, "")
                    + frame({}, "stop") + [b"data: [DONE]", b""])
    with patch("llm_client.requests.post", return_value=http) as post:
        result = client.chat([], on_content=observed.append, return_message=True)
    assert result["content"] == "answer" and result["_finish_reason"] == "stop"
    assert observed == ["answer"] and post.call_count == 1
    http.close.assert_called_once()


@pytest.mark.parametrize("ending", [[], [b"data: [DONE]", b""]])
def test_empty_finish_reason_without_terminal_reason_is_incomplete(client, ending):
    http = response(frame({"content": "unfinished answer"}, "") + ending)
    with patch("llm_client.requests.post", return_value=http) as post:
        with pytest.raises(ChatCompletionError) as caught:
            client.chat([], on_content=lambda text: None)
    assert chat_failure_diagnostics(caught.value)["error_code"] == "incomplete_model_stream"
    assert post.call_count == 1
    http.close.assert_called_once()


def test_json_reply_to_stream_request_is_read_without_another_request(client):
    data = {"choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}]}
    http = response([json.dumps(data).encode()])
    http.headers = {"Content-Type": "application/json; charset=utf-8"}
    observed = []
    with patch("llm_client.requests.post", return_value=http) as post:
        assert client.chat([], on_content=observed.append) == "answer"
    assert observed == ["answer"] and post.call_count == 1
    http.close.assert_called_once()


@pytest.mark.parametrize("data", ['{"choices":false}', '{"choices":[{"delta":[]}]}', 'invalid-private'])
def test_malformed_trailer_is_not_ignored_after_finish(client, data):
    http = response(frame({"content": "answer"}, "stop") + [f"data: {data}".encode()])
    with patch("llm_client.requests.post", return_value=http), pytest.raises(ChatCompletionError) as caught:
        client.chat([], on_content=lambda text: None)
    assert chat_failure_diagnostics(caught.value)["error_code"] == "invalid_model_stream"


@pytest.mark.parametrize("data,code", [
    ('{"choices":[{"delta":null}]}', "incomplete_model_stream"),
    ('[DONE]', "incomplete_model_stream"),
    ('{"choices":[{"delta":"private"}]}', "invalid_model_stream"),
    ('{"choices":[{"delta":{"tool_calls":[{"index":9}]}}]}', "invalid_model_stream"),
    ('not-json-private', "invalid_model_stream"),
    ('{"error":{"message":"private provider response"}}', "model_stream_error"),
])
def test_stream_diagnostics_reject_incomplete_or_invalid_final_frame(client, data, code):
    http = response([f"data: {data}".encode()])
    http.status_code = 200
    with patch("llm_client.requests.post", return_value=http) as post:
        with pytest.raises(ChatCompletionError) as caught:
            client.chat([], on_content=lambda text: None)
    assert chat_failure_diagnostics(caught.value) == {"error_code": code, "http_status": 200, "attempts": 1}
    assert caught.value.__cause__ is not None
    assert caught.value.response_body == ""
    assert post.call_count == 1


@pytest.mark.parametrize("status,code", [(401, "model_auth_error"), (429, "model_rate_limited"),
                                        (503, "model_service_error"), (400, "model_request_rejected")])
def test_http_failure_retains_falsey_response_and_safe_diagnostics(client, status, code):
    import requests

    http = requests.Response()
    http.status_code = status
    http._content = b'private provider response'
    http.raw = Mock()
    with patch("llm_client.requests.post", return_value=http), pytest.raises(ChatCompletionError) as caught:
        client.chat([], on_content=lambda text: None)
    assert chat_failure_diagnostics(caught.value) == {"error_code": code, "http_status": status, "attempts": 1}


def test_failed_call_diagnostics_never_publish_exception_text():
    events = []
    context = RuntimeContext("task", "session", "problem", {}, (), None, lambda *args: None,
                             record=lambda stage, kind, payload: events.append((kind, payload)))
    context.function_calling = "off"

    class FailingClient:
        def chat(self, **kwargs):
            raise ChatCompletionError(1, TimeoutError("private prompt credential C:\\private\\file"))

    proxy = TracedClient(FailingClient(), context, "solve", threading.BoundedSemaphore(1))
    with pytest.raises(ChatCompletionError):
        proxy.chat(messages=[])
    payload = next(payload for kind, payload in events if kind == "model.failed")
    assert payload["error_code"] == "model_timeout" and payload["attempts"] == 1
    assert payload["duration_ms"] >= 0
    assert "private" not in json.dumps(events) and "credential" not in json.dumps(events)


def test_cancel_closes_upstream_even_for_execution_stopped_base_exception(client):
    http = response(frame({"content": "prefix"}))

    def stopped():
        raise ExecutionStopped()

    with patch("llm_client.requests.post", return_value=http):
        with pytest.raises(ExecutionStopped):
            client.chat([], on_content=lambda text: None, check_running=stopped)
    http.close.assert_called_once()


def collect_preview(text, monkeypatch, selected=("详细解题步骤", "最终答案")):
    monkeypatch.setenv("STREAM_TEST_SECRET", "credential-for-stream-test")
    events = []
    context = RuntimeContext("task", "session", "problem", {}, (), None,
                             lambda *args: None, record=lambda stage, kind, payload: events.append((kind, payload)))
    stream = PublicAnswerStream(context, "solve", lambda: None, selected)
    for character in text:
        stream.feed(character)
    stream.complete()
    return events


def test_projection_handles_all_token_boundaries_and_keeps_private_blocks_and_checks_off_wire(monkeypatch):
    events = collect_preview(
        "private preamble\n<think>## 最终答案\nhidden</think>\n"
        "## 详细解题步骤\n第一步，$x<2$。\n<analysis>secret\nmore</analysis>"
        "第二步。\n```check\nassert private\n```\n"
        "Bearer abcdefghijklmnopqrstuvwxyz\ncredential-for-stream-test\n"
        "C:\\private\\file.txt\n/home/person/key.txt\n"
        "## debug\nprivate debug\n## 最终答案\n$x=1$", monkeypatch)
    public = "".join(payload["text"] for kind, payload in events if kind == "answer.delta")
    assert "第一步" in public and "第二步" in public and "$x=1$" in public
    for secret in ("hidden", "secret", "private", "assert", "abcdefghijklmnopqrstuvwxyz", "credential-for-stream-test", "person"):
        assert secret not in public
    assert events[-1][0] == "answer.completed"
    assert events[-1][1]["preview"] is True


def test_unfinished_private_tag_or_block_never_flushes(monkeypatch):
    for suffix in ("<think>hidden", "<analysis\nhidden", "<thi"):
        events = collect_preview("## 最终答案\n公开内容\n" + suffix, monkeypatch)
        public = "".join(payload["text"] for kind, payload in events if kind == "answer.delta")
        assert "公开内容" in public and "hidden" not in public and "<" not in public


def test_answer_only_projection_uses_selected_public_sections(monkeypatch):
    events = collect_preview("## 详细解题步骤\n省略步骤\n## 最终答案\n结论\n", monkeypatch, ("最终答案",))
    public = "".join(payload["text"] for kind, payload in events if kind == "answer.delta")
    assert "省略步骤" not in public and "结论" in public


def test_failed_call_retracts_its_preview_and_repair_gets_a_new_stream():
    events = []
    context = RuntimeContext("task", "session", "problem", {}, (), None,
                             lambda *args: None, record=lambda stage, kind, payload: events.append((kind, payload)))
    context.function_calling = "off"

    class StreamingClient:
        supports_content_stream = True
        fail = True

        def chat(self, on_content, **kwargs):
            on_content("## 最终答案\n本轮公开结果。\n")
            if self.fail:
                raise ValueError("upstream failed")
            return {"content": "## 最终答案\n本轮公开结果。\n"}

    client = StreamingClient()
    proxy = TracedClient(client, context, "solve", threading.BoundedSemaphore(1))
    proxy.call_type = "solver"
    proxy.public_sections = ("最终答案",)
    with pytest.raises(ValueError):
        proxy.chat(messages=[])
    assert any(kind == "answer.delta" for kind, _ in events)
    discarded = next(payload["stream_id"] for kind, payload in events if kind == "answer.discarded")
    client.fail = False
    proxy.chat(messages=[])
    starts = [payload["stream_id"] for kind, payload in events if kind == "answer.started"]
    assert len(starts) == 2 and starts[0] == discarded and starts[1] != discarded
    assert events[-2][0] == "answer.completed"


def test_real_client_to_task_events_is_live_before_verification_and_history_commit(client):
    generated = threading.Event()
    allow_finish = threading.Event()
    verification = asyncio.Event()

    def upstream():
        yield from frame({"reasoning_content": "private reasoning"})
        yield from frame({"content": "## 最终答案\n待校验结果 $x=2$。\n"})
        generated.set()
        assert allow_finish.wait(5)
        yield from frame({}, "stop")

    class Runtime:
        name = "live_stream_test"

        async def run(self, context):
            context.progress("solve")
            proxy = TracedClient(client, context, "solve", threading.BoundedSemaphore(1))
            proxy.call_type = "solver"
            proxy.public_sections = ("最终答案",)
            context.function_calling = "off"
            await asyncio.to_thread(proxy.chat, messages=[])
            context.progress("verify")
            await verification.wait()
            return RuntimeResult("校验后的最终结果。")

    async def scenario():
        store, task, service = setup(Runtime())
        execution = asyncio.create_task(service._execute(task))
        try:
            assert await asyncio.to_thread(generated.wait, 5)
            running = store.get_task(task.session_id, task.id)
            assert running.status == TaskStatus.RUNNING and running.final_response is None
            events = store.events_after(task.session_id, task.id, 0)
            assert any(event.event_type == "answer.delta" and "待校验结果" in event.payload["text"] for event in events)
            assert not any(event.event_type == "model.completed" for event in events)
            assert not any(message.role == "assistant" for message in store.get_session(task.session_id).messages)
            allow_finish.set()
            async with asyncio.timeout(5):
                while store.get_task(task.session_id, task.id).current_stage != "verify":
                    await asyncio.sleep(.001)
            assert store.get_task(task.session_id, task.id).final_response is None
            assert store.get_task(task.session_id, task.id).answer_delivery_ms is None
            verification.set()
            await execution
            assert store.get_task(task.session_id, task.id).final_response == "校验后的最终结果。"
        finally:
            allow_finish.set()
            verification.set()
            await execution

    with patch("llm_client.requests.post", return_value=response(upstream())):
        asyncio.run(scenario())

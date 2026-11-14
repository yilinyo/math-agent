import json
import os
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Union

import requests


DEFAULT_API_BASE = "https://chat.intern-ai.org.cn/api/v1/chat/completions"
DEFAULT_MODEL = "intern-s2-preview"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 8192
DEFAULT_THINKING_MODE = True
DEBUG_CHAT_REQUESTS = os.environ.get("INTERN_CHAT_DEBUG", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}
DUMP_CHAT_REQUESTS = os.environ.get("INTERN_CHAT_DUMP_REQUEST", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}
DUMP_CHAT_REQUEST_DIR = os.environ.get("INTERN_CHAT_REQUEST_DUMP_DIR", "").strip()

ChatMessage = Dict[str, Any]
ChatResponse = Union[str, ChatMessage]


class ModelStreamError(ValueError):
    """A protocol failure with a public, fixed diagnostic code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def chat_failure_diagnostics(error: Exception) -> dict[str, Any]:
    """Project known failures without copying exception or provider text."""
    cause = error.__cause__ if isinstance(error, ChatCompletionError) else error
    status = getattr(error, "status_code", None)
    code = "model_call_failed"
    if isinstance(cause, ModelStreamError):
        code = cause.code if cause.code in {
            "incomplete_model_stream", "invalid_model_stream", "model_stream_error",
            "model_stream_too_large",
        } else code
    elif isinstance(cause, (TimeoutError, requests.Timeout)):
        code = "model_timeout"
    elif isinstance(cause, requests.ConnectionError):
        code = "model_connection_error"
    elif isinstance(cause, requests.exceptions.ChunkedEncodingError):
        code = "incomplete_model_stream"
    elif isinstance(cause, (json.JSONDecodeError, UnicodeDecodeError)):
        code = "invalid_model_stream"
    details: dict[str, Any] = {"error_code": code}
    if type(status) is int and 100 <= status <= 599:
        details["http_status"] = status
        if status >= 400:
            details["error_code"] = (
                "model_auth_error" if status in {401, 403} else
                "model_rate_limited" if status == 429 else
                "model_service_error" if status >= 500 else "model_request_rejected"
            )
    attempts = getattr(error, "attempts", None)
    if type(attempts) is int and attempts > 0:
        details["attempts"] = attempts
    return details


class ChatCompletionError(RuntimeError):
    """Retain bounded server diagnostics without including request contents."""

    def __init__(
        self,
        attempts: int,
        error: Exception | None,
        *,
        status_code: int | None = None,
        response_body: str = "",
    ) -> None:
        self.attempts = attempts
        self.status_code = status_code
        self.response_body = " ".join(str(response_body or "").split())[:1000]
        super().__init__(f"Chat completion failed after {attempts} attempts: {error}")
        self.__cause__ = error


class InternChatClient:
    """Small OpenAI-compatible chat client for the competition sample."""

    supports_content_stream = True

    def __init__(
        self,
        timeout: int = 240,
        retry: int = 3,
        default_args: Optional[Mapping[str, Any]] = None,
        *,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        protocol: str = "intern",
        **request_args: Any,
    ) -> None:
        raw_api_key = api_key if api_key is not None else os.environ.get("INTERN_API_KEY")
        if not raw_api_key and protocol == "intern":
            raise RuntimeError("Missing API key. Set INTERN_API_KEY.")
        self.authorization = (
            raw_api_key if raw_api_key and raw_api_key.startswith("Bearer ") else f"Bearer {raw_api_key or ''}"
        )
        self.api_base = api_url if api_url is not None else os.environ.get("INTERN_API_BASE", DEFAULT_API_BASE)
        self.model = model if model is not None else os.environ.get("INTERN_MODEL", DEFAULT_MODEL)
        self.protocol = protocol
        self.timeout = timeout
        self.retry = retry
        self.default_args = dict(default_args or {})
        self.default_args.update(request_args)

    def chat(
        self,
        messages: List[ChatMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        *,
        thinking_mode: Optional[bool] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        return_message: bool = False,
        request_timeout: Optional[float] = None,
        on_content: Callable[[str], None] | None = None,
        check_running: Callable[[], None] | None = None,
        **request_args: Any,
    ) -> ChatResponse:
        """Create a chat completion.

        Extra request arguments are passed through to the HTTP API. Arguments
        supplied to ``chat`` override client-wide ``default_args``.

        Text completions are returned as strings for backwards compatibility.
        When the model requests a tool call, the complete assistant message is
        returned so that callers can read ``tool_calls`` and append the message
        to the next request.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "thinking_mode": DEFAULT_THINKING_MODE,
        }
        payload.update(self.default_args)
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if thinking_mode is not None:
            payload["thinking_mode"] = thinking_mode
        if tools is not None:
            payload["tools"] = tools
        payload.update(request_args)
        if self.protocol != "intern":
            payload.pop("thinking_mode", None)
        # ``messages`` is the only required per-call argument and must not be
        # replaced accidentally by client-wide defaults.
        payload["messages"] = messages
        if on_content is not None:
            payload["stream"] = True

        headers = {
            "Content-Type": "application/json",
            "Authorization": self.authorization,
        }
        if self.authorization == "Bearer ":
            headers.pop("Authorization", None)

        # A staged long-form solver deliberately gets one uninterrupted HTTP
        # attempt.  Retrying a request that has already consumed the entire
        # 10-minute reasoning window only recreates the same expensive prompt
        # and leaves no time for the compact recovery.  Short control calls
        # keep the normal client retry policy.  ``request_timeout`` is set by
        # the agent's phase budget, so this remains a local-client behavior
        # and does not alter the platform-injected client contract.
        single_long_attempt = bool(
            request_timeout is not None
            and float(request_timeout) > float(self.timeout)
        )
        # A partially published stream must never be silently replayed on retry.
        retry_count = 1 if single_long_attempt or on_content is not None else self.retry
        last_error = None
        last_status_code: int | None = None
        last_response_body = ""
        call_started_monotonic = time.perf_counter()
        attempts = 0
        for attempt in range(retry_count):
            response = None
            stream_response = None
            started_at = datetime.now(timezone.utc)
            started_monotonic = time.perf_counter()
            try:
                transport_timeout = (
                    float(request_timeout)
                    if single_long_attempt and request_timeout is not None
                    else float(self.timeout)
                )
                if request_timeout is not None:
                    request_remaining = float(request_timeout) - (
                        time.perf_counter() - call_started_monotonic
                    )
                    if request_remaining <= 0:
                        last_error = TimeoutError("model_request_deadline")
                        break
                    transport_timeout = min(transport_timeout, request_remaining)
                attempts += 1
                response = requests.post(
                    self.api_base,
                    headers=headers,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    timeout=transport_timeout,
                    **({"stream": True} if on_content is not None else {}),
                )
                if on_content is not None:
                    stream_response = response
                response.raise_for_status()
                if on_content is not None:
                    data = self._read_stream(
                        response, on_content, check_running,
                        call_started_monotonic + float(request_timeout or transport_timeout),
                    )
                else:
                    data = response.json()
                message = data["choices"][0]["message"]
                ended_at = datetime.now(timezone.utc)
                duration_seconds = max(0.0, time.perf_counter() - started_monotonic)
                if DUMP_CHAT_REQUESTS and on_content is None:
                    self._dump_request_payload_safely(
                        payload,
                        attempt=attempt + 1,
                        status_code=getattr(response, "status_code", None),
                        response_body=getattr(response, "text", "") or "",
                        started_at=started_at.isoformat(),
                        ended_at=ended_at.isoformat(),
                        duration_seconds=duration_seconds,
                    )
                if return_message:
                    enriched_message = dict(message)
                    finish_reason = data["choices"][0].get("finish_reason")
                    usage = data.get("usage")
                    if finish_reason is not None:
                        enriched_message["_finish_reason"] = finish_reason
                    if usage is not None:
                        enriched_message["_usage"] = usage
                    return enriched_message
                if "tool_calls" in message:
                    return message
                return message["content"]
            except Exception as exc:  # noqa: BLE001 - keep sample robust and simple.
                last_error = exc
                ended_at = datetime.now(timezone.utc)
                duration_seconds = max(0.0, time.perf_counter() - started_monotonic)
                error_response = getattr(exc, "response", None)
                if error_response is not None:
                    response = error_response
                status_code = getattr(response, "status_code", None)
                last_status_code = status_code if isinstance(status_code, int) else None
                # Never drain an interrupted streaming body for diagnostics.
                last_response_body = (
                    getattr(response, "text", "") if response is not None and on_content is None else ""
                )
                if DEBUG_CHAT_REQUESTS:
                    self._log_request_summary(
                        payload,
                        attempt=attempt + 1,
                        retry=retry_count,
                        status_code=status_code,
                        error=exc,
                        response_body=last_response_body,
                        started_at=started_at.isoformat(),
                        ended_at=ended_at.isoformat(),
                        duration_seconds=duration_seconds,
                    )
                if DUMP_CHAT_REQUESTS:
                    self._dump_request_payload_safely(
                        payload,
                        attempt=attempt + 1,
                        error=exc,
                        status_code=status_code,
                        response_body=last_response_body,
                        started_at=started_at.isoformat(),
                        ended_at=ended_at.isoformat(),
                        duration_seconds=duration_seconds,
                    )
                if attempt + 1 < retry_count:
                    retry_delay = float(2**attempt)
                    if request_timeout is not None:
                        request_remaining = float(request_timeout) - (
                            time.perf_counter() - call_started_monotonic
                        )
                        if request_remaining <= retry_delay:
                            break
                    time.sleep(retry_delay)
            finally:
                if stream_response is not None:
                    stream_response.close()

        raise ChatCompletionError(
            attempts,
            last_error,
            status_code=last_status_code,
            response_body=last_response_body,
        ) from last_error

    @staticmethod
    def _read_stream(response, on_content, check_running, deadline):
        message = {"role": "assistant", "content": ""}
        calls = {}
        usage = None
        finish = None
        frame = []
        size = 0
        content_type = response.headers.get("Content-Type", "")
        is_json = isinstance(content_type, str) and content_type.split(";", 1)[0].strip().lower() == "application/json"

        def consume(data):
            nonlocal usage, finish
            if data == "[DONE]":
                return True
            event = json.loads(data)
            if not isinstance(event, dict):
                raise ModelStreamError("invalid_model_stream")
            if event.get("error"):
                raise ModelStreamError("model_stream_error")
            if event.get("usage") is not None:
                usage = event["usage"]
            choices = event.get("choices")
            if choices is None:
                choices = []
            if not isinstance(choices, list):
                raise ModelStreamError("invalid_model_stream")
            for choice in choices:
                if not isinstance(choice, dict):
                    raise ModelStreamError("invalid_model_stream")
                if choice.get("index", 0) != 0:
                    continue
                delta = choice.get("message" if is_json else "delta")
                if delta is None:
                    delta = {}
                if not isinstance(delta, dict):
                    raise ModelStreamError("invalid_model_stream")
                for key in ("content", "reasoning_content"):
                    text = delta.get(key)
                    if text is not None:
                        if not isinstance(text, str):
                            raise ModelStreamError("invalid_model_stream")
                        message[key] = message.get(key, "") + text
                        if key == "content" and text:
                            on_content(text)
                parts = delta.get("tool_calls")
                if parts is None:
                    parts = []
                if not isinstance(parts, list):
                    raise ModelStreamError("invalid_model_stream")
                for position, part in enumerate(parts):
                    if not isinstance(part, dict):
                        raise ModelStreamError("invalid_model_stream")
                    index = part.get("index", position if is_json else None)
                    if type(index) is not int or not 0 <= index < 4:
                        raise ModelStreamError("invalid_model_stream")
                    call = calls.setdefault(index, {"id": "", "type": "function",
                                                    "function": {"name": "", "arguments": ""}})
                    function = part.get("function")
                    if function is None:
                        function = {}
                    if not isinstance(function, dict):
                        raise ModelStreamError("invalid_model_stream")
                    identifier = part.get("id", "")
                    if not isinstance(identifier, str):
                        raise ModelStreamError("invalid_model_stream")
                    call["id"] += identifier
                    for key in ("name", "arguments"):
                        fragment = function.get(key, "")
                        if not isinstance(fragment, str):
                            raise ModelStreamError("invalid_model_stream")
                        call["function"][key] += fragment
                if choice.get("finish_reason") is not None:
                    if not isinstance(choice["finish_reason"], str):
                        raise ModelStreamError("invalid_model_stream")
                    # Intern uses an empty string while generation is still in progress.
                    if choice["finish_reason"]:
                        finish = choice["finish_reason"]
            return False

        # Consume the final frame at EOF too: some providers omit the last blank line.
        for raw_line in response.iter_lines(chunk_size=1):
            if check_running is not None:
                check_running()
            if time.perf_counter() >= deadline:
                raise TimeoutError("model_stream_deadline")
            size += len(raw_line) + 1
            if size > 4 * 1024 * 1024:
                raise ModelStreamError("model_stream_too_large")
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if is_json:
                frame.append(line)
            elif line:
                if line.startswith("data:"):
                    frame.append(line[5:].lstrip(" "))
            elif frame:
                data = "\n".join(frame)
                frame.clear()
                if consume(data):
                    break
        if frame:
            consume("\n".join(frame))
        if finish is None:
            raise ModelStreamError("incomplete_model_stream")
        if calls:
            message["tool_calls"] = [calls[index] for index in sorted(calls)]
        return {"choices": [{"message": message, "finish_reason": finish}], "usage": usage}

    @staticmethod
    def _log_request_summary(
        payload: dict[str, Any],
        *,
        attempt: int,
        retry: int,
        status_code: int | None = None,
        error: Exception | None = None,
        response_body: str = "",
        started_at: str | None = None,
        ended_at: str | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        messages = payload.get("messages", [])
        message_summaries: list[dict[str, Any]] = []
        total_chars = 0
        if isinstance(messages, list):
            for index, message in enumerate(messages):
                if not isinstance(message, dict):
                    message_summaries.append({"index": index, "type": type(message).__name__})
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    content_text = content
                    content_type = "str"
                else:
                    try:
                        content_text = json.dumps(content, ensure_ascii=False)
                    except TypeError:
                        content_text = str(content)
                    content_type = type(content).__name__
                total_chars += len(content_text)
                message_summaries.append(
                    {
                        "index": index,
                        "role": message.get("role"),
                        "content_type": content_type,
                        "chars": len(content_text),
                        "preview": content_text[:300],
                    }
                )

        summary = {
            "attempt": attempt,
            "retry": retry,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
            "model": payload.get("model"),
            "temperature": payload.get("temperature"),
            "max_tokens": payload.get("max_tokens"),
            "thinking_mode": payload.get("thinking_mode"),
            "status_code": status_code,
            "error": str(error) if error else "",
            "tool_count": len(payload.get("tools", []) or []),
            "message_count": len(messages) if isinstance(messages, list) else None,
            "message_chars": total_chars,
            "messages": message_summaries,
        }
        if response_body:
            summary["response_body"] = response_body[:1000]
        print(
            "[intern_chat_request] " + json.dumps(summary, ensure_ascii=False),
            file=sys.stderr,
        )

    @staticmethod
    def _dump_request_payload(
        payload: dict[str, Any],
        *,
        attempt: int,
        error: Exception | None = None,
        status_code: int | None = None,
        response_body: str = "",
        started_at: str | None = None,
        ended_at: str | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        if not DUMP_CHAT_REQUEST_DIR:
            return
        dump_dir = Path(DUMP_CHAT_REQUEST_DIR).expanduser()
        dump_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        status_label = str(status_code) if status_code is not None else "error"
        path = dump_dir / f"{timestamp}-{status_label}-attempt-{attempt}.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "status_code": status_code,
                    "success": error is None,
                    "error": str(error) if error else "",
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "duration_seconds": duration_seconds,
                    "response_body": (response_body or "")[:8000],
                    "payload": payload,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")

    @classmethod
    def _dump_request_payload_safely(
        cls,
        payload: dict[str, Any],
        *,
        attempt: int,
        error: Exception | None = None,
        status_code: Any = None,
        response_body: str = "",
        started_at: str | None = None,
        ended_at: str | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        normalized_status = status_code if isinstance(status_code, int) else None
        if normalized_status is None and error is None:
            normalized_status = 200
        normalized_body = response_body if isinstance(response_body, str) else ""
        try:
            cls._dump_request_payload(
                payload,
                attempt=attempt,
                error=error,
                status_code=normalized_status,
                response_body=normalized_body,
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=duration_seconds,
            )
        except Exception as dump_error:  # noqa: BLE001 - diagnostics must not break chat.
            if DEBUG_CHAT_REQUESTS:
                print(
                    "[intern_chat_dump_error] " + json.dumps(
                        {"attempt": attempt, "error": str(dump_error)},
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                )

"""Shared cancellation, tracing and checkpoint boundaries for graph nodes."""
import asyncio
import copy
import contextvars
import json
import threading
import time
from uuid import uuid4
from typing import Any
from agent_platform.runtime import RuntimeContext
from agent_platform.safety import sanitize
from agent_platform.tools.function_calling import call_with_tools
from reasoning_agent.custom2.model_call import ModelCallBudgetExhausted, _normalize_response
from reasoning_agent.custom.config import env_flag
from agent_platform.observability import invoke_model
from agent_platform.agent.routing import route
from agent_platform.presentation.streaming import ModelReasoningStream, PublicAnswerStream
from llm_client import chat_failure_diagnostics
from agent_platform.presentation.trace import stage_context, stage_outcome


class ExecutionStopped(BaseException):
    """Must escape the legacy runtime's broad model-failure handlers."""


class TracedClient:
    def __init__(self, client: Any, context: RuntimeContext, stage: str,
                 permits: threading.BoundedSemaphore) -> None:
        self.client, self.context, self.stage = client, context, stage
        self.router = client if callable(getattr(client, "resolve", None)) else None
        self.agent_info = None
        self.permits = permits
        self.call_type = stage
        self.public_sections = None
        self.library_references = []
        # The legacy timeout worker uses threading.Thread, which loses contextvars.
        self.tracing_context = contextvars.copy_context()

    def chat(self, request_timeout=None, **kwargs):
        if self.router:
            self.client, self.agent_info = self.router.resolve(self.call_type)
        return call_with_tools(self, {**kwargs, "request_timeout": request_timeout})

    def _chat_once(self, request_timeout=None, **kwargs):
        deadline = time.monotonic() + min(720, max(0, float(request_timeout or 720)))
        while not self.permits.acquire(timeout=.05):
            self.check_running()
            if time.monotonic() >= deadline:
                raise TimeoutError("model_capacity_deadline")
        try:
            self.check_running()
            call_type = self.call_type
            if call_type.startswith("solver"):
                limit = self.context.max_solve_calls
                if limit is not None and self.context.solver_calls_used >= limit:
                    self.context.record(self.stage, "model.budget_exhausted", {"call_type": call_type})
                    raise ModelCallBudgetExhausted("solver_call_budget_exhausted")
                self.context.solver_calls_used += 1
            if (call_type in {"emergency_integrator", "emergency_direct_solver", "final_arbitrator"}
                    and self.context.model_calls.get(call_type, 0)):
                raise ModelCallBudgetExhausted("recovery_call_budget_exhausted")
            operation_id = str(uuid4())
            started = time.monotonic()
            agent_details = {"agent": self.agent_info} if self.agent_info else {}
            self.context.record(self.stage, "model.started", {"call_type": call_type, "operation_id": operation_id, **agent_details})
            if self.library_references:
                self.context.record(self.stage, "library.injected", {
                    "call_type": call_type, "operation_id": operation_id,
                    "references": self.library_references,
                })
            self.context.model_calls[call_type] = self.context.model_calls.get(call_type, 0) + 1
            preview = None
            if (self.public_sections is not None
                    and env_flag("MATHS_MODEL_STREAMING", True)
                    and getattr(self.client, "supports_content_stream", False) is True):
                preview = PublicAnswerStream(self.context, self.stage, self.check_running, self.public_sections)
                kwargs.update(on_content=preview.feed, check_running=self.check_running)
            reasoning = None
            if (env_flag("MATHS_MODEL_STREAMING", True)
                    and env_flag("MATHS_SHOW_MODEL_REASONING", False)
                    and getattr(self.client, "supports_reasoning_stream", False) is True):
                reasoning = ModelReasoningStream(self.context, self.stage, self.check_running,
                                                 call_type, kwargs.get("messages", []))
                kwargs.update(on_reasoning=reasoning.feed, check_running=self.check_running)
            try:
                kwargs["request_timeout"] = max(.001, deadline - time.monotonic())
                raw = self.tracing_context.copy().run(invoke_model, self.client, kwargs, call_type)
                if reasoning:
                    reasoning.complete()
                if preview:
                    if isinstance(raw, dict) and raw.get("tool_calls"):
                        preview.discard()
                    else:
                        preview.complete()
            except Exception as exc:
                self.check_running()
                if reasoning:
                    reasoning.interrupt()
                if preview:
                    preview.discard()
                self.context.record(self.stage, "model.failed", {
                    "call_type": call_type, "operation_id": operation_id, "error_type": type(exc).__name__,
                    "duration_ms": int(max(0, time.monotonic() - started) * 1000),
                    **chat_failure_diagnostics(exc),
                    **agent_details,
                })
                raise
            self.check_running()
            response = _normalize_response(raw, time.monotonic() - started)
            usage = response.token_usage if isinstance(response.token_usage, dict) else {}
            self.context.record(self.stage, "model.completed", {
                "call_type": call_type, "operation_id": operation_id, "duration_ms": int(response.duration_seconds * 1000),
                "content_length": len(response.content),
                **agent_details,
                "usage": {key: value for key, value in usage.items()
                          if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                          and isinstance(value, int) and value >= 0},
            })
            return raw
        finally:
            # Cancellation cannot kill an injected synchronous client's thread.
            # Keep its permit until that actual client invocation has returned.
            self.permits.release()

    def check_running(self) -> None:
        if not getattr(self.permits, 'check_current', lambda: True)():
            self.context.cancelled.set()
        if self.context.cancelled.is_set():
            raise ExecutionStopped()


def node(stage, *, runtime, context):
    async def execute(current):
        if context.cancelled.is_set():
            raise asyncio.CancelledError
        public_stage = {"emergency": "solve", "arbitrate": "verify"}.get(stage, stage)
        context.progress(public_stage)
        started = time.monotonic()
        context.record(public_stage, "stage.context", stage_context(stage, current))
        adapter = runtime.adapter_factory(runtime.client, runtime.config, context, stage, runtime.permits, current)
        try:
            updates = await asyncio.to_thread(adapter.execute, copy.deepcopy(current))
        except ExecutionStopped:
            raise asyncio.CancelledError from None
        except Exception:
            # Store/lease errors must escape; recording also fences the owner.
            context.record(public_stage, "stage.recovered_error", {"error_code": "stage_failed"})
            if stage == "finalize":
                raise
            if not current.get("adapter", {}).get("_best_candidate_draft"):
                raise
            updates = {"recoverable_error": "stage_failed", "next_stage": "finalize"}
        updated = {**current, **updates}
        updated["solve_calls_used"] = context.solver_calls_used
        budget_available = runtime._budget_available(context)
        updated["next_stage"] = (
            "finalize" if updates.get("next_stage") == "finalize"
            else route(stage, updated, budget_available=budget_available)
        )
        updated = sanitize(updated)
        json.dumps(updated, allow_nan=False)
        context.record(public_stage, "stage.outcome", stage_outcome(
            stage, current, updates, updated["next_stage"],
            max(0, int((time.monotonic() - started) * 1000)),
            budget_available=budget_available,
        ))
        context.progress(public_stage, completed=True, checkpoint=updated)
        context.checkpoint = updated
        if updated.get("adapter", {}).get("_best_candidate_draft"):
            context.saved_response = adapter.safe_response()
        return updated
    return execute

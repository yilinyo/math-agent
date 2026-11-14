import asyncio
import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from agent_platform.observability import log_runtime_event, log_tool_result
from agent_platform.runtime import RuntimeContext
from agent_platform.tools.registry import ToolRegistry
from agent_platform.tools.schemas import ToolInvocation


def test_model_and_tool_event_fields_are_visible(capsys):
    log_runtime_event("task", "profile", "model.started", {"call_type": "classifier", "operation_id": "model-op"})
    log_runtime_event("task", "tool", "tool.completed", {
        "name": "math_verify", "call_id": "tool-id", "latency_ms": 15,
        "attempt": 0, "status": "succeeded", "verdict": "uncertain"})
    log_runtime_event("task", "tool", "tool_fallback.started", {"name": "math_verify", "call_id": "tool-id"})
    output = capsys.readouterr().out
    assert "调用=classifier" in output and "操作ID=model-op" in output
    assert "工具=math_verify" in output and "调用ID=tool-id" in output
    assert "耗时毫秒=15" in output and "状态=succeeded" in output
    assert "[工具回退开始]" in output


def test_model_failure_logs_structured_diagnostics_only(capsys):
    log_runtime_event("task", "solve", "model.failed", {
        "error_type": "ChatCompletionError", "error_code": "model_rate_limited",
        "http_status": 429, "attempts": 1, "duration_ms": 150,
        "message": "private prompt", "response_body": "private response",
    })
    output = capsys.readouterr().out
    assert "错误码=model_rate_limited" in output and "HTTP状态=429" in output
    assert "尝试次数=1" in output and "耗时毫秒=150" in output
    assert "private" not in output


@pytest.mark.parametrize("persist", [False, True])
def test_committed_and_replayed_result_logged_once_without_new_execution(persist, capsys):
    local = Mock(invoke=AsyncMock(return_value={"status": "succeeded", "value": {
        "verdict": "uncertain", "findings": ["Proof needs review"], "counterexample": None, "checked_claims": []}}))
    commit = Mock() if persist else None
    context = RuntimeContext("task", "session", "problem", {}, (), None, lambda *args: None,
                             deadline_at=datetime.now(timezone.utc) + timedelta(seconds=180), commit_tool=commit)
    registry = ToolRegistry(local=local)
    request = ToolInvocation(call_id="same-call", task_id="task", stage_id="tool", tool_name="math_verify",
                             arguments={"problem": "problem", "candidate": "proof", "checks": ["proof_obligations"]})
    first = asyncio.run(registry.invoke(request, context))
    assert first.status == "succeeded"
    asyncio.run(registry.invoke(request, context))
    assert local.invoke.await_count == 1
    output = capsys.readouterr().out
    assert output.count("[工具调用结果]") == 2
    assert output.count("来源=本次调用") == 1 and output.count("来源=缓存重放") == 1
    assert '"verdict": "uncertain"' in output and "Proof needs review" in output


def test_tool_result_redaction_does_not_mutate_result(monkeypatch, capsys):
    monkeypatch.setenv("INTERN_API_KEY", "real-key-marker")
    result = {"status": "succeeded", "value": {
        "matches": [{"strategy_id": "123", "title": "Method", "score": .8,
                     "summary": "real-key-marker /Users/user/private.txt"}],
        "retrieval_text": "private retrieval query", "rendered_cards": {"executor": "private prompt"}}}
    original = copy.deepcopy(result)
    log_tool_result("task", "retrieve", "strategy_search", "call", result)
    output = capsys.readouterr().out
    assert '"strategy_id": "123"' in output and '"score": 0.8' in output
    assert "real-key-marker" not in output and "/Users/" not in output
    assert "private retrieval query" not in output and "private prompt" not in output
    assert result == original


def test_tool_failure_and_result_truncation_are_explicit(capsys):
    log_tool_result("task", "tool", "math_verify", "call", {"status": "failed", "error_code": "timeout", "value": None})
    log_tool_result("task", "tool", "sympy_calculate", "call2", {
        "status": "succeeded", "value": {"value": "x" * 13000}})
    output = capsys.readouterr().out
    assert '"error_code": "timeout"' in output
    assert '"truncated": true' in output


def test_final_acceptance_logs_reasons_without_private_payloads(capsys):
    log_runtime_event("task", "finalize", "reasoning.event", {
        "operation": "final_candidate_checked", "accepted": False,
        "format_failures": ["multiple_final_candidates"], "hard_failure_count": 0,
        "budget_exhausted": False, "extraction": "ok", "prompt": "PRIVATE_PROMPT",
        "raw_response": "PRIVATE_RESPONSE",
    })
    log_runtime_event("task", "verify", "stage.outcome", {
        "status": "needs_review", "next_stage": "repair", "routing_reason": "audit_requires_repair"})
    output = capsys.readouterr().out
    assert "最终验收通过=否" in output
    assert "多个答案冲突或尚无法验证等价" in output
    assert "计算矛盾数=0" in output
    assert "流转依据=审查发现问题" in output
    assert "下一步=repair（定向修复）" in output
    assert "PRIVATE" not in output

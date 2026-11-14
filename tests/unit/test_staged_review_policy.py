"""Deterministic review deadlines, escalation and solver time allocation."""
import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from reasoning_agent.custom.config import AgentConfig
from reasoning_agent.custom2.models import AgentState
from reasoning_agent.custom2.staged_models import StagedAudit, StagedStrategy
from reasoning_agent.custom2.staged_runtime import StagedReasoningRuntime
from reasoning_agent.custom2.text_models import ProblemProfile


PASS = {"verdict": "pass"}
DOUBT = {"verdict": "uncertain", "unmet_obligations": ["Check the boundary case."]}
FAIL = {"verdict": "fail", "invalid_claim": "unsupported claim", "first_fatal_error": "Wrong inference",
        "evidence": "A boundary counterexample contradicts the quoted claim.",
        "required_changes": ["Recompute the boundary case."]}
DRAFT = ("## 问题分析\nUse the definition.\n## 详细解题步骤\nunsupported claim\n"
         "## 最终答案\n\\boxed{2}\n## 关键验证点\nCheck the boundary.")


class Clock:
    now = 1000.0


class ScriptedClient:
    def __init__(self, clock, replies):
        self.clock, self.replies, self.calls = clock, list(replies), []

    def chat(self, *, request_timeout, **kwargs):
        kwargs["request_timeout"] = request_timeout
        self.calls.append({**kwargs, "started": self.clock.now})
        cost, result = self.replies.pop(0)
        limit = kwargs["request_timeout"]
        self.clock.now += min(cost, limit)
        if cost > limit:
            raise TimeoutError("synthetic model timeout")
        if isinstance(result, Exception):
            raise result
        return json.dumps(result) if isinstance(result, dict) else result


@pytest.fixture
def make_runtime():
    clock = Clock()
    with patch("time.monotonic", lambda: clock.now):
        def make(replies, *, remaining=1200, **settings):
            client = ScriptedClient(clock, replies)
            runtime = StagedReasoningRuntime(client, replace(AgentConfig(), **settings))
            runtime.state = AgentState(problem="Use the definition.", efficient_runtime=True,
                                       started_at=clock.now, deadline_at=clock.now + remaining,
                                       finalize_reserve_seconds=30)
            runtime._constraint_ledger = "Preserve the original boundary."
            return runtime, client, clock
        yield make


def review(runtime, *, preserve_repair=False):
    return runtime._review_candidate("Use the definition.", ProblemProfile(), StagedStrategy(),
                                     DRAFT, {"ok": True, "summary": []}, preserve_repair=preserve_repair)[1]


def test_fast_pass_skips_deep_thinking(make_runtime):
    runtime, client, _ = make_runtime([(3, PASS), (4, PASS)])
    assert review(runtime).verdict == "pass"
    assert [call["thinking_mode"] for call in client.calls] == [False, False]
    assert [call["request_timeout"] for call in client.calls] == [20, 45]


@pytest.mark.parametrize("quick", [DOUBT, FAIL])
def test_doubts_escalate_to_focused_deep_review_with_an_independent_token_cap(make_runtime, quick):
    runtime, client, _ = make_runtime([(3, PASS), (4, quick), (5, FAIL)])
    assert review(runtime).verdict == "fail"
    assert [call["thinking_mode"] for call in client.calls] == [False, False, True]
    assert client.calls[-1]["max_tokens"] == 8192
    payload = json.loads(client.calls[-1]["messages"][1]["content"])
    assert payload["review_focus"]["verdict"] == quick["verdict"]
    assert payload["solution"] == DRAFT
    assert "不要重写完整解答" in client.calls[-1]["messages"][0]["content"]


def test_shared_deadline_covers_fidelity_fast_deep_and_parse_recovery(make_runtime):
    runtime, client, clock = make_runtime([(20, PASS), (45, DOUBT), (60, "bad JSON"), (10, PASS)])
    started = clock.now
    assert review(runtime).verdict == "pass"
    assert clock.now - started == 135
    assert len(client.calls) == 4
    for call in client.calls:
        assert call["request_timeout"] <= started + 150 - call["started"]
    assert client.calls[-1]["thinking_mode"] is False
    assert runtime._review_deadline is None


def test_deep_timeout_uses_remaining_budget_without_retry_or_false_failure(make_runtime):
    runtime, client, clock = make_runtime([(20, PASS), (30, DOUBT), (60, FAIL)],
                                         staged_review_round_budget_seconds=70)
    started = clock.now
    audit = review(runtime)
    assert client.calls[-1]["request_timeout"] == 20
    assert clock.now - started == 70
    assert audit.verdict == "uncertain" and audit.review_status == "service_unavailable"
    assert len(client.calls) == 3


def test_fidelity_timeout_cannot_turn_a_later_fast_pass_into_a_completed_review(make_runtime):
    runtime, client, _ = make_runtime([(100, PASS), (3, PASS)])
    audit = review(runtime)
    assert audit.verdict == "uncertain" and audit.review_status == "service_unavailable"
    assert len(client.calls) == 2
    assert not any(item["type"] == "audit_parse_retry_started" for item in runtime.trace)


def test_fast_timeout_does_not_start_deep_review_or_format_retry(make_runtime):
    runtime, client, _ = make_runtime([(3, PASS), (100, PASS)])
    audit = review(runtime)
    assert audit.verdict == "uncertain" and audit.review_status == "service_unavailable"
    assert len(client.calls) == 2


def test_primary_solver_preserves_review_repair_and_delivery_windows(make_runtime):
    runtime, client, clock = make_runtime([(660, DRAFT)])
    started = clock.now
    assert runtime._solve("Use the definition.", ProblemProfile(), StagedStrategy(), "", attempt=1) == DRAFT
    assert client.calls[0]["request_timeout"] == 660
    assert runtime.state.deadline_at - clock.now == 540
    assert clock.now - started == 660


def test_late_primary_solver_reduces_its_cap_before_using_reserved_time(make_runtime):
    runtime, client, clock = make_runtime([(580, DRAFT)], remaining=1000)
    assert runtime._solve("Use the definition.", ProblemProfile(), StagedStrategy(), "", attempt=1) == DRAFT
    assert client.calls[0]["request_timeout"] == 580
    assert runtime.state.deadline_at - clock.now == 420


def test_primary_recovery_reuses_the_same_solver_deadline(make_runtime):
    runtime, client, _ = make_runtime([(100, "incomplete"), (100, DRAFT)],
                                     staged_compact_reasoning_only=False)
    assert runtime._solve("Use the definition.", ProblemProfile(), StagedStrategy(), "", attempt=1) == DRAFT
    assert [call["request_timeout"] for call in client.calls] == [660, 560]


def test_repair_and_recheck_can_use_the_reserved_four_minutes(make_runtime):
    runtime, client, clock = make_runtime([(180, DRAFT), (20, PASS), (40, PASS)], remaining=270)
    assert runtime._solve("Use the definition.", ProblemProfile(), StagedStrategy(), "", attempt=2,
                           previous="old draft", audit=StagedAudit(verdict="fail")) == DRAFT
    assert review(runtime).verdict == "pass"
    assert [call["request_timeout"] for call in client.calls] == [180, 20, 40]
    assert runtime.state.deadline_at - clock.now == 30


def test_no_review_call_is_issued_when_only_repair_and_delivery_time_remains(make_runtime):
    runtime, client, _ = make_runtime([], remaining=270)
    audit = review(runtime, preserve_repair=True)
    assert not client.calls
    assert audit.verdict == "uncertain" and audit.review_status == "service_unavailable"


def test_review_budget_is_reset_for_the_next_round(make_runtime):
    runtime, client, _ = make_runtime([(20, PASS), (45, PASS), (20, PASS), (45, PASS)])
    assert review(runtime).verdict == review(runtime).verdict == "pass"
    assert [call["request_timeout"] for call in client.calls] == [20, 45, 20, 45]


def test_new_budget_settings_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("STAGED_REVIEW_ROUND_BUDGET_SECONDS", "120")
    monkeypatch.setenv("STAGED_SOLVER_REPAIR_TIMEOUT_SECONDS", "150")
    config = AgentConfig()
    assert config.staged_review_round_budget_seconds == 120
    assert config.staged_solver_repair_timeout_seconds == 150


def test_pass_with_unmet_obligations_requires_deep_review(make_runtime):
    runtime, client, _ = make_runtime([(3, PASS), (4, {**PASS, "unmet_obligations": ["boundary"]}),
                                     (5, PASS)])
    assert review(runtime).verdict == "pass"
    assert len(client.calls) == 3 and client.calls[-1]["thinking_mode"] is True


def test_unavailable_fidelity_format_recovery_cannot_be_treated_as_verified(make_runtime):
    runtime, _, _ = make_runtime([(1, "bad JSON"), (1, "bad JSON"), (1, PASS)])
    audit = review(runtime)
    assert audit.verdict == "uncertain" and audit.review_status == "service_unavailable"

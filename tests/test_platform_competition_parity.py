"""Compare fixed model requests across shared orchestration and Web graph nodes."""

import asyncio
import copy
import json
import threading
import time
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest

pytest.importorskip("langgraph")

from agent_platform.graph_runtime import LangGraphRuntime
from agent_platform.staged_adapter import StagedAdapter, TracedClient
from agent_platform.tools.local import LocalTools
from agent_platform.tools.registry import ToolRegistry, validated_result
from reasoning_agent.action_graph.strategy_cards import build_strategy_cards
from reasoning_agent.custom2.model_call import ModelCallBudgetExhausted
from reasoning_agent.custom2.staged_runtime import StagedReasoningRuntime
from test_platform_graph import config, context, draft


class RecordingClient:
    def __init__(self, responses):
        self.responses = copy.deepcopy(responses)
        self.calls = []

    def chat(self, request_timeout=None, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def failure(error_type="calculation"):
    return json.dumps({
        "verdict": "fail", "error_type": error_type,
        "invalid_claim": "The defining calculation gives the result.",
        "evidence": "Substitution yields a different value.",
        "first_fatal_error": "The cited step is invalid.",
        "required_changes": ["Recompute the defining calculation."],
        "forbidden_reuse": ["Do not assume the claimed value."],
    })


def initial(*, risk="high", solution=None):
    return [json.dumps({"domain": "linear_algebra", "answer_mode": "computation"}),
            json.dumps({"risk_level": risk}), draft() if solution is None else solution]


PASS = '{"verdict":"pass"}'
UNCERTAIN = '{"verdict":"uncertain"}'


def compare(responses, **settings):
    cfg = replace(config(), **settings)
    ctx, events, checkpoints = context()
    reference_client, graph_client = RecordingClient(responses), RecordingClient(responses)
    expected = StagedReasoningRuntime(reference_client, copy.deepcopy(cfg)).run(ctx.problem)
    runtime = LangGraphRuntime(graph_client, cfg, function_calling="off")
    actual = asyncio.run(runtime.run(ctx))
    assert actual.final_response == expected["final_response"]
    assert graph_client.calls == reference_client.calls
    assert graph_client.responses == reference_client.responses == []
    return runtime, ctx, events, checkpoints, graph_client


@pytest.mark.parametrize("risk", ["low", "high"])
def test_success_preserves_prompts_thinking_temperature_and_token_limits(risk):
    responses = initial(risk=risk) + ([PASS, PASS] if risk == "high" else [])
    _, _, _, _, client = compare(responses)
    if risk == "high":
        assert client.calls[-1]["thinking_mode"] is True


@pytest.mark.parametrize("error_type,action", [
    ("calculation", "local_repair"), ("format", "local_repair"),
    ("missing_proof", "proof_completion"), ("coverage", "proof_completion"),
    ("model", "global_restart"), ("definition", "global_restart"),
    ("direction", "global_restart"), ("other", "strategy_rethink"),
])
def test_evidence_backed_repair_routes_match_reference(error_type, action):
    _, _, events, checkpoints, client = compare(
        initial(solution=draft("3")) + [PASS, failure(error_type), draft(), PASS, PASS],
    )
    assert any(data.get("action") == action for _, _, data in events)
    assert checkpoints[-1]["repair_count"] == 1
    assert client.calls[5]["temperature"] == .5


@pytest.mark.parametrize("review", [UNCERTAIN, PASS])
def test_inconclusive_review_does_not_trigger_mathematical_repair(review):
    compare(initial() + [PASS, review])


def test_repair_uncertainty_selects_candidate_by_evidence():
    compare(initial(solution=draft("3")) + [PASS, failure(), draft(), PASS, UNCERTAIN])


def test_exhausted_repairs_use_identical_arbitration_evidence():
    compare(initial(solution=draft("3")) + [PASS, failure(), draft("4"), PASS,
                                          failure(), draft()], custom2_max_repairs=1)


def test_empty_solver_uses_emergency_recovery():
    _, _, _, checkpoints, _ = compare(initial(solution="") + [draft()])
    assert any(item["next_stage"] == "emergency" for item in checkpoints)


def test_hard_false_assertions_cannot_be_returned_as_final_answer():
    bad = draft().replace("The defining calculation gives the result.",
                          "The defining calculation gives the result.\n```check\nassert 2 == 3\n```")
    runtime, ctx, _, _, _ = compare(initial(solution=bad) + [PASS, PASS, ""],
                                   custom2_max_repairs=0)
    assert ctx.checkpoint["final_response"] == "无法确定唯一答案"
    assert runtime.checkpoint_compatible(ctx.checkpoint)


def test_resume_new_recovery_nodes_skips_all_completed_model_calls():
    responses = initial(solution=draft("3")) + [PASS, failure(), draft("4"), PASS, failure(), draft()]
    runtime, original, _, checkpoints, client = compare(responses, custom2_max_repairs=1)
    started = 0
    for checkpoint in checkpoints:
        next_stage = checkpoint["next_stage"]
        started = {"retrieve": 1, "plan": 1, "solve": 2, "repair": 5,
                   "arbitrate": 8, "finalize": 9, "terminal": 9}.get(next_stage, started)
        if next_stage == "tool":
            started = 6 if checkpoint["repair_count"] else 3
        elif next_stage == "verify":
            started = 6 if checkpoint["repair_count"] else 3
        remaining = RecordingClient(responses[started:])
        resumed = LangGraphRuntime(remaining, runtime.config, function_calling="off")
        ctx, _, _ = context(checkpoint, original.deadline_at)
        result = asyncio.run(resumed.run(ctx))
        assert result.final_response == r"\boxed{2}"
        assert remaining.calls == client.calls[started:]


def test_resume_emergency_node_and_completed_emergency_does_not_replay():
    runtime, original, _, checkpoints, _ = compare(initial(solution="") + [draft()])
    for checkpoint in checkpoints:
        if checkpoint["next_stage"] not in {"emergency", "finalize"}:
            continue
        client = RecordingClient([draft()] if checkpoint["next_stage"] == "emergency" else [])
        ctx, _, _ = context(checkpoint, original.deadline_at)
        resumed = LangGraphRuntime(client, runtime.config, function_calling="off")
        assert asyncio.run(resumed.run(ctx)).final_response == r"\boxed{2}"
        assert not client.responses


@pytest.mark.parametrize("call_type", ["emergency_direct_solver", "emergency_integrator", "final_arbitrator"])
def test_started_recovery_call_budget_survives_interruption(call_type):
    ctx, _, _ = context()
    ctx.model_calls[call_type] = 1
    client = RecordingClient([draft()])
    proxy = TracedClient(client, ctx, "solve", threading.BoundedSemaphore(1))
    proxy.call_type = call_type
    with pytest.raises(ModelCallBudgetExhausted):
        proxy._chat_once(messages=[], temperature=0, max_tokens=10)
    assert not client.calls


def test_graph_nodes_retain_elapsed_convergence_budget():
    cfg = config(staged_convergence_seconds=10)
    ctx, _, _ = context()
    runtime = LangGraphRuntime(RecordingClient([]), cfg)
    state = runtime._load(ctx)
    state["workflow_started_at"] = (ctx.deadline_at - timedelta(seconds=1250)).isoformat()
    adapter = StagedAdapter(runtime.client, cfg, ctx, "solve", runtime.permits, state)
    assert time.monotonic() - adapter.state.started_at >= 50
    assert adapter._convergence_due()


def test_private_thoughts_never_enter_candidates_or_checkpoints():
    responses = initial(solution="<think>PRIVATE_DELIBERATION</think>\n" + draft()) + [PASS, PASS]
    ctx, events, checkpoints = context()
    result = asyncio.run(LangGraphRuntime(RecordingClient(responses), config()).run(ctx))
    assert result.final_response == r"\boxed{2}"
    assert "PRIVATE_DELIBERATION" not in json.dumps(checkpoints)
    assert "PRIVATE_DELIBERATION" not in json.dumps(events)


@pytest.mark.parametrize("unavailable", [TimeoutError("transport unavailable"), "invalid json"])
def test_audit_transport_and_protocol_recovery_preserve_model_requests(unavailable):
    compare(initial() + [PASS, unavailable, UNCERTAIN])


@pytest.mark.parametrize("compact,retry", [(True, True), (False, True)])
def test_compact_and_compressed_retry_paths_match_reference(compact, retry):
    responses = initial(solution="" if not compact else draft())
    if not compact:
        responses.append(draft())
    compare(responses + [PASS, PASS], staged_compact_reasoning_only=compact,
            staged_solver_compressed_retry_enabled=retry)


@pytest.mark.parametrize("mode,similarity,example_visible", [
    ("lexical", None, True), ("legacy_embedding", .9, True),
    ("hybrid", .6, True), ("hybrid", .45, False), ("hybrid", .2, False),
])
def test_typed_retrieval_preserves_structured_query_and_confidence_cards(mode, similarity, example_visible):
    from test_action_graph_strategy_retrieval import RESULT

    class Retriever:
        def __init__(self):
            self.calls = []

        def retrieve_for_structure(self, problem, query, **kwargs):
            self.calls.append((problem, query, kwargs))
            card = {**RESULT, "vector_score": similarity,
                    "score": similarity if mode == "legacy_embedding" else .08}
            return {"retrieval_text": query, "results": [card], "index_version": "fixture-v1"}

    query = "Domain: algebra\nGoal: compute a value\nObjects: matrices\nStructure:\n- finite dimension"
    cfg = replace(config(), staged_strategy_retrieval_enabled=True,
                  staged_strategy_retrieval_mode=mode)
    responses = [*initial()[:1], query, *initial()[1:], PASS, PASS]
    reference_client, graph_client = RecordingClient(responses), RecordingClient(responses)
    retriever = Retriever()
    ctx, _, checkpoints = context()
    with patch("reasoning_agent.custom2.staged_runtime.get_shared_" +
               {"hybrid": "hybrid_strategy_retriever", "lexical": "lexical_strategy_retriever",
                "legacy_embedding": "strategy_retriever"}[mode], return_value=retriever):
        expected = StagedReasoningRuntime(reference_client, copy.deepcopy(cfg)).run(ctx.problem)
    runtime = LangGraphRuntime(graph_client, cfg, tools=ToolRegistry(LocalTools(retriever=retriever)),
                               function_calling="off")
    actual = asyncio.run(runtime.run(ctx))
    assert actual.final_response == expected["final_response"]
    assert graph_client.calls == reference_client.calls
    assert len(retriever.calls) == 2
    assert retriever.calls[0][:2] == retriever.calls[1][:2]
    solver = json.dumps(graph_client.calls[3], ensure_ascii=False)
    assert ("Example problem" in solver) == example_visible
    assert ("Example solution" in solver) == example_visible
    assert "Example solution" not in json.dumps(graph_client.calls[2])
    if similarity == .2:
        assert not checkpoints[1]["adapter"]["_solver_strategy_cards"]


def test_full_length_unicode_cards_fit_the_typed_tool_result_budget():
    raw = {"status": "succeeded", "value": {"matches": [], "rendered_cards": {
        "planner": "方法" * 6000, "executor": "推导" * 6000,
    }}}
    result = validated_result("strategy_search", raw)
    assert len(result.value["rendered_cards"]["executor"]) == 12000


def test_strategy_card_budget_counts_separators_between_whole_cards():
    from test_action_graph_strategy_retrieval import RESULT

    single = build_strategy_cards([RESULT], max_chars=12000)
    cards = build_strategy_cards([RESULT, RESULT], max_chars=2 * len(single.executor))
    assert len(cards.executor) <= 2 * len(single.executor)
    assert cards.executor_truncated


def test_configured_workflow_deadline_and_return_reserve_survive_nodes():
    cfg = config(custom2_total_budget_seconds=100, staged_best_candidate_return_seconds=40)
    ctx, _, _ = context()
    runtime = LangGraphRuntime(RecordingClient([]), cfg)
    state = runtime._load(ctx)
    state["workflow_started_at"] = (ctx.deadline_at - timedelta(seconds=1220)).isoformat()
    adapter = StagedAdapter(runtime.client, cfg, ctx, "solve", runtime.permits, state)
    remaining = adapter.state.deadline_at - time.monotonic()
    assert 79 <= remaining <= 80
    assert 39 <= adapter.state.best_candidate_deadline_at - time.monotonic() <= 40

"""Golden scenarios: ``langgraph_final`` must behave exactly like the pre-refactor graph.

Every scenario runs once on the frozen baseline (``tests/baseline_runtime``, a copy of the
original ``agent_platform`` runtime at git HEAD) and once on
``reasoning_agent.langgraph_final`` with identical scripted model responses,
then compares everything observable: final answer, trace events, checkpoints,
model calls and saved responses. Wall-clock values and random identifiers are
dropped; ``config_hash`` is dropped because the final runtime also hashes its
own sources (the platform graph cannot see them).
"""

import asyncio
import copy
import json
import threading
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Callable
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("langgraph")

from baseline_runtime.graph_runtime import GRAPH_STAGES, LangGraphRuntime as PlatformRuntime
from agent_platform.models import Message, utc_now
from agent_platform.presentation import QUESTION_INSTRUCTION_KEY, RESPONSE_STYLE_KEY
from agent_platform.runtime import CheckpointIncompatible, RuntimeContext
from baseline_runtime.staged_adapter import StagedAdapter as PlatformEngine
from agent_platform.tools.registry import ToolRegistry
from reasoning_agent.custom.config import AgentConfig
from reasoning_agent.custom2.staged_models import StagedAudit, StagedModelFidelity

from reasoning_agent.langgraph_final import LangGraphRuntime as FinalRuntime
from reasoning_agent.langgraph_final.engine import StageEngine as FinalEngine


@dataclass(frozen=True)
class Flavor:
    name: str
    runtime: type
    engine: type


FLAVORS = (Flavor("platform", PlatformRuntime, PlatformEngine), Flavor("final", FinalRuntime, FinalEngine))

VOLATILE_STATE = ("deadline_at", "workflow_started_at", "config_hash")
VOLATILE_EVENT = ("operation_id", "call_id", "invocation_id")  # plus any ``*_ms`` timing field


def draft(value="2", *, proof=False):
    return (
        "## 问题分析\nUse the given definition.\n"
        "## 详细解题步骤\nThe defining calculation gives the result.\n"
        f"## 最终答案\n{value if proof else chr(92) + 'boxed{' + value + '}'}\n"
        "## 关键验证点\nCheck the defining condition."
    )


class ScriptedClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, temperature, max_tokens, request_timeout=None, **kwargs):
        self.calls.append({"messages": messages, "temperature": temperature,
                           "max_tokens": max_tokens, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def config(**updates):
    defaults = {"staged_strategy_retrieval_enabled": False,
                "staged_strategy_model_enabled": True,
                "staged_compact_reasoning_only": False,
                "staged_solver_compressed_retry_enabled": False}
    return replace(AgentConfig(custom2_solver_protocol="staged"), **{**defaults, **updates})


def passing(*, proof=False, value="2"):
    return [
        json.dumps({"answer_mode": "proof" if proof else "computation", "domain": "linear_algebra"}),
        '{"risk_level":"high"}',
        draft("Conclusion follows." if proof else value, proof=proof),
        '{"verdict":"pass"}', '{"verdict":"pass"}',
    ]


def normalize_state(state):
    if not isinstance(state, dict):
        return state
    return {key: value for key, value in state.items() if key not in VOLATILE_STATE}


def normalize_events(events):
    return [(stage, kind, {key: value for key, value in (payload or {}).items()
                           if key not in VOLATILE_EVENT and not key.endswith("_ms")})
            for stage, kind, payload in events]


def make_context(checkpoint=None, deadline=None, *, metadata=None, memory=(), problem=None):
    events, checkpoints = [], []
    ctx = RuntimeContext(
        "task", "session", problem or "Compute a value from its definition.", metadata or {}, memory,
        checkpoint,
        lambda stage, completed, state: checkpoints.append(copy.deepcopy(state)) if completed else None,
        deadline_at=deadline or utc_now() + timedelta(seconds=1200),
        record=lambda stage, kind, data: events.append((stage, kind, data)))
    return ctx, events, checkpoints


def observe(flavor, responses, *, cfg=None, patches: Callable[[type], list] | None = None,
            checkpoint=None, deadline=None, metadata=None, memory=(), problem=None,
            runtime_kwargs=None):
    client = ScriptedClient(responses)
    runtime = flavor.runtime(client, config(**(cfg or {})),
                             **{"function_calling": "off", **(runtime_kwargs or {})})
    ctx, events, checkpoints = make_context(checkpoint, deadline, metadata=metadata,
                                            memory=memory, problem=problem)
    with ExitStack() as stack:
        for item in (patches(flavor.engine) if patches else []):
            stack.enter_context(item)
        try:
            outcome = ("ok", asyncio.run(runtime.run(ctx)).final_response)
        except Exception as exc:  # noqa: BLE001 - parity includes the failure type
            outcome = ("error", type(exc).__name__)
    return {
        "outcome": outcome,
        "events": normalize_events(events),
        "checkpoints": [normalize_state(item) for item in checkpoints],
        "final_checkpoint": normalize_state(ctx.checkpoint),
        "calls": client.calls,
        "saved": ctx.saved_response,
        "model_calls": dict(ctx.model_calls),
        "solver_calls": ctx.solver_calls_used,
        "_raw_checkpoints": checkpoints,
        "_deadline": ctx.deadline_at,
    }


def public(obs):
    return {key: value for key, value in obs.items() if not key.startswith("_")}


# --- scenarios -------------------------------------------------------------------------------


def _repair_patches(reviews):
    def build(engine):
        return [patch.object(engine, "_model_fidelity", return_value=StagedModelFidelity(verdict="pass")),
                patch.object(engine, "_audit", side_effect=list(reviews))]
    return build


def _arbitrate_patches(reviews, arbitrated):
    def build(engine):
        return [*_repair_patches(reviews)(engine),
                patch.object(engine, "_final_arbitrate", return_value=arbitrated)]
    return build


def scenario_pass_first_try(flavor):
    return observe(flavor, passing())


def scenario_proof_pass(flavor):
    return observe(flavor, passing(proof=True), problem="Prove the stated conclusion from the definition.")


def scenario_planner_low_risk_skips_review(flavor):
    return observe(flavor, ['{"answer_mode":"computation"}', '{"risk_level":"low"}', draft("4")])


def scenario_planner_medium_risk_gets_reviewed(flavor):
    # Only an explicit "low" skips the model review; medium (the planner-off default) must not.
    return observe(flavor, ['{"answer_mode":"computation"}', '{"risk_level":"medium"}', draft("4"),
                            '{"verdict":"pass"}', '{"verdict":"pass"}'])


def scenario_planner_disabled_default_risk(flavor):
    return observe(flavor, ['{"answer_mode":"computation"}', draft("4"),
                            '{"verdict":"pass"}', '{"verdict":"pass"}'],
                   cfg={"staged_strategy_model_enabled": False})


def scenario_audit_findings_feed_the_repair_prompt(flavor):
    # forbidden_reuse must land in the checkpoint's persistent avoidance list AND in the repair prompt.
    return observe(flavor, ['{"answer_mode":"computation"}', '{"risk_level":"high"}', draft("3"), draft("7")],
                   cfg={"custom2_max_repairs": 1},
                   patches=_repair_patches([
                       StagedAudit(verdict="fail", first_fatal_error="wrong step",
                                   forbidden_reuse=["analogy with the unit circle"]),
                       StagedAudit(verdict="pass")]))


def scenario_long_partial_solution_is_truncated(flavor):
    # A solver reply that has the public sections but no boxed answer: the partial text is kept,
    # truncated to the checkpoint limit, and no candidate is accepted.
    section = "## 问题分析\n" + "分析" * 30000 + "\n## 详细解题步骤\n" + "步骤" * 30000 + "\n"
    return observe(flavor, ['{}', '{"risk_level":"high"}', section, '', ''])


def scenario_finalize_failure_is_not_swallowed(flavor):
    # Unlike every other stage, a failing finalize must surface instead of falling back.
    # _final_result failing is caught inside finalize; its fallback then records an event, and if
    # *that* fails too the error escapes the stage and the harness must re-raise it.
    def broken(engine):
        real_record = engine._record

        def record(self, event, **data):
            if event == "final_acceptance_failed":
                raise RuntimeError("private record failure")
            return real_record(self, event, **data)
        return [patch.object(engine, "_final_result", side_effect=RuntimeError("private final failure")),
                patch.object(engine, "_record", record)]
    return observe(flavor, passing(), patches=broken)


def scenario_repair_then_pass(flavor):
    return observe(flavor, ['{"answer_mode":"computation"}', '{"risk_level":"high"}', draft("3"), draft("7")],
                   cfg={"custom2_max_repairs": 1},
                   patches=_repair_patches([StagedAudit(verdict="fail", first_fatal_error="wrong step"),
                                            StagedAudit(verdict="pass")]))


def scenario_repair_still_failing(flavor):
    return observe(flavor, ['{"answer_mode":"computation"}', '{"risk_level":"high"}', draft("3"), draft("7")],
                   cfg={"custom2_max_repairs": 1},
                   patches=_repair_patches([StagedAudit(verdict="fail", first_fatal_error="wrong step"),
                                            StagedAudit(verdict="fail", first_fatal_error="still wrong")]))


def scenario_arbitration_accepts_new_candidate(flavor):
    return observe(flavor, ['{"answer_mode":"computation"}', '{"risk_level":"high"}', draft("3"), draft("7")],
                   cfg={"custom2_max_repairs": 1},
                   patches=_arbitrate_patches([StagedAudit(verdict="fail", first_fatal_error="a"),
                                               StagedAudit(verdict="fail", first_fatal_error="b")], draft("9")))


def scenario_arbitration_declines(flavor):
    return observe(flavor, ['{"answer_mode":"computation"}', '{"risk_level":"high"}', draft("3"), draft("7")],
                   cfg={"custom2_max_repairs": 1},
                   patches=_arbitrate_patches([StagedAudit(verdict="fail", first_fatal_error="a"),
                                               StagedAudit(verdict="fail", first_fatal_error="b")], None))


def scenario_emergency_after_empty_solver(flavor):
    return observe(flavor, ['{}', '{"risk_level":"high"}', '', draft("5")])


def scenario_solver_failure_without_emergency_answer(flavor):
    return observe(flavor, ['{}', '{"risk_level":"high"}', ''])


def scenario_local_check_failure(flavor):
    return observe(flavor, passing(), cfg={"custom2_max_repairs": 0},
                   patches=lambda engine: [patch.object(engine, "_local_checks",
                                                        side_effect=RuntimeError("private failure"))])


def scenario_typed_tool_failure(flavor):
    return observe(flavor, passing(), cfg={"custom2_max_repairs": 0},
                   patches=lambda engine: [patch("agent_platform.tools.local.LocalTools.math_verify",
                                                 side_effect=RuntimeError("private tool failure"))])


def scenario_verify_stage_failure_recovers(flavor):
    return observe(flavor, passing(),
                   patches=lambda engine: [patch.object(engine, "_model_fidelity",
                                                        side_effect=RuntimeError("private"))])


def scenario_no_budget(flavor):
    return observe(flavor, [], deadline=utc_now() + timedelta(seconds=20))


def scenario_question_instruction_and_style(flavor):
    return observe(flavor, passing(),
                   metadata={QUESTION_INSTRUCTION_KEY: "请简要回答", RESPONSE_STYLE_KEY: "detailed"})


def scenario_auto_style_answer_request(flavor):
    responses = passing()
    responses[0] = json.dumps({"answer_mode": "computation", "domain": "linear_algebra",
                               "response_style": "answer", "response_style_evidence": "只给最终答案"})
    return observe(flavor, responses, metadata={RESPONSE_STYLE_KEY: "auto"},
                   problem="Compute a value from its definition. 只给最终答案")


def scenario_session_memory(flavor):
    return observe(flavor, passing(),
                   memory=(Message("message", "user", "previous context", "old-task"),))


def scenario_native_function_calling_mode(flavor):
    return observe(flavor, passing(), runtime_kwargs={"function_calling": "auto"})


SCENARIOS = {
    "pass_first_try": scenario_pass_first_try,
    "proof_pass": scenario_proof_pass,
    "planner_low_risk_skips_review": scenario_planner_low_risk_skips_review,
    "planner_medium_risk_gets_reviewed": scenario_planner_medium_risk_gets_reviewed,
    "planner_disabled_default_risk": scenario_planner_disabled_default_risk,
    "repair_then_pass": scenario_repair_then_pass,
    "audit_findings_feed_the_repair_prompt": scenario_audit_findings_feed_the_repair_prompt,
    "long_partial_solution_is_truncated": scenario_long_partial_solution_is_truncated,
    "finalize_failure_is_not_swallowed": scenario_finalize_failure_is_not_swallowed,
    "repair_still_failing": scenario_repair_still_failing,
    "arbitration_accepts_new_candidate": scenario_arbitration_accepts_new_candidate,
    "arbitration_declines": scenario_arbitration_declines,
    "emergency_after_empty_solver": scenario_emergency_after_empty_solver,
    "solver_failure_without_emergency_answer": scenario_solver_failure_without_emergency_answer,
    "local_check_failure": scenario_local_check_failure,
    "typed_tool_failure": scenario_typed_tool_failure,
    "verify_stage_failure_recovers": scenario_verify_stage_failure_recovers,
    "no_budget": scenario_no_budget,
    "question_instruction_and_style": scenario_question_instruction_and_style,
    "auto_style_answer_request": scenario_auto_style_answer_request,
    "session_memory": scenario_session_memory,
    "native_function_calling_mode": scenario_native_function_calling_mode,
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_parity(name):
    platform, final = (public(SCENARIOS[name](flavor)) for flavor in FLAVORS)
    assert final["outcome"] == platform["outcome"]
    assert final["events"] == platform["events"]
    assert final["checkpoints"] == platform["checkpoints"]
    assert final["final_checkpoint"] == platform["final_checkpoint"]
    assert final["calls"] == platform["calls"]
    assert final["saved"] == platform["saved"]
    assert final["model_calls"] == platform["model_calls"]
    assert final["solver_calls"] == platform["solver_calls"]


def test_scenarios_exercise_every_graph_stage():
    """The parity suite is only meaningful if it reaches all ten nodes."""
    reached = {"profile"}  # the entry node never appears as a checkpoint's next_stage
    for scenario in SCENARIOS.values():
        for item in scenario(FLAVORS[0])["_raw_checkpoints"]:
            reached.add(item["next_stage"])
    assert {*GRAPH_STAGES, "terminal"} <= reached, sorted({*GRAPH_STAGES, "terminal"} - reached)


# --- resume ----------------------------------------------------------------------------------

REMAINING_AFTER = [
    ['{"risk_level":"high"}', draft(), '{"verdict":"pass"}', '{"verdict":"pass"}'],
    ['{"risk_level":"high"}', draft(), '{"verdict":"pass"}', '{"verdict":"pass"}'],
    [draft(), '{"verdict":"pass"}', '{"verdict":"pass"}'],
    ['{"verdict":"pass"}', '{"verdict":"pass"}'],
    ['{"verdict":"pass"}', '{"verdict":"pass"}'],
    [], [],
]


def test_resume_from_every_checkpoint_matches():
    runs = {}
    for flavor in FLAVORS:
        base = observe(flavor, passing())
        resumed = []
        for checkpoint, responses in zip(base["_raw_checkpoints"], REMAINING_AFTER):
            resumed.append(public(observe(flavor, responses, checkpoint=copy.deepcopy(checkpoint),
                                          deadline=base["_deadline"])))
        runs[flavor.name] = resumed
    assert len(runs["platform"]) == len(REMAINING_AFTER)
    assert runs["final"] == runs["platform"]
    assert all(item["outcome"] == ("ok", r"\boxed{2}") for item in runs["final"])


@pytest.mark.parametrize("change", ["version", "owner", "problem", "config", "deadline", "next_stage"])
def test_checkpoint_mismatch_is_rejected_by_both(change):
    for flavor in FLAVORS:
        base = observe(flavor, passing())
        state = copy.deepcopy(base["_raw_checkpoints"][-1])
        state[{"version": "schema_version", "owner": "session_id", "problem": "problem_hash",
               "config": "config_hash", "deadline": "deadline_at", "next_stage": "next_stage"}[change]] = "bad"
        again = observe(flavor, [], checkpoint=state, deadline=base["_deadline"])
        assert again["outcome"] == ("error", CheckpointIncompatible.__name__), flavor.name


# --- cancellation ----------------------------------------------------------------------------


def _cancel_during_tool(flavor):
    async def run():
        started, cleaned = threading.Event(), threading.Event()

        async def slow(name, arguments):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        client = ScriptedClient(passing())
        runtime = flavor.runtime(client, config(), tools=ToolRegistry(Mock(invoke=slow)),
                                 function_calling="off")
        ctx, events, checkpoints = make_context()
        work = asyncio.create_task(runtime.run(ctx))
        assert await asyncio.to_thread(started.wait, 2)
        ctx.cancelled.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(work, 2)
        assert await asyncio.to_thread(cleaned.wait, 2)
        return {
            "next_stage": checkpoints[-1]["next_stage"],
            "saved": ctx.saved_response,
            "calls": len(client.calls),
            "tool_completed": any(kind == "tool.completed" for _, kind, _ in events),
        }
    return asyncio.run(run())


def test_cancel_during_tool_matches():
    platform, final = (_cancel_during_tool(flavor) for flavor in FLAVORS)
    assert final == platform
    assert final["next_stage"] == "tool" and final["saved"] == r"\boxed{2}"
    assert final["calls"] == 3 and not final["tool_completed"]


# --- exhaustive routing parity -----------------------------------------------------------------
# ``route`` is a pure function, so instead of hoping scenarios reach every branch, compare the
# original and the final implementation on the whole (small) input space.


def _route_inputs():
    import itertools
    verdicts = ("pass", "uncertain", "fail")
    evidence = ("", "defect", "   ")
    for stage, budget in itertools.product(GRAPH_STAGES, (True, False)):
        for draft_, conv, partial, rec_err in itertools.product(("", "d"), (False, True), (False, True), ("", "x")):
            for verdict, ev, repairs, max_repairs, solves, max_solves, ret in itertools.product(
                    verdicts, evidence, (0, 1, 3), (0, 1, 3), (0, 1, 4, 8), (1, 2, 8), (False, True)):
                yield stage, budget, {
                    "draft": draft_, "convergence_due": conv, "partial_recovered": partial,
                    "recoverable_error": rec_err, "return_due": ret,
                    "verification": {"verdict": verdict, "first_fatal_error": ev},
                    "repair_count": repairs, "max_repairs": max_repairs,
                    "solve_calls_used": solves, "max_solve_calls": max_solves,
                }


def test_route_matches_platform_on_the_whole_input_space():
    from baseline_runtime.graph_runtime import route as platform_route
    from reasoning_agent.langgraph_final.routing import route as final_route
    count = 0
    for stage, budget, state in _route_inputs():
        assert final_route(stage, state, budget_available=budget) == \
            platform_route(stage, state, budget_available=budget), (stage, budget, state)
        count += 1
    assert count > 100_000  # the sweep really is large, not accidentally empty


def test_review_exemption_matches_the_original_expression():
    """``can_skip_model_review`` must equal the original inline condition for every input."""
    import itertools
    from reasoning_agent.custom2.staged_models import StagedStrategy
    from reasoning_agent.langgraph_final.routing import can_skip_model_review
    for ok, risk, repairs in itertools.product((True, False), ("low", "medium", "high"), (0, 1, 2)):
        plan = StagedStrategy(risk_level=risk)
        original = bool(ok and plan.risk_level == "low" and not repairs)
        assert can_skip_model_review({"ok": ok}, plan, repairs) is original

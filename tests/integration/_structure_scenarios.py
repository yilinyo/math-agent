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

from agent_platform.graph_runtime import GRAPH_STAGES, LangGraphRuntime as PlatformRuntime
from agent_platform.models import Message, utc_now
from agent_platform.presentation import QUESTION_INSTRUCTION_KEY, RESPONSE_STYLE_KEY
from agent_platform.runtime import CheckpointIncompatible, RuntimeContext
from agent_platform.staged_adapter import StagedAdapter as PlatformEngine
from agent_platform.tools.registry import ToolRegistry
from reasoning_agent.custom.config import AgentConfig
from reasoning_agent.custom2.staged_models import StagedAudit, StagedModelFidelity



@dataclass(frozen=True)
class Flavor:
    name: str
    runtime: type
    engine: type




VOLATILE_STATE = ()
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
                           "max_tokens": max_tokens, "request_timeout": request_timeout, **kwargs})
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
        "tool_calls": copy.deepcopy(ctx.tool_calls),
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

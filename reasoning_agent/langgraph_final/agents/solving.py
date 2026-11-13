"""Solving layer: produce a candidate solution, repair it, or fall back to an emergency answer."""

from typing import Any

from reasoning_agent.custom2.recovery import route_recovery
from reasoning_agent.custom2.staged_answer_extractor import extract_staged_answer
from reasoning_agent.custom2.staged_models import StagedAudit
from reasoning_agent.langgraph_final.agents.base import Agent, AgentSpec, StageInput
from agent_platform.presentation import public_sections

LAYER = "求解层"
MAX_DRAFT_CHARS = 48000


def _solve_or_repair(inp: StageInput, *, repair: bool, source: str) -> dict[str, Any]:
    """The shared body of the Solver and the Repairer: they differ only in what they are given."""
    engine, state, problem, profile, plan = inp.engine, inp.state, inp.problem, inp.profile, inp.plan
    update: dict[str, Any] = {}
    audit = StagedAudit.model_validate(state["verification"]) if repair else None
    attempt = state.get("repair_count", 0) + (2 if repair else 1)
    recovery = route_recovery(audit) if repair else None
    if recovery:
        engine._record("recovery_routed", action=recovery.action, reason=recovery.reason,
                       error_type=audit.error_type)
    draft = engine._solve(
        problem, profile, plan, engine.material(profile, plan),
        attempt=attempt,
        previous=state.get("draft", "") if repair else "", audit=audit,
        recovery_action=recovery.action if recovery else None,
    )
    # Only accepted structured reasoning is checkpointed, not raw replies.
    if not draft:
        partial = engine._last_solver_partial
        draft = partial if extract_staged_answer(partial).answer is not None else ""
        update["partial_recovered"] = bool(draft)
    if draft and len(draft) > MAX_DRAFT_CHARS:
        # Too large to checkpoint: fall back to the best candidate saved by an earlier stage.
        update["recoverable_error"] = "candidate_too_large"
        engine._best_candidate_draft = state.get("adapter", {}).get("_best_candidate_draft", "")
        engine._best_candidate_source = state.get("adapter", {}).get("_best_candidate_source", "")
        draft = ""
    if engine._capture_candidate(draft, source, attempt):
        used = [item["chunk_id"] for item in engine.evidence if item["chunk_id"] in draft]
        if used:
            engine.context.record(engine.stage, "retrieval.cited", {"chunk_ids": used,
                "status": "model_reported_not_independently_verified"})
        update["draft"] = draft
        update["recoverable_error"] = ""
    else:
        update["recoverable_error"] = "solver_no_candidate"
        update["draft"] = ""
        sections = public_sections(engine._last_solver_partial)
        update["partial_solution"] = "\n\n".join(
            f"## {name}\n{text}" for name, text in sections.items()
        )[:MAX_DRAFT_CHARS]
    if repair:
        update["repair_count"] = state["repair_count"] + 1
        update["recovery_action"] = recovery.action
    update["checks"] = {}
    return update


class Solver(Agent):
    spec = AgentSpec(
        name="Solver", stage="solve", layer=LAYER,
        summary="结合题型、策略卡和技能材料给出首个候选解答，保存为候选。",
        reads=frozenset({"profile", "plan", "repair_count", "adapter"}),
        writes=frozenset({"draft", "checks", "recoverable_error", "partial_recovered", "partial_solution"}),
        board_writes=frozenset({"audit_skill_summary", "best_candidate_draft", "best_candidate_source"}),
        model_calls=("solver", "solver_compressed"),
    )

    def run(self, inp: StageInput) -> dict[str, Any]:
        return _solve_or_repair(inp, repair=False, source="solve")


class Repairer(Agent):
    spec = AgentSpec(
        name="Repairer", stage="repair", layer=LAYER,
        summary="按审查意见选择修复路线（局部修复、补全证明、重选策略、全局重建）并重新求解。",
        reads=frozenset({"profile", "plan", "draft", "verification", "repair_count", "adapter"}),
        writes=frozenset({"draft", "checks", "recoverable_error", "partial_recovered", "partial_solution",
                          "repair_count", "recovery_action"}),
        board_writes=frozenset({"audit_skill_summary", "best_candidate_draft", "best_candidate_source"}),
        model_calls=("solver_repair", "solver_compressed"),
    )

    def run(self, inp: StageInput) -> dict[str, Any]:
        return _solve_or_repair(inp, repair=True, source="repair")


class EmergencySolver(Agent):
    spec = AgentSpec(
        name="EmergencySolver", stage="emergency", layer=LAYER,
        summary="首轮求解未收敛时的兜底：整合已有片段或直接求解，每个任务只调用一次。",
        reads=frozenset({"profile", "plan"}),
        writes=frozenset({"draft", "recoverable_error"}),
        board_writes=frozenset({"best_candidate_draft", "best_candidate_source"}),
        model_calls=("emergency_integrator", "emergency_direct_solver"),
    )

    def run(self, inp: StageInput) -> dict[str, Any]:
        engine = inp.engine
        update: dict[str, Any] = {}
        draft = engine._emergency_solve(
            inp.problem, inp.profile, inp.plan, "Solver 未在收敛阀值前返回完整解答",
        )
        engine._capture_candidate(draft, "emergency", 1)
        update["draft"] = draft if len(draft) <= MAX_DRAFT_CHARS else ""
        update["recoverable_error"] = ""
        return update

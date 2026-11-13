"""Existing solve stage."""
from reasoning_agent.custom2.staged_answer_extractor import extract_staged_answer
from reasoning_agent.custom2.staged_models import StagedAudit
from reasoning_agent.custom2.recovery import route_recovery
from agent_platform.presentation import public_sections


def run(engine, state, problem, profile, plan, update):
    repair = engine.node == "repair"
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
    if draft and len(draft) > 48000:
        update["recoverable_error"] = "candidate_too_large"
        engine._best_candidate_draft = state.get("adapter", {}).get("_best_candidate_draft", "")
        engine._best_candidate_source = state.get("adapter", {}).get("_best_candidate_source", "")
        draft = ""
    if engine._capture_candidate(draft, engine.node, attempt):
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
        )[:48000]
    if repair:
        update["repair_count"] = state["repair_count"] + 1
        update["recovery_action"] = recovery.action
    update["checks"] = {}

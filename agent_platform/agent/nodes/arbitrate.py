"""Existing arbitrate stage."""
from reasoning_agent.custom2.staged_models import StagedAudit


def run(engine, state, problem, profile, plan, update):
    records = engine._arbitration_records()
    audit = StagedAudit.model_validate(state.get("verification") or {})
    arbitrated = None
    if not engine._best_candidate_return_due():
        arbitrated = engine._final_arbitrate(
            problem, profile, plan, records[0]["draft"], records[-1]["draft"], audit,
            candidates=records,
        )
    if arbitrated and len(arbitrated) <= 48000:
        engine._capture_candidate(arbitrated, "final_arbitration", state["repair_count"] + 2)
    if arbitrated and len(arbitrated) <= 48000 and engine._candidate_acceptable(arbitrated):
        engine._save_candidate(arbitrated, source="final_arbitration", replace=True)
    else:
        engine._select_deadline_candidate(records, records[0]["draft"])

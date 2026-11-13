"""Existing verify stage."""
from reasoning_agent.custom2.staged_models import StagedAudit, StagedModelFidelity


def run(engine, state, problem, profile, plan, update):
    checks = state["checks"]
    if checks["ok"] and plan.risk_level == "low" and not state["repair_count"]:
        audit = StagedAudit(verdict="pass", review_status="completed")
        fidelity = StagedModelFidelity()
    else:
        fidelity = engine._model_fidelity(problem, state["draft"], plan)
        audit = (engine._fidelity_failure_as_audit(fidelity) if fidelity.verdict == "fail"
                 else engine._audit(problem, profile, plan, state["draft"], checks))
    audit = engine._apply_local_evidence(audit, checks)
    if "non_concept_final_answer_contains_chinese" in checks["summary"] and audit.verdict == "pass":
        audit = audit.model_copy(update={"verdict": "fail", "error_type": "format",
            "review_status": "format_error", "first_fatal_error":
            "非概念题的最终答案必须改写为公式、符号、坐标方程或数值，不能使用中文自然语言短语。"})
    engine._remember_audit_findings(audit)
    engine._candidate_reviews[state["draft"].strip()] = audit
    engine.candidates[-1].update(audit=audit.model_dump(), fidelity=fidelity.model_dump(), checks=checks)
    if audit.verdict == "pass":
        engine._save_candidate(state["draft"], source="verified", replace=True)
    update["verification"] = audit.model_dump()
    engine.context.record(engine.stage, "verification.completed", engine._audit_trace_data(audit))

"""Verification layer: check a candidate without trusting the solver that wrote it."""

from typing import Any

from reasoning_agent.custom2.staged_models import StagedAudit, StagedModelFidelity
from reasoning_agent.langgraph_final.agents.base import Agent, AgentSpec, StageInput
from reasoning_agent.langgraph_final.routing import can_skip_model_review

LAYER = "校验层"
MAX_DRAFT_CHARS = 48000
CHINESE_ANSWER_CHECK = "non_concept_final_answer_contains_chinese"


class Checker(Agent):
    spec = AgentSpec(
        name="Checker", stage="tool", layer=LAYER,
        summary="确定性核验：sympy 数值等式检查加本地规则检查，不调用模型。",
        reads=frozenset({"profile", "plan", "draft", "repair_count"}),
        writes=frozenset({"checks", "recoverable_error", "tool_checks"}),
        deterministic=True,
    )

    def run(self, inp: StageInput) -> dict[str, Any]:
        engine, state, problem, profile, plan = inp.engine, inp.state, inp.problem, inp.profile, inp.plan
        update: dict[str, Any] = {}
        result = engine.invoke_tool("math_verify", {
            "problem": problem, "candidate": state["draft"],
            "checks": ["numeric_equivalence", "proof_obligations"],
        }, f"candidate:{state['repair_count']}")
        try:
            update["checks"] = engine._local_checks(problem, profile, plan, state["draft"])
        except Exception:
            update["checks"] = {"ok": False, "summary": ["local_check_failed"],
                                "budget_exhausted": True}
            update["recoverable_error"] = "local_check_failed"
            engine.context.record(engine.stage, "candidate_check.failed", {"error_code": "local_check_failed"})
        update["tool_checks"] = result.value or {"error_code": result.error_code}
        if result.value and result.value["verdict"] == "fail":
            update["checks"]["ok"] = False
            update["checks"].setdefault("hard_failures", []).extend(
                result.value["checked_claims"] or [result.value["counterexample"] or "numeric_claim_failed"]
            )
        engine.candidates[-1]["checks"] = update["checks"]
        return update


class Verifier(Agent):
    spec = AgentSpec(
        name="Verifier", stage="verify", layer=LAYER,
        summary="模型审查：先做保真审查（防偷换题意），再做定向审查；低风险且本地核验通过时免审。",
        reads=frozenset({"profile", "plan", "draft", "checks", "repair_count"}),
        writes=frozenset({"verification"}),
        # A passing audit promotes the draft to the verified best candidate.
        board_writes=frozenset({"persistent_avoidance", "best_candidate_draft", "best_candidate_source"}),
        model_calls=("model_fidelity", "targeted_audit"),
    )

    def run(self, inp: StageInput) -> dict[str, Any]:
        engine, state, problem, profile, plan = inp.engine, inp.state, inp.problem, inp.profile, inp.plan
        update: dict[str, Any] = {}
        checks = state["checks"]
        if can_skip_model_review(checks, plan, state["repair_count"]):
            audit = StagedAudit(verdict="pass", review_status="completed")
            fidelity = StagedModelFidelity()
        else:
            fidelity = engine._model_fidelity(problem, state["draft"], plan)
            audit = (engine._fidelity_failure_as_audit(fidelity) if fidelity.verdict == "fail"
                     else engine._audit(problem, profile, plan, state["draft"], checks))
        audit = engine._apply_local_evidence(audit, checks)
        if CHINESE_ANSWER_CHECK in checks["summary"] and audit.verdict == "pass":
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
        return update


class Arbiter(Agent):
    spec = AgentSpec(
        name="Arbiter", stage="arbitrate", layer=LAYER,
        summary="修复耗尽后基于全部候选与证据做一次有界的最终仲裁；无可接受候选时按期限规则择优。",
        reads=frozenset({"profile", "plan", "verification", "repair_count"}),
        writes=frozenset(),
        board_writes=frozenset({"best_candidate_draft", "best_candidate_source"}),
        model_calls=("final_arbitrator",),
    )

    def run(self, inp: StageInput) -> dict[str, Any]:
        engine, state, problem, profile, plan = inp.engine, inp.state, inp.problem, inp.profile, inp.plan
        records = engine._arbitration_records()
        audit = StagedAudit.model_validate(state.get("verification") or {})
        arbitrated = None
        if not engine._best_candidate_return_due():
            arbitrated = engine._final_arbitrate(
                problem, profile, plan, records[0]["draft"], records[-1]["draft"], audit,
                candidates=records,
            )
        if arbitrated and len(arbitrated) <= MAX_DRAFT_CHARS:
            engine._capture_candidate(arbitrated, "final_arbitration", state["repair_count"] + 2)
        if arbitrated and len(arbitrated) <= MAX_DRAFT_CHARS and engine._candidate_acceptable(arbitrated):
            engine._save_candidate(arbitrated, source="final_arbitration", replace=True)
        else:
            engine._select_deadline_candidate(records, records[0]["draft"])
        return {}

"""Bounded public execution diagnostics, derived from existing runtime results."""
import json

from agent_platform.presentation.stages import clean


def library_references(material):
    try:
        entries = json.loads(material) if material else []
    except (ValueError, TypeError):
        return []
    if not isinstance(entries, list):
        return []
    return [{key: clean(entry[key], 160) if isinstance(entry[key], str) else entry[key]
             for key in ("id", "revision", "kind", "title", "category")
             if key in entry and isinstance(entry[key], (str, int))}
            for entry in entries[:4] if isinstance(entry, dict)]


def stage_context(node, state):
    candidates = state.get("candidates") or []
    round_number = (state.get("repair_count", 0) + 2 if node == "repair"
                    else len(candidates) + 1 if node in {"solve", "emergency", "arbitrate"}
                    else len(candidates))
    return {"node": node, "round": max(0, round_number)}


def stage_outcome(node, state, updates, next_stage, duration_ms, budget_available=True):
    status, reason = "completed", ""
    if updates.get("recoverable_error"):
        status, reason = "recovered", updates["recoverable_error"]
    elif node in {"solve", "repair", "emergency"} and not updates.get("draft"):
        status, reason = "incomplete", "solver_no_candidate"
    elif node == "tool":
        checks = updates.get("checks") or {}
        if checks.get("hard_failures") or checks.get("format_failures"):
            status = "needs_review"
        elif checks.get("budget_exhausted") or checks.get("verdict") != "pass":
            status = "unverified"
        else:
            status = "pass"
    elif node == "verify":
        verdict = (updates.get("verification") or {}).get("verdict")
        status = {"pass": "pass", "fail": "needs_review"}.get(verdict, "unverified")
    elif node == "finalize":
        status = "accepted" if updates.get("final_response") not in {None, "", "无法确定唯一答案"} else "rejected"
    result = {**stage_context(node, state), "status": status, "next_stage": next_stage,
              "duration_ms": duration_ms}
    if reason:
        result["reason"] = reason
    if node == "finalize":
        adapter = updates.get("adapter") or {}
        if status == "accepted":
            result["candidate_source"] = adapter.get("_best_candidate_source", "")
            chosen = next((item for item in updates.get("candidates", [])
                           if item.get("draft", "").strip() == adapter.get("_best_candidate_draft", "").strip()), {})
            if chosen.get("attempt"):
                result["candidate_round"] = chosen["attempt"]
    elif not budget_available:
        result["routing_reason"] = "task_budget_low"
    elif next_stage == "emergency":
        result["routing_reason"] = "solver_no_candidate"
    elif next_stage == "repair":
        result["routing_reason"] = "audit_requires_repair"
    elif next_stage == "arbitrate":
        result["routing_reason"] = "compare_available_candidates"
    elif node == "solve" and next_stage == "finalize":
        result["routing_reason"] = "finalize_existing_candidate"
    elif node == "verify" and next_stage == "finalize":
        result["routing_reason"] = "review_finished"
    if node == "verify":
        result["review_source"] = "local_checks" if (
            state.get("checks", {}).get("ok") and state.get("plan", {}).get("risk_level") == "low"
            and not state.get("repair_count")) else "model_review"
    return result


def publish_check_details(engine, checks):
    engine.context.record(engine.stage, "checks.completed", {
        "verdict": checks.get("verdict", "unknown"),
        "budget_exhausted": bool(checks.get("budget_exhausted")),
        "format_failures": [clean(item, 160) for item in checks.get("format_failures", [])[:8]],
        "hard_failures": [clean(item, 1000) for item in checks.get("hard_failures", [])[:12]],
        "program_checks": [{key: clean(item[key], 2000) for key in
                            ("expression", "source", "status", "verdict", "result") if key in item}
                           for item in checks.get("program_checks", [])[:12]],
    })


def public_tool_result(name, call_id, result):
    value = result.get("value") or {}
    fields = {"math_verify": ("verdict", "checked_claims", "findings", "counterexample"),
              "sympy_calculate": ("normalized_expression", "value", "conditions", "warnings")}
    details = {}
    if isinstance(value, dict):
        for key in fields.get(name, ()):
            item = value.get(key)
            if isinstance(item, list):
                details[key] = [clean(part, 2000) for part in item[:12]]
            elif item is not None:
                details[key] = clean(item, 4000)
    return {"name": name, "call_id": call_id, "status": result.get("status"),
            "error_code": result.get("error_code"), "result": details}

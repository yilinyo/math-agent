"""Existing tool stage."""



def run(engine, state, problem, profile, plan, update):
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

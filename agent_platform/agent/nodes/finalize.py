"""Existing finalize stage."""



def run(engine, state, problem, profile, plan, update):
    if state.get("repair_count") and (state.get("verification") or {}).get("verdict") == "uncertain":
        records = engine._arbitration_records()
        if records:
            engine._select_deadline_candidate(records, records[0]["draft"])
    try:
        update["final_response"] = engine._final_result(state.get("draft", ""))["final_response"]
    except Exception:
        engine._record("final_acceptance_failed", reason="candidate_check_unavailable")
        update["final_response"] = "无法确定唯一答案"

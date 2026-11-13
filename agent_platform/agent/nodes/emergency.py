"""Existing emergency stage."""



def run(engine, state, problem, profile, plan, update):
    draft = engine._emergency_solve(
        problem, profile, plan, "Solver 未在收敛阀值前返回完整解答",
    )
    engine._capture_candidate(draft, "emergency", 1)
    update["draft"] = draft if len(draft) <= 48000 else ""
    update["recoverable_error"] = ""

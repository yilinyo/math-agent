"""Existing plan stage."""



def run(engine, state, problem, profile, plan, update):
    plan = engine._strategy(problem, profile)
    engine.material(profile, plan)
    update["plan"] = plan.model_dump()

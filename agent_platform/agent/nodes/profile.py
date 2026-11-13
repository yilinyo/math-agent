"""Existing profile stage."""



def run(engine, state, problem, profile, plan, update):
    profile = engine._profile(problem)
    engine._answer_mode = profile.answer_mode
    update["profile"] = profile.model_dump()

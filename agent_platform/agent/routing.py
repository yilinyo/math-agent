"""Existing staged graph routing decisions."""
from agent_platform.agent.state import GraphState


def route(stage: str, state: GraphState, *, budget_available: bool) -> str:
    if stage == "finalize":
        return "terminal"
    if not budget_available:
        return "finalize"
    if stage == "solve":
        if not state.get("draft"):
            return "emergency"
        return "finalize" if state.get("convergence_due") or state.get("partial_recovered") else "tool"
    if stage == "repair":
        return "tool" if state.get("draft") and not state.get("recoverable_error") else "arbitrate"
    if stage in {"emergency", "arbitrate"}:
        return "finalize"
    if stage == "verify":
        audit = state["verification"]
        repairing = state["repair_count"] > 0
        if audit["verdict"] != "fail" or (not repairing and not audit.get("first_fatal_error", "").strip()):
            return "finalize"
        if (not state.get("convergence_due") and not state.get("return_due")
                and state["repair_count"] < state["max_repairs"]
                and state["solve_calls_used"] < state["max_solve_calls"]):
            return "repair"
        return "arbitrate"
    return {"profile": "retrieve", "retrieve": "plan", "plan": "solve", "tool": "verify"}[stage]

"""Where the graph goes next, and the decision rules agents share.

``route`` is a pure function: it looks only at the stage that just finished and
the state it produced. ``TRANSITIONS`` documents the same table for diagrams;
a test keeps the two in sync.
"""

from typing import Any

from reasoning_agent.langgraph_final.state import GraphState


# stage -> the stages it can hand control to ("terminal" ends the graph).
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "profile": ("retrieve", "finalize"),
    "retrieve": ("plan", "finalize"),
    "plan": ("solve", "finalize"),
    "solve": ("tool", "emergency", "finalize"),
    "tool": ("verify", "finalize"),
    "verify": ("repair", "arbitrate", "finalize"),
    "repair": ("tool", "arbitrate", "finalize"),
    "emergency": ("finalize",),
    "arbitrate": ("finalize",),
    "finalize": ("terminal",),
}


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


def can_skip_model_review(checks: dict[str, Any], plan: Any, repair_count: int) -> bool:
    """A first, low-risk draft that passed every local check needs no model review.

    ``plan`` is only inspected when the local checks passed, matching the
    original short-circuit evaluation.
    """
    return bool(checks["ok"] and plan.risk_level == "low" and not repair_count)

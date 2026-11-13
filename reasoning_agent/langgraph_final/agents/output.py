"""Output layer: turn the best accepted candidate into the answer the user sees."""

from typing import Any

from reasoning_agent.langgraph_final.agents.base import Agent, AgentSpec, StageInput

LAYER = "输出层"
NO_UNIQUE_ANSWER = "无法确定唯一答案"


class Finalizer(Agent):
    spec = AgentSpec(
        name="Finalizer", stage="finalize", layer=LAYER,
        summary="终检并渲染最终回答；没有可接受候选时如实返回“无法确定唯一答案”，不编造。",
        reads=frozenset({"draft", "repair_count", "verification"}),
        writes=frozenset({"final_response"}),
        board_writes=frozenset({"best_candidate_draft", "best_candidate_source"}),
        deterministic=True,
    )

    def run(self, inp: StageInput) -> dict[str, Any]:
        engine, state = inp.engine, inp.state
        update: dict[str, Any] = {}
        if state.get("repair_count") and (state.get("verification") or {}).get("verdict") == "uncertain":
            records = engine._arbitration_records()
            if records:
                engine._select_deadline_candidate(records, records[0]["draft"])
        try:
            update["final_response"] = engine._final_result(state.get("draft", ""))["final_response"]
        except Exception:
            engine._record("final_acceptance_failed", reason="candidate_check_unavailable")
            update["final_response"] = NO_UNIQUE_ANSWER
        return update

"""Understanding layer: what kind of problem is this, and what do we already know about it."""

from typing import Any
from uuid import uuid4

from reasoning_agent.langgraph_final.agents.base import Agent, AgentSpec, StageInput

LAYER = "理解层"


class Profiler(Agent):
    spec = AgentSpec(
        name="Profiler", stage="profile", layer=LAYER,
        summary="识别题型：领域、答案类型、证明义务，并判断回答详略。",
        reads=frozenset(), writes=frozenset({"profile"}),
        board_writes=frozenset({"answer_mode", "response_style"}),
        model_calls=("classifier",),
    )

    def run(self, inp: StageInput) -> dict[str, Any]:
        engine = inp.engine
        profile = engine._profile(inp.problem)
        engine._answer_mode = profile.answer_mode
        return {"profile": profile.model_dump()}


class Retriever(Agent):
    spec = AgentSpec(
        name="Retriever", stage="retrieve", layer=LAYER,
        summary="检索本地策略卡（词法加向量混合），可选检索会话内参考文档。",
        reads=frozenset({"profile"}), writes=frozenset({"evidence"}),
        board_writes=frozenset({"strategy_retrieval_text", "planner_strategy_cards", "solver_strategy_cards"}),
        model_calls=("strategy_retrieval",),
    )

    def run(self, inp: StageInput) -> dict[str, Any]:
        engine, problem, profile = inp.engine, inp.problem, inp.profile
        update: dict[str, Any] = {}
        operation_id = str(uuid4())
        engine.context.record(engine.stage, "retrieval.started", {"source": "local_strategy", "operation_id": operation_id})
        engine._retrieve_strategy_examples(problem, profile)
        engine.context.record(engine.stage, "retrieval.completed", {
            "hit_count": len(engine._strategy_results),
            "operation_id": operation_id,
            "references": [{key: item[key] for key in ("id", "name", "score", "tags") if key in item}
                           for item in engine._strategy_results[:20]],
            "status": "used" if engine._solver_strategy_cards else "empty_or_degraded",
        })
        if getattr(engine.context.tools.local, "documents", None) is not None:
            operation_id = str(uuid4())
            filters = {key: engine.context.metadata[key] for key in ("document_ids", "domain", "problem_type", "source")
                       if key in engine.context.metadata}
            engine.context.record(engine.stage, "retrieval.started", {
                "source": "documents", "operation_id": operation_id, "filters": filters})
            result = engine.invoke_tool("document_search", {
                "query": problem[:4000], "session_id": engine.context.session_id, "top_k": 5, **filters,
            }, "documents")
            engine.evidence = result.value["passages"] if result.value else []
            update["evidence"] = engine.evidence
            engine.context.record(engine.stage, "retrieval.completed", {
                "source": "documents", "operation_id": operation_id, "hit_count": len(engine.evidence),
                "status": "available_not_proven_used" if engine.evidence else "empty_or_degraded",
                "error_code": result.error_code,
                "references": [{key: item[key] for key in ("chunk_id", "document_id", "rank", "page_start", "page_end", "source_metadata", "scores")}
                               for item in engine.evidence],
            })
        return update


class Planner(Agent):
    spec = AgentSpec(
        name="Planner", stage="plan", layer=LAYER,
        summary="把题型和策略卡转成可执行的求解路线与风险等级（默认关闭模型规划，走默认策略）。",
        reads=frozenset({"profile"}), writes=frozenset({"plan"}),
        board_writes=frozenset({"audit_skill_summary"}),
        model_calls=("strategy",),
    )

    def run(self, inp: StageInput) -> dict[str, Any]:
        engine = inp.engine
        plan = engine._strategy(inp.problem, inp.profile)
        engine.material(inp.profile, plan)
        return {"plan": plan.model_dump()}

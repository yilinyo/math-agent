"""Existing retrieve stage."""
from uuid import uuid4
from agent_platform.observability import log_retrieval_results


def run(engine, state, problem, profile, plan, update):
    operation_id = str(uuid4())
    engine.context.record(engine.stage, "retrieval.started", {"source": "local_strategy", "operation_id": operation_id})
    engine._retrieve_strategy_examples(problem, profile)
    log_retrieval_results(engine.context.task_id, engine._strategy_results, engine._solver_strategy_cards)
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

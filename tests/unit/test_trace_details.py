import asyncio
import json
from unittest.mock import patch

from agent_platform.custom_library import CustomLibrary, LibraryEntry
from agent_platform.graph_runtime import LangGraphRuntime
from agent_platform.presentation.trace import library_references, public_tool_result
from agent_platform.staged_adapter import StagedAdapter
from reasoning_agent.custom2.staged_models import StagedAudit, StagedModelFidelity
from test_platform_graph import ScriptedClient, client_for_pass, config, context, draft


def test_trace_explains_final_rejection_and_actual_route_without_extra_calls():
    client = client_for_pass()
    client.responses[2] = draft(r"\boxed{1}\quad\boxed{2}", proof=True)
    ctx, events, _ = context()
    result = asyncio.run(LangGraphRuntime(client, config(custom2_max_repairs=0)).run(ctx))
    assert result.final_response == "无法确定唯一答案"
    acceptance = [payload for stage, kind, payload in events if stage == "finalize" and kind == "reasoning.event"
                  and payload["operation"] == "final_candidate_checked"]
    assert acceptance and acceptance[0]["accepted"] is False
    assert acceptance[0]["format_failures"] == ["multiple_final_candidates"]
    assert acceptance[0]["hard_failure_count"] == 0
    outcomes = [(stage, payload) for stage, kind, payload in events if kind == "stage.outcome"]
    assert outcomes[-1][1]["status"] == "rejected"
    assert outcomes[-1][1]["next_stage"] == "terminal"
    assert all(payload["duration_ms"] >= 0 for _, payload in outcomes)
    assert len(client.calls) == 5


def test_trace_separates_selected_library_from_actual_model_injection(tmp_path):
    library = CustomLibrary(tmp_path)
    item = library.save(LibraryEntry(kind="skill", title="Definition check", keywords="compute definition",
                                    content="PRIVATE_REFERENCE_MATERIAL"))
    client = client_for_pass()
    ctx, events, _ = context()
    asyncio.run(LangGraphRuntime(client, config(), library=library).run(ctx))
    selected = [data for _, kind, data in events if kind == "library.selected"]
    injections = [data for _, kind, data in events if kind == "library.injected"]
    assert selected[0]["references"][0]["id"] == item["id"]
    assert selected[0]["references"][0]["revision"] == 1
    assert {data["call_type"] for data in injections} == {"strategy", "solver"}
    started = {data["operation_id"] for _, kind, data in events if kind == "model.started"}
    assert all(data["operation_id"] in started for data in injections)
    assert "PRIVATE_REFERENCE_MATERIAL" not in json.dumps(events)
    assert "PRIVATE_REFERENCE_MATERIAL" in json.dumps(client.calls)
    assert len(client.calls) == 5


def test_repair_rounds_and_low_risk_shortcut_are_distinguished():
    client = ScriptedClient(['{}', '{"risk_level":"high"}', draft("3"), draft("7")])
    reviews = [StagedAudit(verdict="fail", first_fatal_error="wrong sign"), StagedAudit(verdict="pass")]
    ctx, events, _ = context()
    with patch.object(StagedAdapter, "_model_fidelity", return_value=StagedModelFidelity(verdict="pass")), \
            patch.object(StagedAdapter, "_audit", side_effect=reviews):
        asyncio.run(LangGraphRuntime(client, config(custom2_max_repairs=1)).run(ctx))
    repairs = [data for stage, kind, data in events if stage == "repair" and kind == "stage.context"]
    assert repairs == [{"node": "repair", "round": 2}]
    assert any(kind == "stage.outcome" and data["next_stage"] == "repair" for _, kind, data in events)
    client = client_for_pass()
    client.responses[1] = '{"risk_level":"low"}'
    ctx, events, _ = context()
    asyncio.run(LangGraphRuntime(client, config()).run(ctx))
    assert len(client.calls) == 3
    assert any(stage == "verify" and kind == "stage.outcome" and data["review_source"] == "local_checks"
               for stage, kind, data in events)


def test_public_tool_details_are_bounded_and_redacted(monkeypatch):
    monkeypatch.setenv("TRACE_DETAIL_SECRET", "trace-detail-secret-marker")
    payload = public_tool_result("sympy_calculate", "call", {"status": "succeeded", "value": {
        "normalized_expression": "8/5", "value": "1.6", "conditions": ["a+b>0"],
        "warnings": ["trace-detail-secret-marker C:\\private\\file.txt <think>PRIVATE</think>"],
        "prompt": "PRIVATE_PROMPT", "raw_response": "PRIVATE_RESPONSE"}})
    assert payload["result"]["value"] == "1.6"
    assert "trace-detail-secret-marker" not in json.dumps(payload)
    assert "PRIVATE" not in json.dumps(payload) and "private" not in json.dumps(payload)
    assert library_references('{"bad":"format"}') == []

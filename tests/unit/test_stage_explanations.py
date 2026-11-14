import asyncio
import json
from unittest.mock import patch

from agent_platform.graph_runtime import LangGraphRuntime
from agent_platform.staged_adapter import StagedAdapter
from agent_platform.presentation.stages import (
    audit_explanation, checks_explanation, plan_explanation, profile_explanation,
)
from reasoning_agent.custom2.staged_models import StagedAudit, StagedModelFidelity, StagedStrategy
from reasoning_agent.custom2.text_models import ProblemProfile
from test_platform_graph import ScriptedClient, client_for_pass, config, context, draft


def test_summaries_use_public_math_fields_and_redact_secrets(monkeypatch):
    monkeypatch.setenv("TIMELINE_TEST_SECRET", "credential-for-timeline-test")
    profile = ProblemProfile(domain="complex_analysis", answer_mode="computation", obligations=["domain_conditions"])
    assert "复分析" in profile_explanation(profile)
    assert "定义域" in profile_explanation(profile)
    plan = StagedStrategy(main_method="<think>PRIVATE</think>使用公式 $x=2$ credential-for-timeline-test C:\\private\\key.txt",
                          proof_obligations=["检查适用条件"])
    result = plan_explanation(plan)
    assert "$x=2$" in result and "检查适用条件" in result
    assert all(value not in result for value in ("PRIVATE", "credential-for-timeline-test", "private"))
    assert "未生成单独的方法规划" in plan_explanation(StagedStrategy())


def test_tool_and_audit_summaries_do_not_invent_verification():
    result = checks_explanation({"program_checks": [{"expression": "2+2==4", "verdict": "pass"}]}, {})
    assert "2+2==4" in result and "不等于已经证明" in result
    unavailable = StagedAudit(verdict="uncertain", review_status="protocol_error", evidence="PRIVATE protocol body")
    assert "PRIVATE" not in audit_explanation(unavailable)
    assert "未获得完整" in audit_explanation(unavailable)


def test_explanations_cover_actual_stages_without_extra_model_calls():
    client = client_for_pass()
    client.responses[1] = json.dumps({"risk_level": "high", "main_method": "使用定义计算", "checks": ["代回检查"]})
    ctx, events, _ = context()
    result = asyncio.run(LangGraphRuntime(client, config()).run(ctx))
    details = [(stage, payload) for stage, kind, payload in events if kind == "stage.explanation"]
    assert {"profile", "retrieve", "plan", "solve", "tool", "verify", "finalize"} == {stage for stage, _ in details}
    assert any("使用定义计算" in payload["content"] for stage, payload in details if stage == "plan")
    assert any(payload["kind"] == "solution" and "详细解题步骤" in payload["content"] for _, payload in details)
    assert len(client.calls) == 5 and result.final_response == r"\boxed{2}"


def test_repair_rounds_publish_separate_drafts_and_repair_evidence():
    client = ScriptedClient(['{"answer_mode":"computation"}', '{"risk_level":"high"}', draft("3"), draft("7")])
    ctx, events, checkpoints = context()
    reviews = [StagedAudit(verdict="fail", review_status="math_error", first_fatal_error="遗漏负号"),
               StagedAudit(verdict="pass", review_status="completed")]
    with patch.object(StagedAdapter, "_model_fidelity", return_value=StagedModelFidelity(verdict="pass")), \
            patch.object(StagedAdapter, "_audit", side_effect=reviews):
        asyncio.run(LangGraphRuntime(client, config(custom2_max_repairs=1)).run(ctx))
    details = [(stage, payload) for stage, kind, payload in events if kind == "stage.explanation"]
    solutions = [(stage, payload["content"]) for stage, payload in details if payload["kind"] == "solution"]
    assert [stage for stage, _ in solutions] == ["solve", "repair"]
    assert r"\boxed{3}" in solutions[0][1] and r"\boxed{7}" in solutions[1][1]
    assert any(stage == "repair" and payload["title"] == "本轮修复依据" and "遗漏负号" in payload["content"]
               for stage, payload in details)
    assert len(client.calls) == 4
    assert checkpoints[-1]["repair_count"] == 1

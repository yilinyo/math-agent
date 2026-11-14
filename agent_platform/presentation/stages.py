"""Public mathematical explanations derived from actual stage results."""
from agent_platform.observability import redact_trace_value
from agent_platform.presentation import public_sections, strip_private_thoughts
from reasoning_agent.custom2.staged_models import StagedAudit, StagedStrategy
from reasoning_agent.custom2.text_models import ProblemProfile


OBLIGATIONS = {
    "answer_supported": "结论需要有推导依据", "domain_conditions": "检查定义域和适用条件",
    "requested_parts": "覆盖题目要求的全部小问", "proof_complete": "补全必要证明",
    "lower_bound": "证明下界", "upper_bound": "证明上界",
    "attaining_construction": "给出达到界的构造", "all_cases": "覆盖全部情况",
    "option_coverage": "逐项检查选项",
}
MODES = {"choice": "选择题", "judgment": "判断题", "fill_blank": "填空题",
         "computation": "计算题", "proof": "证明题", "other": "综合解答"}
DOMAINS = {"complex_analysis": "复分析", "linear_algebra": "线性代数",
           "abstract_algebra": "抽象代数", "combinatorics": "组合数学",
           "mathematical_analysis": "数学分析", "probability": "概率论"}


def clean(value, limit=24000):
    return redact_trace_value(strip_private_thoughts(str(value or "")))[:limit].strip()


def bullets(title, values):
    lines = [clean(value, 2000) for value in list(values or [])[:12]]
    return (f"**{title}**\n\n" + "\n".join(f"- {line}" for line in lines if line)
            if any(lines) else "")


def profile_explanation(profile):
    parts = [f"本题按**{MODES.get(profile.answer_mode, '综合解答')}**组织解答。"]
    if profile.domain != "unknown":
        parts.append(f"识别领域：{DOMAINS.get(profile.domain, clean(profile.domain, 80))}。")
    parts.append(bullets("需要满足的解答要求", [OBLIGATIONS.get(v, v) for v in profile.obligations]))
    return "\n\n".join(part for part in parts if part)


def plan_explanation(plan):
    parts = []
    for title, value in [("主要方法", plan.main_method), ("备选方法", plan.backup_method)]:
        if value:
            parts.append(f"**{title}**\n\n{clean(value)}")
    for title, values in [("使用的定理与条件", plan.key_theorems),
                          ("需要证明的关键环节", plan.proof_obligations), ("计划核对的内容", plan.checks)]:
        parts.append(bullets(title, values))
    return "\n\n".join(p for p in parts if p) or "本轮未生成单独的方法规划，直接结合题意与可用参考资料展开推导。"


def checks_explanation(checks, tool_result):
    parts = []
    for item in list(checks.get("program_checks") or [])[:12]:
        expression = clean(item.get("expression"), 2000)
        verdict = {"pass": "通过", "fail": "不成立", "uncertain": "未能确定"}.get(item.get("verdict"), "未能确定")
        if expression:
            result = clean(item.get("result"), 2000)
            parts.append(f"- 核对 `{expression}`：{verdict}。" + (f"实际结果：`{result}`。" if result else ""))
    parts.append(bullets("工具实际检查的等式", tool_result.get("checked_claims", [])))
    if tool_result.get("counterexample"):
        parts.append("**发现的反例或矛盾**\n\n" + clean(tool_result["counterexample"]))
    parts.append(bullets("需要修正的计算", checks.get("hard_failures", [])))
    if checks.get("budget_exhausted"):
        parts.append("本地检查达到预算限制，部分内容尚未完成核验。")
    parts.append("以上只反映已执行的检查；未发现数值矛盾不等于已经证明整个解答正确。")
    return "\n\n".join(part for part in parts if part)


def audit_explanation(audit):
    verdict = {"pass": "通过", "fail": "发现问题", "uncertain": "尚不能确认"}[audit.verdict]
    if audit.review_status in {"service_unavailable", "protocol_error", "inconclusive"}:
        return "本轮未获得完整、可确认的审查结论。"
    parts = [f"审查结论：**{verdict}**。"]
    for title, value in [("需要关注的数学问题", audit.first_fatal_error),
                          ("核对依据", audit.evidence or audit.counterexample_or_evidence)]:
        if value:
            parts.append(f"**{title}**\n\n{clean(value)}")
    parts.append(bullets("后续需要修改", audit.required_changes))
    parts.append(bullets("尚未满足的要求", audit.unmet_obligations))
    return "\n\n".join(part for part in parts if part)


def explain(engine, content, *, title="", kind="summary"):
    content = clean(content)
    if content:
        engine.context.record(engine.stage, "stage.explanation", {
            "content": content, "title": title, "kind": kind,
        })


def publish_stage_explanation(engine, state, update):
    stage = engine.node
    if stage == "profile":
        explain(engine, profile_explanation(ProblemProfile.model_validate(update["profile"])))
    elif stage == "retrieve":
        references = [item.get("name", "") for item in engine._strategy_results[:8]]
        explain(engine, bullets("召回的内置方法", references) + (
            "\n\n参考资料仍需结合当前题目的条件判断是否适用。" if references
            else "本轮未召回可展示的内置方法，自定义资料的选入情况另行记录。"))
    elif stage == "plan":
        explain(engine, plan_explanation(StagedStrategy.model_validate(update["plan"])))
    elif stage in {"solve", "repair", "emergency", "arbitrate"}:
        draft = update.get("draft", "") if stage != "arbitrate" else engine._best_candidate_draft
        content = "\n\n".join(f"## {name}\n{text}" for name, text in public_sections(draft).items())
        explain(engine, content, kind="solution")
    elif stage == "tool":
        explain(engine, checks_explanation(update["checks"], update.get("tool_checks", {})))
    elif stage == "verify":
        explain(engine, audit_explanation(StagedAudit.model_validate(update["verification"])))
    elif stage == "finalize":
        sections = public_sections(engine._best_candidate_draft or state.get("draft", ""))
        explain(engine, ("**最终保留的验证要点**\n\n" + sections["关键验证点"])
                if sections.get("关键验证点") and update["final_response"] != "无法确定唯一答案"
                else "本轮未产生可单独展示的最终验证要点，最终结果见下方答案。")

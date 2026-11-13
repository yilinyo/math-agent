"""Existing answer rendering."""
from reasoning_agent.custom2.staged_answer_extractor import render_staged_response
from agent_platform.presentation.instructions import RESOLVED_STYLES, SECTIONS
from agent_platform.presentation.sections import _parse_solution

def render_chat_response(draft: str, answer_mode: str, style: str) -> str:
    if style not in RESOLVED_STYLES:
        raise ValueError("unresolved_response_style")
    sections, cleaned = _parse_solution(draft)
    # A proof cannot be made independently valid by showing only its conclusion.
    if style == "answer" and answer_mode != "proof":
        final_section = sections.get("最终答案")
        return final_section or render_staged_response(cleaned, answer_mode)
    steps = sections.get("详细解题步骤")
    selected = SECTIONS if style == "detailed" else ("详细解题步骤", "最终答案")
    output = []
    for name in selected:
        value = sections.get(name)
        if name == "详细解题步骤" and not steps:
            value = "当前任务未生成可展示的解题过程；以下仅保留已生成的结论。"
        if name == "最终答案" and not value:
            value = render_staged_response(cleaned, "other")
        if value:
            output.append(f"## {name}\n{value}")
    return "\n\n".join(output)

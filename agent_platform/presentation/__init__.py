"""Compatibility exports for public solution presentation."""
from agent_platform.presentation.instructions import (
    AUTO_STYLE_PROMPT, QUESTION_INSTRUCTION_KEY, RESOLVED_STYLES, RESPONSE_STYLE_KEY,
    RESPONSE_STYLES, SECTIONS, requested_style, solver_style_prompt,
)
from agent_platform.presentation.sections import _parse_solution, public_sections, strip_private_thoughts
from agent_platform.presentation.rendering import render_chat_response

__all__ = [
    "AUTO_STYLE_PROMPT", "QUESTION_INSTRUCTION_KEY", "RESOLVED_STYLES", "RESPONSE_STYLE_KEY",
    "RESPONSE_STYLES", "SECTIONS", "requested_style", "solver_style_prompt",
    "_parse_solution", "public_sections", "strip_private_thoughts", "render_chat_response",
]

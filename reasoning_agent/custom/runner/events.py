from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ToolCallEvent:
    type: Literal["tool_call"] = "tool_call"
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalAnswerEvent:
    type: Literal["final_answer"] = "final_answer"
    answer: str = ""
    reasoning_summary: str = ""


@dataclass(frozen=True)
class InvalidEvent:
    type: Literal["invalid"] = "invalid"
    raw: str = ""
    message: str = ""


ModelEvent = ToolCallEvent | FinalAnswerEvent | InvalidEvent

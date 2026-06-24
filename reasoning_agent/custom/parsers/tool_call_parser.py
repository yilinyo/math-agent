from reasoning_agent.custom.runner.events import (
    FinalAnswerEvent,
    InvalidEvent,
    ModelEvent,
    ToolCallEvent,
)
from reasoning_agent.custom.parsers.json_parser import extract_json_object


def parse_model_event(raw: str) -> ModelEvent:
    data = extract_json_object(raw)
    if not data:
        return InvalidEvent(raw=raw, message="response does not contain a JSON object")

    event_type = data.get("type")
    if event_type == "final_answer":
        answer = data.get("answer", "")
        if not isinstance(answer, str) or not answer.strip():
            return InvalidEvent(raw=raw, message="final_answer.answer is empty")
        summary = data.get("reasoning_summary", "")
        return FinalAnswerEvent(
            answer=answer.strip(),
            reasoning_summary=summary if isinstance(summary, str) else "",
        )

    if event_type == "tool_call":
        tool = data.get("tool", "")
        arguments = data.get("arguments", {})
        if not isinstance(tool, str) or not tool.strip():
            return InvalidEvent(raw=raw, message="tool_call.tool is empty")
        if not isinstance(arguments, dict):
            return InvalidEvent(raw=raw, message="tool_call.arguments must be an object")
        return ToolCallEvent(name=tool.strip(), arguments=arguments)

    return InvalidEvent(raw=raw, message=f"unknown event type: {event_type}")

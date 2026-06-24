from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    max_model_calls: int = 3
    max_tool_calls: int = 4
    max_loop_steps: int = 6
    max_response_chars: int = 30000
    max_trace_chars: int = 12000

    tool_loop_temperature: float = 0.2
    tool_loop_max_tokens: int = 4096

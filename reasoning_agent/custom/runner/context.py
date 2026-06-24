from dataclasses import dataclass, field
from typing import Any

from reasoning_agent.custom.prompts.tool_use import build_initial_messages
from reasoning_agent.custom.state import Candidate


@dataclass
class RunnerContext:
    problem: str
    metadata: dict[str, Any]
    messages: list[dict[str, str]]

    model_calls: int = 0
    tool_calls: int = 0
    loop_steps: int = 0

    observations: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    raw_responses: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def create(cls, problem: str, metadata: dict | None) -> "RunnerContext":
        normalized_problem = str(problem or "").strip()
        normalized_metadata = metadata if isinstance(metadata, dict) else {}
        return cls(
            problem=normalized_problem,
            metadata=dict(normalized_metadata),
            messages=build_initial_messages(normalized_problem),
        )

    def add_observation(self, observation: dict[str, Any]) -> None:
        self.observations.append(observation)
        self.trace.append({"step": "tool_observation", "content": observation})

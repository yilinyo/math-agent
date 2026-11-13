"""What an agent is: one graph node with a declared contract.

An agent decides *what this stage does* with the shared state and returns a
partial ``GraphState`` update. How the work is actually done (asking the
model, retrieving, checking) belongs to the engine behind ``EngineAPI``.
"""

from dataclasses import dataclass
from typing import Any, ClassVar

from reasoning_agent.custom2.staged_models import StagedStrategy
from reasoning_agent.custom2.text_models import ProblemProfile
from reasoning_agent.langgraph_final.engine import EngineAPI
from reasoning_agent.langgraph_final.state import GraphState


@dataclass(frozen=True)
class AgentSpec:
    """The public contract of one agent; also the source of the architecture diagram."""

    name: str
    stage: str  # graph node id
    layer: str
    summary: str
    reads: frozenset[str]  # GraphState keys it consumes
    writes: frozenset[str]  # GraphState keys it may produce
    board_writes: frozenset[str] = frozenset()  # Blackboard fields it may change
    model_calls: tuple[str, ...] = ()  # model call types it may issue
    deterministic: bool = False  # True when it never calls the model


@dataclass(frozen=True)
class StageInput:
    """Everything one agent invocation receives."""

    engine: EngineAPI
    state: GraphState
    profile: ProblemProfile | None
    plan: StagedStrategy | None

    @property
    def problem(self) -> str:
        return self.engine.context.problem


class Agent:
    """Base class: subclasses set ``spec`` and implement ``run``."""

    spec: ClassVar[AgentSpec]

    def run(self, inp: StageInput) -> dict[str, Any]:
        raise NotImplementedError

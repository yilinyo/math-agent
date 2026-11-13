"""Typed state shared by the graph, its agents and the checkpoint wire format.

Two kinds of state flow between agents:

* ``GraphState`` -- the top-level, JSON-safe fields that every node reads and
  updates (profile, plan, draft, checks, verification, counters, ...).
* ``Blackboard`` -- the ten engine-side fields that must survive a restart
  (constraint ledger, strategy cards, best candidate, ...). On the wire they
  live under the checkpoint key ``"adapter"`` with the engine's original
  underscore names, so existing checkpoints stay readable.
"""

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_platform.runtime import STAGES
from agent_platform.tools.schemas import Passage
from reasoning_agent.custom2.staged_models import StagedAudit, StagedModelFidelity, StagedStrategy
from reasoning_agent.custom2.text_models import ProblemProfile


WORKFLOW_VERSION = "staged-graph-v5"
GRAPH_STAGES = (*STAGES[:-1], "emergency", "arbitrate", "finalize")
# Nodes that report progress under another stage's public name.
PUBLIC_STAGE = {"emergency": "solve", "arbitrate": "verify"}

# Blackboard field -> key used inside the checkpoint's ``adapter`` section.
BOARD_WIRE = {
    "constraint_ledger": "_constraint_ledger",
    "strategy_retrieval_text": "_strategy_retrieval_text",
    "planner_strategy_cards": "_planner_strategy_cards",
    "solver_strategy_cards": "_solver_strategy_cards",
    "audit_skill_summary": "_audit_skill_summary",
    "persistent_avoidance": "_persistent_avoidance",
    "best_candidate_draft": "_best_candidate_draft",
    "best_candidate_source": "_best_candidate_source",
    "answer_mode": "_answer_mode",
    "response_style": "_response_style",
}
BOARD_KEYS = tuple(BOARD_WIRE.values())


@dataclass
class Blackboard:
    """Engine-side facts that agents hand to each other and checkpoints persist."""

    constraint_ledger: str = ""
    strategy_retrieval_text: str = ""
    planner_strategy_cards: str = ""
    solver_strategy_cards: str = ""
    audit_skill_summary: str = ""
    persistent_avoidance: list[Any] = field(default_factory=list)
    best_candidate_draft: str = ""
    best_candidate_source: str = ""
    answer_mode: str = "other"
    response_style: str | None = None

    @classmethod
    def from_engine(cls, engine: Any) -> "Blackboard":
        return cls(**{name: getattr(engine, wire) for name, wire in BOARD_WIRE.items()})

    def to_wire(self) -> dict[str, Any]:
        return {wire: getattr(self, name) for name, wire in BOARD_WIRE.items()}

    def snapshot(self) -> "Blackboard":
        return copy.deepcopy(self)

    def changed_since(self, earlier: "Blackboard") -> set[str]:
        """Names of fields whose value differs from ``earlier``."""
        return {name for name in BOARD_WIRE if getattr(self, name) != getattr(earlier, name)}


class CandidateCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    draft: str = Field(min_length=1, max_length=48000)
    source: Literal["solve", "repair", "emergency", "final_arbitration"]
    attempt: int = Field(ge=1, le=5)
    audit: StagedAudit | None = None
    checks: dict[str, Any] = Field(default_factory=dict)
    fidelity: StagedModelFidelity | None = None


class GraphState(TypedDict, total=False):
    schema_version: str
    task_id: str
    session_id: str
    problem_hash: str
    config_hash: str
    deadline_at: str
    profile: dict[str, Any]
    plan: dict[str, Any]
    adapter: dict[str, Any]
    draft: str
    checks: dict[str, Any]
    verification: dict[str, Any]
    repair_count: int
    max_repairs: int
    solve_calls_used: int
    max_solve_calls: int
    recoverable_error: str
    next_stage: str
    final_response: str
    response_style: str | None
    evidence: list[dict[str, Any]]
    workflow_started_at: str
    candidates: list[dict[str, Any]]
    convergence_due: bool
    return_due: bool
    recovery_action: str | None
    partial_solution: str
    tool_checks: dict[str, Any]
    partial_recovered: bool


class GraphCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str
    task_id: str
    session_id: str
    problem_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    deadline_at: str
    profile: ProblemProfile | None = None
    plan: StagedStrategy | None = None
    adapter: dict[str, Any]
    draft: str = Field(default="", max_length=48000)
    checks: dict[str, Any] = Field(default_factory=dict)
    verification: StagedAudit | None = None
    repair_count: int = Field(ge=0, le=3)
    max_repairs: int = Field(ge=0, le=3)
    solve_calls_used: int = Field(ge=0, le=8)
    max_solve_calls: int = Field(ge=1, le=8)
    recoverable_error: str
    next_stage: str
    final_response: str = ""
    response_style: Literal["auto", "answer", "brief", "detailed"] | None = None
    evidence: list[Passage] = Field(default_factory=list, max_length=5)
    workflow_started_at: str
    candidates: list[CandidateCheckpoint] = Field(default_factory=list, max_length=6)
    convergence_due: bool = False
    return_due: bool = False
    recovery_action: Literal["local_repair", "proof_completion", "strategy_rethink", "global_restart"] | None = None
    partial_solution: str = Field(default="", max_length=48000)
    tool_checks: dict[str, Any] = Field(default_factory=dict)
    partial_recovered: bool = False

    @field_validator("deadline_at", "workflow_started_at")
    @classmethod
    def valid_deadline(cls, value):
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("timezone_required")
        return value

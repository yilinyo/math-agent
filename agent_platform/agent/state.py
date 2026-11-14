"""Existing staged graph state and checkpoint schemas."""
from typing import Any, Literal, TypedDict
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from agent_platform.runtime import STAGES
from agent_platform.tools.schemas import Passage
from reasoning_agent.custom2.staged_models import StagedAudit, StagedModelFidelity, StagedStrategy
from reasoning_agent.custom2.text_models import ProblemProfile

WORKFLOW_VERSION = "staged-graph-v5"
GRAPH_STAGES = (*STAGES[:-1], "emergency", "arbitrate", "finalize")


class CandidateCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    draft: str = Field(min_length=1, max_length=48000)
    source: Literal["solve", "repair", "emergency", "final_arbitration"]
    attempt: int = Field(ge=1, le=5)
    audit: StagedAudit | None = None
    checks: dict[str, Any] = Field(default_factory=dict)
    fidelity: StagedModelFidelity | None = None


class GraphState(TypedDict, total=False):
    solve_agent_hash: str
    custom_material: str
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

    solve_agent_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    custom_material: str = Field(default="", max_length=12000)

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

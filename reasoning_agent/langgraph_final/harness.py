"""The shell around every agent: cancellation, progress, recovery and checkpoints.

Agents only decide what a stage does. Everything that must behave the same for
all stages lives here, so an agent never has to know about LangGraph, the task
store or the checkpoint format.
"""

import asyncio
import copy
import json
from typing import Any, Callable, Mapping

from reasoning_agent.custom2.staged_models import StagedStrategy
from reasoning_agent.custom2.text_models import ProblemProfile
from agent_platform.runtime import RuntimeContext
from agent_platform.safety import sanitize
from reasoning_agent.langgraph_final.agents.base import Agent, AgentSpec, StageInput
from reasoning_agent.langgraph_final.engine import EngineAPI, ExecutionStopped
from reasoning_agent.langgraph_final.routing import route
from reasoning_agent.langgraph_final.state import PUBLIC_STAGE, GraphState

# Added to every update by the harness, so agents never declare them.
HARNESS_KEYS = frozenset({"candidates", "convergence_due", "return_due", "adapter"})


class ContractViolation(AssertionError):
    """An agent read, wrote or changed something its ``AgentSpec`` does not declare."""


class TrackedState(dict):
    """A state copy that remembers which keys the agent looked at."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        super().__init__(data)
        self.touched: set[str] = set()

    def __getitem__(self, key):
        self.touched.add(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.touched.add(key)
        return super().get(key, default)

    def __contains__(self, key):
        self.touched.add(key)
        return super().__contains__(key)


def check_contract(spec: AgentSpec, *, reads: set[str], update: Mapping[str, Any],
                   board_changes: set[str]) -> None:
    problems = []
    if reads - spec.reads:
        problems.append(f"reads undeclared state {sorted(reads - spec.reads)}")
    if set(update) - spec.writes:
        problems.append(f"writes undeclared state {sorted(set(update) - spec.writes)}")
    if board_changes - spec.board_writes:
        problems.append(f"changes undeclared blackboard fields {sorted(board_changes - spec.board_writes)}")
    if problems:
        raise ContractViolation(f"{spec.name}: " + "; ".join(problems))


def run_stage(agent: Agent, engine: EngineAPI, state: GraphState, *, enforce_contracts: bool = False) -> dict[str, Any]:
    """Run one agent against one engine. Executes in a worker thread."""
    profile = ProblemProfile.model_validate(state["profile"]) if state.get("profile") else None
    plan = StagedStrategy.model_validate(state["plan"]) if state.get("plan") else None
    view = TrackedState(state) if enforce_contracts else state
    before = engine.blackboard().snapshot() if enforce_contracts else None
    update = agent.run(StageInput(engine, view, profile, plan))
    if enforce_contracts:
        check_contract(agent.spec, reads=view.touched, update=update,
                       board_changes=engine.blackboard().changed_since(before))
    update["candidates"] = engine.candidates
    update["convergence_due"] = engine._convergence_due()
    update["return_due"] = engine._best_candidate_return_due()
    update["adapter"] = engine.export()
    return update


class NodeHarness:
    """Builds the LangGraph node for each stage of one task run."""

    def __init__(self, *, client: Any, config: Any, permits: Any, engine_factory: Callable[..., EngineAPI],
                 context: RuntimeContext, agents: Mapping[str, Agent],
                 budget_available: Callable[[], bool], enforce_contracts: bool = False) -> None:
        self.client, self.config, self.permits = client, config, permits
        self.engine_factory, self.context, self.agents = engine_factory, context, agents
        self.budget_available = budget_available
        self.enforce_contracts = enforce_contracts

    def node(self, stage: str):
        context, agent = self.context, self.agents[stage]

        async def execute(current: GraphState) -> GraphState:
            if context.cancelled.is_set():
                raise asyncio.CancelledError
            public_stage = PUBLIC_STAGE.get(stage, stage)
            context.progress(public_stage)
            engine = self.engine_factory(self.client, self.config, context, stage, self.permits, current)
            try:
                updates = await asyncio.to_thread(
                    run_stage, agent, engine, copy.deepcopy(current), enforce_contracts=self.enforce_contracts)
            except ExecutionStopped:
                raise asyncio.CancelledError from None
            except ContractViolation:
                raise
            except Exception:
                # Store/lease errors must escape; recording also fences the owner.
                context.record(public_stage, "stage.recovered_error", {"error_code": "stage_failed"})
                if stage == "finalize":
                    raise
                if not current.get("adapter", {}).get("_best_candidate_draft"):
                    raise
                updates = {"recoverable_error": "stage_failed", "next_stage": "finalize"}
            updated = {**current, **updates}
            updated["solve_calls_used"] = context.solver_calls_used
            updated["next_stage"] = (
                "finalize" if updates.get("next_stage") == "finalize"
                else route(stage, updated, budget_available=self.budget_available())
            )
            updated = sanitize(updated)
            json.dumps(updated, allow_nan=False)
            context.progress(public_stage, completed=True, checkpoint=updated)
            context.checkpoint = updated
            if updated.get("adapter", {}).get("_best_candidate_draft"):
                context.saved_response = engine.safe_response()
            return updated

        return execute

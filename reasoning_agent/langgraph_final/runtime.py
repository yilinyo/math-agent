"""LangGraph orchestration of the staged math workflow, with atomic checkpoints.

The graph has one node per agent (see ``agents``). This module only wires
things together: it validates and restores checkpoints, builds the graph from
the agent registry and the routing table, and runs it. Stage logic lives in
the agents, shared plumbing in the harness, and reasoning in the engine.
"""

import asyncio
import copy
import hashlib
import json
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from langgraph.errors import NodeCancelledError
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from agent_platform.presentation import RESOLVED_STYLES, requested_style
from agent_platform.runtime import CheckpointIncompatible, ModelPermits, RuntimeContext, RuntimeResult
from agent_platform.tools.registry import ToolRegistry
from reasoning_agent.custom.config import AgentConfig
from reasoning_agent.langgraph_final.agents import AGENT_BY_STAGE
from reasoning_agent.langgraph_final.engine import StageEngine
from reasoning_agent.langgraph_final.harness import NodeHarness
from reasoning_agent.langgraph_final.state import (
    GRAPH_STAGES, WORKFLOW_VERSION, GraphCheckpoint, GraphState,
)

# Source trees whose contents decide whether a stored checkpoint is still valid.
# ``langgraph_final`` hashes itself, so editing an agent invalidates old checkpoints.
HASHED_SOURCE_DIRS = (
    "agent_platform", "reasoning_agent/custom2", "reasoning_agent/custom", "reasoning_agent/langgraph_final",
)


class LangGraphRuntime:
    name = "langgraph_staged"

    def __init__(self, client: Any, config: AgentConfig | None = None,
                 *, model_concurrency: int = 8, client_identity: str | None = None,
                 engine_factory=StageEngine, tools: ToolRegistry | None = None,
                 function_calling: str = "auto", enforce_contracts: bool = False) -> None:
        if client is None or not callable(getattr(client, "chat", None)):
            raise ValueError("injected_client_required")
        if model_concurrency < 1:
            raise ValueError("invalid_model_concurrency")
        self.client = client
        self.config = copy.deepcopy(config or AgentConfig(custom2_solver_protocol="staged"))
        self.permits: ModelPermits = threading.BoundedSemaphore(model_concurrency)
        self.engine_factory = engine_factory
        if function_calling not in {"auto", "native", "json", "off"}:
            raise ValueError("invalid_function_calling_mode")
        self.tools = tools or ToolRegistry()
        self.function_calling = function_calling
        # Test-time switch: raise ContractViolation when an agent steps outside its AgentSpec.
        self.enforce_contracts = enforce_contracts
        # Refuse incompatible code/prompt/config checkpoints instead of guessing.
        source_root = Path(__file__).resolve().parents[2]
        digest = hashlib.sha256(json.dumps(asdict(self.config), sort_keys=True).encode())
        identity = client_identity or f"{type(client).__module__}.{type(client).__qualname__}"
        digest.update(identity.encode())
        digest.update(f"{self.tools.identity}:{function_calling}".encode())
        for folder in HASHED_SOURCE_DIRS:
            for path in sorted((source_root / folder).rglob("*.py")):
                digest.update(path.relative_to(source_root).as_posix().encode())
                digest.update(path.read_bytes())
        for relative in ("reasoning_agent/action_graph/strategy_cards.py", "reasoning_agent/strategy_retrieval.py",
                         "reasoning_agent/lexical_strategy_retrieval.py", "reasoning_agent/hybrid_strategy_retrieval.py",
                         "strategy_data/strategy_lexical_manifest.json", "strategy_data/strategy_index.json"):
            path = source_root / relative
            digest.update(relative.encode())
            digest.update(path.read_bytes() if path.is_file() else b"missing")
        for folder in ("skill2_en", "skill2"):
            for path in sorted((source_root / folder).glob("*.md")):
                digest.update(path.relative_to(source_root).as_posix().encode())
                digest.update(path.read_bytes())
        self.config_hash = digest.hexdigest()

    def checkpoint_compatible(self, checkpoint: dict | None) -> bool:
        if checkpoint is None:
            return True
        try:
            parsed = GraphCheckpoint.model_validate(checkpoint)
        except ValidationError:
            return False
        effective = parsed.adapter.get("_response_style")
        if parsed.response_style == "auto":
            if not isinstance(effective, str) or effective not in RESOLVED_STYLES:
                return False
        elif effective != parsed.response_style:
            return False
        if parsed.next_stage in {*GRAPH_STAGES, "terminal"} - {"profile", "finalize", "terminal"} and parsed.profile is None:
            return False
        if parsed.next_stage in {"solve", "tool", "verify", "repair", "emergency", "arbitrate"} and parsed.plan is None:
            return False
        if parsed.next_stage in {"tool", "verify", "repair"} and not parsed.draft:
            return False
        if parsed.next_stage == "verify" and not isinstance(parsed.checks.get("ok"), bool):
            return False
        if parsed.next_stage == "repair" and parsed.verification is None:
            return False
        if parsed.next_stage == "arbitrate" and not parsed.candidates:
            return False
        if parsed.next_stage == "terminal" and not parsed.final_response.strip():
            return False
        return (parsed.schema_version == WORKFLOW_VERSION
                and parsed.config_hash == self.config_hash
                and parsed.next_stage in {*GRAPH_STAGES, "terminal"}
                and parsed.repair_count <= parsed.max_repairs
                and parsed.solve_calls_used <= parsed.max_solve_calls)

    def _load(self, context: RuntimeContext) -> GraphState:
        if not context.deadline_at:
            context.deadline_at = datetime.now(timezone.utc) + timedelta(seconds=1200)
        problem_hash = hashlib.sha256(context.problem.encode()).hexdigest()
        if context.checkpoint is not None:
            state = copy.deepcopy(context.checkpoint)
            if (not self.checkpoint_compatible(state)
                    or state.get("task_id") != context.task_id
                    or state.get("session_id") != context.session_id
                    or state.get("problem_hash") != problem_hash
                    or state.get("response_style") != requested_style(context.metadata)
                    or state.get("deadline_at") != context.deadline_at.isoformat()):
                raise CheckpointIncompatible("checkpoint_incompatible")
            return state
        max_repairs = min(3, max(0, int(self.config.custom2_max_repairs)))
        solve_multiplier = 2 if self.config.staged_solver_compressed_retry_enabled else 1
        return {
            "schema_version": WORKFLOW_VERSION, "task_id": context.task_id,
            "session_id": context.session_id, "problem_hash": problem_hash,
            "config_hash": self.config_hash, "deadline_at": context.deadline_at.isoformat(),
            "repair_count": 0, "max_repairs": max_repairs, "solve_calls_used": 0,
            "max_solve_calls": (max_repairs + 1) * solve_multiplier, "next_stage": "profile",
            "adapter": {}, "recoverable_error": "",
            "response_style": requested_style(context.metadata),
            "workflow_started_at": datetime.now(timezone.utc).isoformat(), "candidates": [],
            "convergence_due": False, "return_due": False, "recovery_action": None, "partial_solution": "",
        }

    def _budget_available(self, context):
        return (context.deadline_at - datetime.now(timezone.utc)).total_seconds() > context.finalize_reserve_seconds

    def build_graph(self, context: RuntimeContext) -> StateGraph:
        """One node per agent; edges follow ``routing.route`` through each state's ``next_stage``."""
        harness = NodeHarness(
            client=self.client, config=self.config, permits=self.permits,
            engine_factory=self.engine_factory, context=context, agents=AGENT_BY_STAGE,
            budget_available=lambda: self._budget_available(context),
            enforce_contracts=self.enforce_contracts,
        )
        graph = StateGraph(GraphState)
        for stage in GRAPH_STAGES:
            graph.add_node(stage, harness.node(stage))
            graph.add_conditional_edges(stage, lambda value: value["next_stage"],
                                        {**{name: name for name in GRAPH_STAGES}, "terminal": END})
        graph.add_conditional_edges(START, lambda value: (
            value["next_stage"] if self._budget_available(context) else "finalize"
        ), {stage: stage for stage in GRAPH_STAGES})
        return graph

    async def run(self, context: RuntimeContext) -> RuntimeResult:
        if context.finalize_reserve_seconds < 25:
            raise ValueError("graph_requires_finalize_reserve")
        state = self._load(context)
        context.tools = self.tools
        context.function_calling = self.function_calling
        context.max_solve_calls = state["max_solve_calls"]
        context.solver_calls_used = max(context.solver_calls_used, state["solve_calls_used"])
        state["solve_calls_used"] = context.solver_calls_used
        if state.get("adapter", {}).get("_best_candidate_draft"):
            engine = self.engine_factory(self.client, self.config, context, "finalize", self.permits, state)
            response = engine.safe_response()
            if response:
                context.save_response(response)
        if state["next_stage"] == "terminal":
            return RuntimeResult(state["final_response"])
        graph = self.build_graph(context)
        try:
            output = await graph.compile().ainvoke(state, {"recursion_limit": 40})
            return RuntimeResult(output["final_response"])
        except NodeCancelledError:
            raise asyncio.CancelledError from None
        finally:
            context.cancelled.set()

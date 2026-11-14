"""Platform runtime adapter for the existing reasoning graph."""
import asyncio
import copy
import threading
import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from langgraph.errors import NodeCancelledError
from agent_platform.runtime import ModelPermits, RuntimeContext, RuntimeResult
from agent_platform.observability import graph_tracing
from agent_platform.tools.registry import ToolRegistry
from reasoning_agent.custom.config import AgentConfig
from agent_platform.agent.stage_engine import StagedAdapter
from agent_platform.agent.checkpoint import CheckpointRuntime
from agent_platform.agent.checkpoint_identity import config_hash
from agent_platform.agent.graph import build_graph
from agent_platform.agent.routing import route
from agent_platform.agent.state import CandidateCheckpoint, GRAPH_STAGES, WORKFLOW_VERSION, GraphCheckpoint, GraphState

__all__ = [
    "LangGraphRuntime", "route", "CandidateCheckpoint", "GRAPH_STAGES", "WORKFLOW_VERSION",
    "GraphCheckpoint", "GraphState",
]


class LangGraphRuntime(CheckpointRuntime):
    name = "langgraph_staged"

    def __init__(self, client: Any, config: AgentConfig | None = None,
                 *, model_concurrency: int = 8, client_identity: str | None = None,
                 adapter_factory=StagedAdapter, tools: ToolRegistry | None = None,
                 function_calling: str = "auto", library=None,
                 solve_client_factory=None, solve_router_factory=None) -> None:
        if client is None or not callable(getattr(client, "chat", None)):
            raise ValueError("injected_client_required")
        if model_concurrency < 1:
            raise ValueError("invalid_model_concurrency")
        self.client = client
        self.library = library
        self.solve_client_factory = solve_client_factory
        self.solve_router_factory = solve_router_factory
        self.config = copy.deepcopy(config or AgentConfig(custom2_solver_protocol="staged"))
        self.permits: ModelPermits = threading.BoundedSemaphore(model_concurrency)
        self.adapter_factory = adapter_factory
        if function_calling not in {"auto", "native", "json", "off"}:
            raise ValueError("invalid_function_calling_mode")
        self.tools = tools or ToolRegistry()
        self.function_calling = function_calling
        self.config_hash = config_hash(self.config, client, client_identity, self.tools, function_calling)
        self.base_config_hash = self.config_hash

    def _solver_config_hash(self, digest):
        return hashlib.sha256((self.base_config_hash + ":solve-agent-v1:" + digest).encode()).hexdigest()

    def checkpoint_compatible(self, checkpoint):
        digest = checkpoint.get("solve_agent_hash") if isinstance(checkpoint, dict) else None
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            return False
        runtime = copy.copy(self)
        runtime.config_hash = self._solver_config_hash(digest) if digest else self.base_config_hash
        return CheckpointRuntime.checkpoint_compatible(runtime, checkpoint)

    def _budget_available(self, context):
        return (context.deadline_at - datetime.now(timezone.utc)).total_seconds() > context.finalize_reserve_seconds

    async def run(self, context: RuntimeContext) -> RuntimeResult:
        from agent_platform.solve_agents import SNAPSHOT_KEY, snapshot_hash
        from agent_platform.runtime import CheckpointIncompatible

        snapshot = context.metadata.get(SNAPSHOT_KEY)
        digest = snapshot_hash(snapshot) if snapshot else None
        if context.checkpoint is not None and context.checkpoint.get("solve_agent_hash") != digest:
            raise CheckpointIncompatible("checkpoint_incompatible")
        runtime = copy.copy(self)
        if snapshot:
            if not self.solve_router_factory or not self.solve_client_factory:
                raise ValueError("solve_agent_factory_required")
            solver = self.solve_client_factory(snapshot) if snapshot.get("config") else self.client
            runtime.client = self.solve_router_factory(self.client, solver, snapshot)
            runtime.config_hash = self._solver_config_hash(digest)
        return await runtime._run(context, digest)

    async def _run(self, context: RuntimeContext, digest=None) -> RuntimeResult:
        if context.finalize_reserve_seconds < 25:
            raise ValueError("graph_requires_finalize_reserve")
        state = self._load(context)
        if digest:
            state["solve_agent_hash"] = digest
        if context.checkpoint is None and self.library is not None:
            state["custom_material"] = await asyncio.to_thread(self.library.select, context.problem)
        context.tools = self.tools
        context.function_calling = self.function_calling
        context.max_solve_calls = state["max_solve_calls"]
        context.solver_calls_used = max(context.solver_calls_used, state["solve_calls_used"])
        state["solve_calls_used"] = context.solver_calls_used
        if state.get("adapter", {}).get("_best_candidate_draft"):
            adapter = self.adapter_factory(self.client, self.config, context, "finalize", self.permits, state)
            response = adapter.safe_response()
            if response:
                context.save_response(response)
        if state["next_stage"] == "terminal":
            return RuntimeResult(state["final_response"])
        graph = build_graph(self, context)
        try:
            with graph_tracing(context.task_id) as tracing_config:
                output = await graph.compile().ainvoke(state, {"recursion_limit": 40, **tracing_config})
            return RuntimeResult(output["final_response"])
        except NodeCancelledError:
            raise asyncio.CancelledError from None
        finally:
            context.cancelled.set()

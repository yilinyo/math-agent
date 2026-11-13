"""The ten agents of the final graph, one per node, grouped into four layers.

    理解层  Profiler -> Retriever -> Planner
    求解层  Solver / Repairer / EmergencySolver
    校验层  Checker -> Verifier ; Arbiter
    输出层  Finalizer
"""

from reasoning_agent.langgraph_final.agents.base import Agent, AgentSpec, StageInput
from reasoning_agent.langgraph_final.agents.output import Finalizer
from reasoning_agent.langgraph_final.agents.solving import EmergencySolver, Repairer, Solver
from reasoning_agent.langgraph_final.agents.understanding import Planner, Profiler, Retriever
from reasoning_agent.langgraph_final.agents.verification import Arbiter, Checker, Verifier
from reasoning_agent.langgraph_final.state import GRAPH_STAGES

LAYERS = ("理解层", "求解层", "校验层", "输出层")

AGENTS: tuple[Agent, ...] = (
    Profiler(), Retriever(), Planner(),
    Solver(), Repairer(), EmergencySolver(),
    Checker(), Verifier(), Arbiter(),
    Finalizer(),
)
AGENT_BY_STAGE: dict[str, Agent] = {agent.spec.stage: agent for agent in AGENTS}

# The graph and its agents must stay one-to-one; fail at import rather than at run time.
if set(AGENT_BY_STAGE) != set(GRAPH_STAGES) or len(AGENT_BY_STAGE) != len(AGENTS):
    raise RuntimeError("agents_do_not_match_graph_stages")
if {agent.spec.layer for agent in AGENTS} - set(LAYERS):
    raise RuntimeError("agent_layer_unknown")

__all__ = ["AGENTS", "AGENT_BY_STAGE", "LAYERS", "Agent", "AgentSpec", "StageInput"]

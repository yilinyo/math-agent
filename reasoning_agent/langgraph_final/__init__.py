"""Final LangGraph runtime for the math reasoning application.

    from reasoning_agent.langgraph_final import LangGraphRuntime

Layout: ``agents`` (one agent per graph node), ``routing`` (where the graph
goes next), ``harness`` (cancellation, progress, recovery, checkpoints),
``engine`` (the reasoning engine built on ``custom2``), ``state`` (typed shared
state and the checkpoint format). ``python -m reasoning_agent.langgraph_final``
prints the architecture diagram generated from the agent registry.
"""

from reasoning_agent.langgraph_final.runtime import LangGraphRuntime

__all__ = ["LangGraphRuntime"]

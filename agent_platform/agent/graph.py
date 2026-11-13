"""The existing staged workflow: nodes, conditional edges and compilation."""
from langgraph.graph import END, START, StateGraph
from agent_platform.agent.execution import node
from agent_platform.agent.state import GRAPH_STAGES, GraphState


def build_graph(runtime, context):
    graph = StateGraph(GraphState)
    graph.add_node("profile", node("profile", runtime=runtime, context=context))
    graph.add_node("retrieve", node("retrieve", runtime=runtime, context=context))
    graph.add_node("plan", node("plan", runtime=runtime, context=context))
    graph.add_node("solve", node("solve", runtime=runtime, context=context))
    graph.add_node("tool", node("tool", runtime=runtime, context=context))
    graph.add_node("verify", node("verify", runtime=runtime, context=context))
    graph.add_node("repair", node("repair", runtime=runtime, context=context))
    graph.add_node("emergency", node("emergency", runtime=runtime, context=context))
    graph.add_node("arbitrate", node("arbitrate", runtime=runtime, context=context))
    graph.add_node("finalize", node("finalize", runtime=runtime, context=context))

    for stage in GRAPH_STAGES:
        graph.add_conditional_edges(stage, lambda value: value["next_stage"],
                                    {**{name: name for name in GRAPH_STAGES}, "terminal": END})
    graph.add_conditional_edges(START, lambda value: (
        value["next_stage"] if runtime._budget_available(context) else "finalize"
    ), {stage: stage for stage in GRAPH_STAGES})
    return graph

"""Architecture tests for ``langgraph_final``: contracts, routing table, engine API, hashing."""

import asyncio
import copy
import hashlib
import inspect
import json

import pytest

pytest.importorskip("langgraph")

from reasoning_agent.langgraph_final import LangGraphRuntime
from reasoning_agent.langgraph_final.agents import AGENT_BY_STAGE, AGENTS, LAYERS
from reasoning_agent.langgraph_final.engine import ENGINE_API_NAMES, StageEngine
from reasoning_agent.langgraph_final.harness import (
    ContractViolation, check_contract, run_stage,
)
from reasoning_agent.langgraph_final.routing import TRANSITIONS, route
from reasoning_agent.langgraph_final.state import (
    BOARD_KEYS, BOARD_WIRE, GRAPH_STAGES, Blackboard, GraphState,
)

import test_langgraph_final_golden as golden


# --- agents ----------------------------------------------------------------------------------


def test_one_agent_per_graph_stage():
    assert [agent.spec.stage for agent in AGENTS] and set(AGENT_BY_STAGE) == set(GRAPH_STAGES)
    assert len(AGENTS) == len(GRAPH_STAGES) == 10
    assert {agent.spec.layer for agent in AGENTS} <= set(LAYERS)


def test_specs_only_name_real_state_keys():
    state_keys = set(GraphState.__annotations__)
    for agent in AGENTS:
        spec = agent.spec
        assert spec.reads <= state_keys, spec.name
        assert spec.writes <= state_keys, spec.name
        assert spec.board_writes <= set(BOARD_WIRE), spec.name
        assert spec.summary and spec.name


def test_deterministic_agents_declare_no_model_calls():
    for agent in AGENTS:
        if agent.spec.deterministic:
            assert not agent.spec.model_calls, agent.spec.name


@pytest.mark.parametrize("scenario", sorted(golden.SCENARIOS))
def test_every_scenario_respects_declared_contracts(scenario):
    """Run each golden scenario with contract enforcement on; any undeclared read, write or
    blackboard change raises ``ContractViolation`` and fails the scenario."""
    flavor = golden.Flavor("final-strict", _StrictRuntime, StageEngine)
    observed = golden.SCENARIOS[scenario](flavor)
    assert observed["outcome"][0] in {"ok", "error"}
    assert observed["outcome"] != ("error", "ContractViolation"), observed["outcome"]


class _StrictRuntime(LangGraphRuntime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **{**kwargs, "enforce_contracts": True})


def test_contract_check_catches_each_kind_of_violation():
    spec = AGENT_BY_STAGE["plan"].spec
    check_contract(spec, reads=set(spec.reads), update={"plan": {}}, board_changes=set())
    with pytest.raises(ContractViolation, match="reads undeclared"):
        check_contract(spec, reads={"draft"}, update={}, board_changes=set())
    with pytest.raises(ContractViolation, match="writes undeclared"):
        check_contract(spec, reads=set(), update={"draft": "x"}, board_changes=set())
    with pytest.raises(ContractViolation, match="blackboard"):
        check_contract(spec, reads=set(), update={}, board_changes={"best_candidate_draft"})


# --- routing ---------------------------------------------------------------------------------


def _states_for(stage):
    base = {"draft": "d", "repair_count": 0, "max_repairs": 3, "solve_calls_used": 1, "max_solve_calls": 8,
            "recoverable_error": "", "convergence_due": False, "return_due": False, "partial_recovered": False}
    yield {**base}
    yield {**base, "draft": ""}
    yield {**base, "convergence_due": True}
    yield {**base, "partial_recovered": True}
    yield {**base, "recoverable_error": "x"}
    for verdict in ("pass", "uncertain", "fail"):
        for evidence in ("", "defect"):
            for repairs in (0, 3):
                yield {**base, "verification": {"verdict": verdict, "first_fatal_error": evidence},
                       "repair_count": repairs}
    yield {**base, "verification": {"verdict": "fail", "first_fatal_error": "defect"}, "return_due": True}
    yield {**base, "verification": {"verdict": "fail", "first_fatal_error": "defect"},
           "solve_calls_used": 8}


def test_routing_table_documents_every_reachable_edge():
    seen = {stage: set() for stage in GRAPH_STAGES}
    for stage in GRAPH_STAGES:
        for state in _states_for(stage):
            for budget in (True, False):
                try:
                    seen[stage].add(route(stage, state, budget_available=budget))
                except KeyError:
                    pass  # state not meaningful for this stage (e.g. no verification yet)
    for stage, targets in seen.items():
        assert targets <= set(TRANSITIONS[stage]), (stage, targets - set(TRANSITIONS[stage]))
    # every target the table promises is actually reachable
    for stage, targets in TRANSITIONS.items():
        assert set(targets) <= seen[stage] | {"finalize"}, (stage, set(targets) - seen[stage])


def test_every_stage_can_reach_the_end():
    reach, frontier = {"terminal"}, ["terminal"]
    while frontier:
        node = frontier.pop()
        for stage, targets in TRANSITIONS.items():
            if node in targets and stage not in reach:
                reach.add(stage)
                frontier.append(stage)
    assert set(GRAPH_STAGES) <= reach


# --- engine API ------------------------------------------------------------------------------


def test_stage_engine_provides_every_name_in_the_engine_api():
    missing = [name for name in ENGINE_API_NAMES if not hasattr(StageEngine, name)
               and name not in _INSTANCE_ATTRIBUTES]
    assert not missing, missing


# Declared in the Protocol but only assigned in __init__ of the shared runtime.
_INSTANCE_ATTRIBUTES = {
    "context", "stage", "node", "candidates", "evidence", "_answer_mode", "_best_candidate_draft",
    "_best_candidate_source", "_candidate_reviews", "_strategy_results", "_solver_strategy_cards",
    "_last_solver_partial",
}


def test_agents_only_use_the_declared_engine_surface():
    """Agents may touch ``engine.<name>`` only for names the EngineAPI promises."""
    import ast
    import pathlib
    import reasoning_agent.langgraph_final.agents as package
    allowed = set(ENGINE_API_NAMES) | {"stage", "context"}
    offenders = []
    for path in pathlib.Path(package.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "engine" and node.attr not in allowed):
                offenders.append(f"{path.name}:{node.lineno} engine.{node.attr}")
    assert not offenders, offenders


# --- blackboard / checkpoint wire format -----------------------------------------------------


def test_blackboard_wire_keys_are_the_original_engine_names():
    assert set(BOARD_KEYS) == {
        "_constraint_ledger", "_strategy_retrieval_text", "_planner_strategy_cards",
        "_solver_strategy_cards", "_audit_skill_summary", "_persistent_avoidance",
        "_best_candidate_draft", "_best_candidate_source", "_answer_mode", "_response_style",
    }


def test_blackboard_roundtrip_and_change_detection():
    board = Blackboard(constraint_ledger="L", answer_mode="proof", response_style="brief",
                       persistent_avoidance=["a"])
    wire = board.to_wire()
    assert set(wire) == set(BOARD_KEYS) and wire["_answer_mode"] == "proof"
    snapshot = board.snapshot()
    board.persistent_avoidance.append("b")
    assert board.changed_since(snapshot) == {"persistent_avoidance"}
    assert snapshot.persistent_avoidance == ["a"], "snapshot must be a deep copy"


def test_checkpoint_adapter_section_matches_blackboard():
    observed = golden.scenario_pass_first_try(golden.FLAVORS[1])
    adapter = observed["final_checkpoint"]["adapter"]
    assert set(adapter) == set(BOARD_KEYS)
    json.dumps(observed["final_checkpoint"], allow_nan=False)


# --- checkpoint compatibility and hashing ----------------------------------------------------


def _runtime(**kwargs):
    return LangGraphRuntime(golden.ScriptedClient([]), golden.config(), function_calling="off", **kwargs)


def test_checkpoints_are_compatible_across_old_and_new_runtime():
    """A checkpoint written by the platform runtime resumes in the final runtime's format check
    except for the (intentionally different) source hash."""
    platform = golden.observe(golden.FLAVORS[0], golden.passing())
    saved = copy.deepcopy(platform["_raw_checkpoints"][-1])
    final = _runtime()
    assert not final.checkpoint_compatible(saved)  # hash differs: langgraph_final hashes its own sources
    saved["config_hash"] = final.config_hash
    assert final.checkpoint_compatible(saved)


def test_config_hash_covers_langgraph_final_sources():
    from reasoning_agent.langgraph_final import runtime as module
    assert "reasoning_agent/langgraph_final" in module.HASHED_SOURCE_DIRS
    # and the hash really changes when the file set it walks changes
    original = _runtime().config_hash
    module.HASHED_SOURCE_DIRS = module.HASHED_SOURCE_DIRS[:-1]
    try:
        assert _runtime().config_hash != original
    finally:
        module.HASHED_SOURCE_DIRS = (*module.HASHED_SOURCE_DIRS, "reasoning_agent/langgraph_final")


def test_workflow_version_unchanged():
    from reasoning_agent.langgraph_final.state import WORKFLOW_VERSION
    assert WORKFLOW_VERSION == "staged-graph-v5"

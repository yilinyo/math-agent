"""Compare extracted code with the frozen pre-migration implementation."""

import ast
import copy
import hashlib
import importlib
import json
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import _structure_scenarios as scenarios
from agent_platform.reasoning_runtime import LangGraphRuntime
from agent_platform.agent import checkpoint, checkpoint_identity, execution, stage_engine
from agent_platform.agent.state import GraphCheckpoint, GraphState


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = json.loads((ROOT / "agent_platform/agent/_compat/source_snapshot.json").read_text())


def frozen_module(name, path):
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / path)
    sys.modules[name] = module
    exec(compile(SNAPSHOT[path], module.__file__, "exec"), module.__dict__)
    return module


BASE_ENGINE = frozen_module("_structure_baseline_engine", "agent_platform/staged_adapter.py")
with patch.dict(sys.modules, {"agent_platform.staged_adapter": BASE_ENGINE}):
    BASE_GRAPH = frozen_module("_structure_baseline_graph", "agent_platform/graph_runtime.py")


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 12, tzinfo=timezone.utc)
        return value if tz is not None else value.replace(tzinfo=None)


@contextmanager
def controlled_runtime():
    from contextlib import ExitStack
    from agent_platform.tools import registry

    with ExitStack() as stack:
        # A constant monotonic clock makes request budgets and tool timings comparable.
        stack.enter_context(patch("time.monotonic", return_value=1000.0))
        for module in (BASE_ENGINE, BASE_GRAPH, checkpoint, stage_engine, registry,
                       importlib.import_module("agent_platform.reasoning_runtime")):
            stack.enter_context(patch.object(module, "datetime", FixedDateTime))
        yield


class BaselineRuntime(BASE_GRAPH.LangGraphRuntime):
    def __init__(self, *args, **kwargs):
        # Run the unmodified old hash loop against its pre-migration source paths.
        with patch.object(BASE_GRAPH, "Path", OriginalSourcePath):
            super().__init__(*args, **kwargs)


class OriginalSourcePath:
    def __init__(self, path):
        self.path = Path(path)

    def resolve(self):
        return OriginalSourcePath(self.path.resolve())

    @property
    def parent(self):
        return OriginalSourcePath(self.path.parent)

    def __truediv__(self, value):
        return OriginalSourcePath(self.path / value)

    def __lt__(self, other):
        return self.path < other.path

    def relative_to(self, other):
        return self.path.relative_to(other.path)

    def read_bytes(self):
        relative = self.path.relative_to(ROOT).as_posix()
        return SNAPSHOT[relative].encode() if relative in SNAPSHOT else self.path.read_bytes()

    def is_file(self):
        return self.path.is_file()

    def rglob(self, pattern):
        assert pattern == "*.py"
        relative = self.path.relative_to(ROOT).as_posix() + "/"
        sources = checkpoint_identity.logical_sources(ROOT)
        return [OriginalSourcePath(ROOT / name) for name in sources if name.startswith(relative)]

    def glob(self, pattern):
        return [OriginalSourcePath(path) for path in self.path.glob(pattern)]


BASE = scenarios.Flavor("baseline", BaselineRuntime, BASE_ENGINE.StagedAdapter)
NEW = scenarios.Flavor("extracted", LangGraphRuntime, stage_engine.StagedAdapter)


def observe_pair(scenario):
    deadline = FixedDateTime.now(timezone.utc) + timedelta(seconds=1200)
    # Scenarios use utc_now only to choose the task deadline; keep this binding fixed too.
    with controlled_runtime(), patch.object(scenarios, "utc_now", lambda: deadline - timedelta(seconds=1200)):
        before = scenario(BASE)
        after = scenario(NEW)
    return before, after


@pytest.mark.parametrize("name", list(scenarios.SCENARIOS))
def test_frozen_scenario_equivalence(name):
    before, after = observe_pair(scenarios.SCENARIOS[name])
    assert scenarios.public(before) == scenarios.public(after)


@pytest.mark.parametrize("repairs", [1, 2, 3])
def test_full_repair_budget_equivalence(repairs):
    def scenario(flavor):
        reviews = [scenarios.StagedAudit(verdict="fail", first_fatal_error="quoted defect")
                   for _ in range(repairs)] + [scenarios.StagedAudit(verdict="pass")]
        return scenarios.observe(
            flavor, ['{}', '{"risk_level":"high"}', *[scenarios.draft(str(i + 2)) for i in range(repairs + 1)]],
            cfg={"custom2_max_repairs": repairs}, patches=scenarios._repair_patches(reviews))
    before, after = observe_pair(scenario)
    assert scenarios.public(before) == scenarios.public(after)
    assert after["final_checkpoint"]["repair_count"] == repairs


def test_old_checkpoint_restores_at_every_completed_stage():
    before, after = observe_pair(scenarios.scenario_pass_first_try)
    for state, remaining in zip(before["_raw_checkpoints"], [4, 4, 3, 2, 2, 0, 0]):
        def scenario(flavor):
            return scenarios.observe(flavor, scenarios.passing()[5 - remaining:] if remaining else [],
                                     checkpoint=copy.deepcopy(state), deadline=before["_deadline"])
        old, new = observe_pair(scenario)
        assert scenarios.public(old) == scenarios.public(new)
        assert len(new["calls"]) == remaining


def test_original_state_schema_and_route_are_unchanged():
    assert GraphState.__annotations__ == BASE_GRAPH.GraphState.__annotations__
    assert GraphCheckpoint.model_json_schema() == BASE_GRAPH.GraphCheckpoint.model_json_schema()
    original = ast.parse(SNAPSHOT["agent_platform/graph_runtime.py"])
    current = ast.parse((ROOT / "agent_platform/agent/routing.py").read_text())
    old_route = next(n for n in original.body if getattr(n, "name", None) == "route")
    new_route = next(n for n in current.body if getattr(n, "name", None) == "route")
    assert ast.dump(old_route) == ast.dump(new_route)


def test_old_imports_and_patch_target_share_the_new_implementation():
    assert importlib.import_module("agent_platform.staged_adapter") is stage_engine
    assert importlib.import_module("agent_platform.graph_runtime").LangGraphRuntime is LangGraphRuntime
    with patch("agent_platform.staged_adapter.theorem_cards", return_value="patched"):
        assert stage_engine.theorem_cards([]) == "patched"


def test_legacy_hash_algorithm_matches_exactly():
    # Run the original hash loop against a virtual Path exposing the frozen logical sources.
    sources = checkpoint_identity.logical_sources(ROOT)
    for path, source in SNAPSHOT.items():
        assert sources[path] == source.encode()
    manifest = json.loads((ROOT / "agent_platform/agent/_compat/migration.json").read_text())
    assert not set(manifest["new_paths"]) & set(sources)
    cfg = scenarios.config()
    client = scenarios.ScriptedClient([])
    tools = scenarios.ToolRegistry()
    from dataclasses import asdict
    digest = hashlib.sha256(json.dumps(asdict(cfg), sort_keys=True).encode())
    digest.update(f"{type(client).__module__}.{type(client).__qualname__}".encode())
    digest.update(f"{tools.identity}:off".encode())
    for folder in checkpoint_identity.LEGACY_DIRS:
        for path in sorted(p for p in sources if p.startswith(folder + "/")):
            digest.update(path.encode())
            digest.update(sources[path])
    for relative in checkpoint_identity.RESOURCE_FILES:
        path = ROOT / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes() if path.is_file() else b"missing")
    for folder in ("skill2_en", "skill2"):
        for path in sorted((ROOT / folder).glob("*.md")):
            digest.update(path.relative_to(ROOT).as_posix().encode())
            digest.update(path.read_bytes())
    assert checkpoint_identity.config_hash(cfg, client, None, tools, "off") == digest.hexdigest()


@pytest.mark.parametrize("changed", [
    "agent_platform/agent/nodes/solve.py", "agent_platform/agent/state.py",
    "agent_platform/agent/checkpoint_identity.py", "agent_platform/agent/prompts/staged.py",
    "reasoning_agent/custom2/staged_prompts.py", "agent_platform/storage/memory.py",
    "agent_platform/agent/nodes/new_node.py",
])
def test_source_changes_invalidate_old_identity(changed):
    cfg, client, tools = scenarios.config(), scenarios.ScriptedClient([]), scenarios.ToolRegistry()
    expected = checkpoint_identity.config_hash(cfg, client, None, tools, "off")
    sources = checkpoint_identity.source_files(ROOT)
    sources[changed] = sources.get(changed, b"") + b"\n# changed\n"
    with patch.object(checkpoint_identity, "source_files", return_value=sources):
        assert checkpoint_identity.config_hash(cfg, client, None, tools, "off") != expected


def test_config_and_client_identity_remain_bound():
    client, tools = scenarios.ScriptedClient([]), scenarios.ToolRegistry()
    cfg = scenarios.config()
    original = checkpoint_identity.config_hash(cfg, client, "provider/v1", tools, "off")
    assert checkpoint_identity.config_hash(cfg, client, "provider/v2", tools, "off") != original
    assert checkpoint_identity.config_hash(scenarios.config(custom2_max_repairs=1), client,
                                           "provider/v1", tools, "off") != original


@pytest.mark.parametrize("old_path,new_path,names", [
    ("agent_platform/staged_adapter.py", "agent_platform/agent/stage_engine.py", ["StagedAdapter"]),
    ("agent_platform/staged_adapter.py", "agent_platform/agent/execution.py", ["TracedClient", "ExecutionStopped"]),
    ("agent_platform/storage.py", "agent_platform/storage/memory.py", ["InMemoryTaskStore"]),
    ("agent_platform/storage.py", "agent_platform/storage/base.py", ["TaskStore"]),
    ("agent_platform/presentation.py", "agent_platform/presentation/instructions.py",
     ["requested_style", "solver_style_prompt"]),
    ("agent_platform/presentation.py", "agent_platform/presentation/sections.py",
     ["strip_private_thoughts", "_parse_solution", "public_sections"]),
    ("agent_platform/presentation.py", "agent_platform/presentation/rendering.py", ["render_chat_response"]),
])
def test_extracted_shared_code_is_syntactically_identical(old_path, new_path, names):
    def definitions(source):
        return {node.name: node for node in ast.parse(source).body if hasattr(node, "name")}
    old = definitions(SNAPSHOT[old_path])
    new = definitions((ROOT / new_path).read_text())
    for name in names:
        before, after = old[name], new[name]
        if name == "StagedAdapter":
            before.body = [node for node in before.body if getattr(node, "name", None) != "execute"]
            after.body = [node for node in after.body if getattr(node, "name", None) != "execute"]
        assert ast.dump(before) == ast.dump(after)


def test_extracted_node_branches_keep_original_statements():
    adapter = next(node for node in ast.parse(SNAPSHOT["agent_platform/staged_adapter.py"]).body
                   if getattr(node, "name", None) == "StagedAdapter")
    execute = next(node for node in adapter.body if getattr(node, "name", None) == "execute")
    branch = next(node for node in execute.body if isinstance(node, ast.If))

    class Receiver(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == "self":
                node.id = "engine"
            return node

    while branch:
        name = next(node.value for node in ast.walk(branch.test)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str))
        extracted = ast.parse((ROOT / f"agent_platform/agent/nodes/{name}.py").read_text())
        run = next(node for node in extracted.body if getattr(node, "name", None) == "run")
        before = Receiver().visit(ast.Module(body=branch.body, type_ignores=[]))
        assert ast.dump(before) == ast.dump(ast.Module(body=run.body, type_ignores=[]))
        branch = branch.orelse[0] if branch.orelse else None


def test_graph_registration_preserves_node_order_and_edge_targets():
    captured = []
    original_factory = BASE_GRAPH.StateGraph

    def capture(state):
        graph = original_factory(state)
        captured.append(graph)
        return graph

    with patch.object(BASE_GRAPH, "StateGraph", capture):
        observe_pair(scenarios.scenario_pass_first_try)
    from agent_platform.agent.graph import build_graph
    runtime = LangGraphRuntime(scenarios.ScriptedClient([]), scenarios.config())
    ctx, _, _ = scenarios.make_context()
    new = build_graph(runtime, ctx)
    old = captured[0]
    assert list(old.nodes) == list(new.nodes)
    assert old.edges == new.edges
    assert {stage: {key: branch.ends for key, branch in branches.items()}
            for stage, branches in old.branches.items()} == {
                stage: {key: branch.ends for key, branch in branches.items()}
                for stage, branches in new.branches.items()}


@pytest.mark.parametrize("manifest", [
    [], None, {"protected": []},
    {"protected": {}, "new_paths": None, "removed_paths": []},
    {"protected": {}, "new_paths": [], "removed_paths": [1]},
    {"protected": {}, "new_paths": [], "removed_paths": [], "snapshot_sha256": "invalid"},
])
def test_malformed_migration_metadata_disables_legacy_mapping(manifest):
    current = checkpoint_identity.source_files(ROOT)
    with patch.object(Path, "read_text", return_value=json.dumps(manifest)):
        assert checkpoint_identity.logical_sources(ROOT) == current

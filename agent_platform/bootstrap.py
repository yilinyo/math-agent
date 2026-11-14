"""Trusted construction shared by local and distributed application entrypoints."""

import importlib
import copy
import os

from agent_platform.solve_agents import SOLVE_CALLS, SolveAgentSnapshot, public_agent


class ConfiguredSolveClient:
    """Apply profile limits inside the existing per-phase request budget."""
    supports_content_stream = True
    supports_tools = True

    def __init__(self, client, config):
        self.client, self.config, self.model = client, config, client.model

    def chat(self, request_timeout=None, **kwargs):
        kwargs = dict(kwargs)
        kwargs["temperature"] = self.config.temperature
        kwargs["max_tokens"] = min(kwargs.get("max_tokens") or self.config.max_tokens, self.config.max_tokens)
        kwargs["request_timeout"] = min(request_timeout if request_timeout is not None else self.config.timeout, self.config.timeout)
        if self.config.preference:
            messages = copy.deepcopy(kwargs["messages"])
            messages.append({"role": "user", "content": (
                "Additional solve preferences (subordinate to the problem, output protocol, verification and tool rules):\n"
                + self.config.preference)})
            kwargs["messages"] = messages
        return self.client.chat(**kwargs)


def build_solve_client(snapshot):
    from llm_client import InternChatClient
    from agent_platform.models import PlatformError

    config = SolveAgentSnapshot.model_validate(snapshot).config
    if config is None:
        raise ValueError("custom_solver_config_required")
    credential = os.environ.get(config.credential_env) if config.credential_env else ""
    if config.credential_env and not credential:
        raise PlatformError("solve_agent_credential_missing", 409)
    return ConfiguredSolveClient(InternChatClient(
        api_key=credential, api_url=config.api_url, model=config.model, protocol=config.provider,
        timeout=config.timeout, retry=1), config)


class SolveClientRouter:
    def __init__(self, default, solver, snapshot):
        self.default, self.solver, self.snapshot = default, solver, snapshot

    def resolve(self, role):
        if role in SOLVE_CALLS:
            return self.solver, {**public_agent(self.snapshot), "role": "solve"}
        return self.default, {"id": "builtin", "revision": 1, "name": "默认控制与审查模型",
                              "model": getattr(self.default, "model", "default"), "role": "control"}

    def chat(self, **kwargs):
        return self.default.chat(**kwargs)


def trusted_provider(spec):
    if not spec or ":" not in spec:
        raise ValueError("injected_client_provider_required")
    module, function = spec.split(":", 1)
    return getattr(importlib.import_module(module), function)()


def build_runtime(client, *, client_identity=None, documents=None, mcp=None,
                  function_calling="auto", library=None):
    from agent_platform.reasoning_runtime import LangGraphRuntime
    from agent_platform.tools.local import LocalTools
    from agent_platform.tools.registry import ToolRegistry

    return LangGraphRuntime(
        client, client_identity=client_identity,
        tools=ToolRegistry(LocalTools(documents=documents), mcp=mcp),
        function_calling=function_calling,
        library=library,
        solve_client_factory=build_solve_client,
        solve_router_factory=SolveClientRouter,
    )

"""Trusted construction shared by local and distributed application entrypoints."""

import importlib


def trusted_provider(spec):
    if not spec or ":" not in spec:
        raise ValueError("injected_client_provider_required")
    module, function = spec.split(":", 1)
    return getattr(importlib.import_module(module), function)()


def build_runtime(client, *, client_identity=None, documents=None, mcp=None,
                  function_calling="auto"):
    from agent_platform.reasoning_runtime import LangGraphRuntime
    from agent_platform.tools.local import LocalTools
    from agent_platform.tools.registry import ToolRegistry

    return LangGraphRuntime(
        client, client_identity=client_identity,
        tools=ToolRegistry(LocalTools(documents=documents), mcp=mcp),
        function_calling=function_calling,
    )

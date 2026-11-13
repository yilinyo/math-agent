"""Dependency assembly keeps the existing runtime construction contract."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_platform.bootstrap import build_runtime, trusted_provider
from agent_platform.reasoning_runtime import LangGraphRuntime
from agent_platform.tools.local import LocalTools
from agent_platform.tools.registry import ToolRegistry


class Client:
    def chat(self, **kwargs):
        raise AssertionError("Construction must not invoke the model")


def test_bootstrap_matches_direct_construction():
    client = Client()
    documents = SimpleNamespace(identity="fixture-documents")
    mcp = object()
    assembled = build_runtime(client, client_identity="fixture/v1", documents=documents,
                              mcp=mcp, function_calling="off")
    direct = LangGraphRuntime(client, client_identity="fixture/v1",
                              tools=ToolRegistry(LocalTools(documents=documents), mcp=mcp),
                              function_calling="off")
    assert assembled.client is client
    assert assembled.config == direct.config
    assert assembled.config_hash == direct.config_hash
    assert assembled.tools.identity == direct.tools.identity
    assert assembled.tools.local.documents is documents
    assert assembled.tools.mcp is mcp
    assert assembled.adapter_factory is direct.adapter_factory


@pytest.mark.parametrize("spec", [None, "", "missing-separator"])
def test_trusted_provider_rejects_the_same_invalid_specs(spec):
    with pytest.raises(ValueError, match="injected_client_provider_required"):
        trusted_provider(spec)


def test_trusted_provider_constructs_only_the_explicit_provider():
    client = Client()
    with patch("agent_platform.bootstrap.importlib.import_module",
               return_value=SimpleNamespace(create=lambda: client)) as imported:
        assert trusted_provider("fixture:create") is client
        imported.assert_called_once_with("fixture")

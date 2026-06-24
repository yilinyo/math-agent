import os
from typing import Any

from reasoning_agent.custom import CustomAgent


DEFAULT_AGENT_MODE = "custom"
SUPPORTED_AGENT_MODES = {"custom", "baseline"}


def resolve_agent_mode(agent_mode: str | None = None) -> str:
    mode = agent_mode or os.environ.get("REASONING_AGENT_MODE", DEFAULT_AGENT_MODE)
    normalized = str(mode).strip().lower()
    if normalized == "default":
        normalized = DEFAULT_AGENT_MODE
    if normalized not in SUPPORTED_AGENT_MODES:
        allowed = ", ".join(sorted(SUPPORTED_AGENT_MODES))
        raise ValueError(f"Unknown agent mode: {mode}. Allowed modes: {allowed}.")
    return normalized


class ReasoningAgent:
    """Stable platform entrypoint that dispatches to a concrete implementation.

    The official platform imports this class from user_agent.py. This wrapper
    keeps that interface stable while allowing local experiments to switch the
    underlying implementation.
    """

    def __init__(
        self,
        client: Any,
        config: Any | None = None,
        *args: Any,
        agent_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        mode = resolve_agent_mode(agent_mode or kwargs.pop("agent_mode", None))
        self.agent_mode = mode
        self._agent = self._build_agent(mode, client, config, *args, **kwargs)

    def solve(self, problem: str, metadata: dict | None) -> dict:
        return self._agent.solve(problem, metadata)

    def _build_agent(
        self,
        mode: str,
        client: Any,
        config: Any | None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if mode == "custom":
            return CustomAgent(client, config, *args, **kwargs)

        if mode == "baseline":
            try:
                from reasoning_agent.baseline import BaselineAgent
            except ImportError as exc:
                raise RuntimeError(
                    "BaselineAgent requires lagent. Install requirements.txt or use "
                    "REASONING_AGENT_MODE=custom."
                ) from exc
            return BaselineAgent(client, config, *args, **kwargs)

        raise AssertionError(f"unhandled agent mode: {mode}")

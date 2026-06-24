from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    function: Callable[..., Any]
    required_arguments: tuple[str, ...] = ()
    optional_arguments: tuple[str, ...] = ()
    description: str = ""

    @property
    def allowed_arguments(self) -> set[str]:
        return set(self.required_arguments) | set(self.optional_arguments)


def build_tool_registry() -> dict[str, ToolSpec]:
    """Return the official whitelist of local tools.

    The custom agent intentionally starts with no executable math tools. Add SymPy
    tools here after their validation and serialization behavior is tested.
    """
    return {}

"""Compatibility module; implementation lives in agent_platform.reasoning_runtime."""
import sys
from agent_platform import reasoning_runtime as _implementation

sys.modules[__name__] = _implementation

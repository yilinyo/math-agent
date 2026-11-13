"""Compatibility module; implementation lives in agent_platform.agent.stage_engine."""
import sys
from agent_platform.agent import stage_engine as _implementation

sys.modules[__name__] = _implementation

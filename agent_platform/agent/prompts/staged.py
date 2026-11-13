"""Stable entry to the existing staged prompts, preserving module patching."""
import sys
from reasoning_agent.custom2 import staged_prompts as _implementation

sys.modules[__name__] = _implementation

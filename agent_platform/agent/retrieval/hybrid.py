"""Compatibility entry to the existing weighted and RRF retrieval implementation."""
import sys
from reasoning_agent import hybrid_strategy_retrieval as _implementation

sys.modules[__name__] = _implementation

"""Compatibility entry to the existing vector retrieval implementation."""
import sys
from reasoning_agent import strategy_retrieval as _implementation

sys.modules[__name__] = _implementation

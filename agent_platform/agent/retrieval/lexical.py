"""Compatibility entry to the existing lexical retrieval implementation."""
import sys
from reasoning_agent import lexical_strategy_retrieval as _implementation

sys.modules[__name__] = _implementation

"""Compatibility entry for the postgres task store."""
import sys
from typing import TYPE_CHECKING
from agent_platform.storage import postgres as _implementation

if TYPE_CHECKING:
    from agent_platform.storage.postgres import PostgresTaskStore as PostgresTaskStore

sys.modules[__name__] = _implementation

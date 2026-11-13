"""Task persistence contracts and the process-local reference store."""
from agent_platform.storage.base import TaskStore
from agent_platform.storage.memory import InMemoryTaskStore

__all__ = ["TaskStore", "InMemoryTaskStore"]

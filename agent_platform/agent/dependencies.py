"""Injected capabilities used by the staged workflow; no clients are constructed here."""

import threading
from datetime import datetime
from typing import Any, Protocol


class ChatClient(Protocol):
    def chat(self, **kwargs: Any) -> Any: ...


class ModelPermits(Protocol):
    def acquire(self, timeout: float = ...) -> bool: ...
    def release(self) -> None: ...


class Tools(Protocol):
    identity: str
    local: Any

    async def invoke(self, request: Any, context: Any) -> Any: ...


class RunContext(Protocol):
    task_id: str
    session_id: str
    problem: str
    metadata: dict[str, Any]
    checkpoint: dict[str, Any] | None
    deadline_at: datetime | None
    finalize_reserve_seconds: float
    cancelled: threading.Event

    def progress(self, stage: str, *, completed: bool = False,
                 checkpoint: dict[str, Any] | None = None) -> None: ...
    def record(self, stage: str, event_type: str, payload: dict[str, Any]) -> None: ...
    def save_response(self, response: str) -> None: ...

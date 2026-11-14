from datetime import datetime
from typing import Any

from agent_platform.models import TERMINAL_STATUSES, Task, TaskStatus, utc_now


def task_timing(task: Task, now: datetime | None = None) -> dict[str, int | None]:
    """Wall-clock durations; processing includes pauses between execution attempts."""
    stopped = task.status in TERMINAL_STATUSES or task.status == TaskStatus.INTERRUPTED
    end = (task.finished_at or task.stopped_at) if stopped else (now or utc_now())

    def milliseconds(start: datetime | None, finish: datetime | None) -> int | None:
        if start is None or finish is None:
            return None
        return max(0, int((finish - start).total_seconds() * 1000))

    return {
        "total_ms": milliseconds(task.accepted_at, end),
        "queue_ms": milliseconds(task.accepted_at, task.started_at or end),
        "processing_ms": milliseconds(task.started_at, end),
        "answer_delivery_ms": task.answer_delivery_ms,
    }


def record_task_timing(task: Task, event_type: str, payload: dict[str, Any],
                       now: datetime) -> dict[str, Any]:
    if event_type in {"task.running", "task.resumed"}:
        task.stopped_at = None
        task.answer_delivery_ms = None
    elif event_type in {"task.interrupted", "task.succeeded", "task.failed", "task.cancelled"}:
        task.stopped_at = task.finished_at or now
    if event_type == "answer.completed" and payload.get("preview") is not True:
        duration = payload.get("duration_ms")
        if type(duration) is int and duration >= 0:
            task.answer_delivery_ms = duration
    if event_type.startswith("task."):
        return {**payload, "timing": task_timing(task, now),
                "stopped_at": task.stopped_at.isoformat() if task.stopped_at else None}
    return payload

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent_platform.app import create_app
from agent_platform.models import Task, TaskStatus
from agent_platform.redis_store import RedisTaskStore, decode_task, encode
from agent_platform.runtime import FakeRuntime
from agent_platform.storage import InMemoryTaskStore
from agent_platform.timing import task_timing


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(params=["memory", "redis"])
def store(request):
    if request.param == "memory":
        return InMemoryTaskStore()
    fakeredis = pytest.importorskip("fakeredis")
    return RedisTaskStore(fakeredis.FakeRedis(decode_responses=True), require_aof=False)


def new_task(store):
    with patch("agent_platform.storage.memory.utc_now", return_value=BASE), \
         patch("agent_platform.storage.memory.Task", side_effect=lambda **values: Task(accepted_at=BASE, **values)):
        session = store.create_session(100)
        task, _ = store.create_task(session.id, "Timing fixture.", {}, "fake", "key")
    return session, task


def test_completed_durations_survive_storage_history_and_api(store):
    session, queued = new_task(store)
    with patch("agent_platform.storage.memory.utc_now", return_value=BASE + timedelta(seconds=5)):
        running = store.start(session.id, queued.id, 1200)
    with patch("agent_platform.storage.memory.utc_now", return_value=BASE + timedelta(seconds=8)):
        store.record(session.id, queued.id, running.generation, "finalize", "answer.completed",
                     {"stream_id": "fixture", "chunks": 1, "duration_ms": 120})
    with patch("agent_platform.storage.memory.utc_now", return_value=BASE + timedelta(seconds=9)):
        store.finish(session.id, queued.id, running.generation, TaskStatus.SUCCEEDED, "Accepted result.")
    expected = {"total_ms": 9000, "queue_ms": 5000, "processing_ms": 4000, "answer_delivery_ms": 120}
    final = store.get_task(session.id, queued.id)
    assert task_timing(final, BASE + timedelta(hours=2)) == expected
    assert store.events_after(session.id, queued.id, 0)[-1].payload["timing"] == expected
    assert task_timing(store.list_tasks(session.id, 10)[0][0]) == expected
    with TestClient(create_app(store=store, runtime=FakeRuntime(0), rate_limits=False)) as client:
        assert client.get(f"/v1/sessions/{session.id}/tasks/{queued.id}").json()["timing"] == expected
        assert client.get(f"/v1/sessions/{session.id}/tasks").json()["items"][0]["timing"] == expected


def test_interruption_freezes_until_resume_and_retains_initial_queue_duration(store):
    session, queued = new_task(store)
    with patch("agent_platform.storage.memory.utc_now", return_value=BASE + timedelta(seconds=5)):
        running = store.start(session.id, queued.id, 1200)
    with patch("agent_platform.storage.memory.utc_now", return_value=BASE + timedelta(seconds=10)):
        store.finish(session.id, queued.id, running.generation, TaskStatus.INTERRUPTED)
    paused = store.get_task(session.id, queued.id)
    assert paused.finished_at is None and paused.stopped_at == BASE + timedelta(seconds=10)
    assert task_timing(paused, BASE + timedelta(hours=1))["total_ms"] == 10000
    with patch("agent_platform.storage.memory.utc_now", return_value=BASE + timedelta(seconds=20)):
        resumed, _ = store.resume(session.id, queued.id)
    assert resumed.stopped_at is None
    with patch("agent_platform.storage.memory.utc_now", return_value=BASE + timedelta(seconds=25)):
        running = store.start(session.id, queued.id, 1200)
    with patch("agent_platform.storage.memory.utc_now", return_value=BASE + timedelta(seconds=30)):
        final = store.finish(session.id, queued.id, running.generation, TaskStatus.SUCCEEDED, "Result.")
    assert task_timing(final) == {"total_ms": 30000, "queue_ms": 5000,
                                  "processing_ms": 25000, "answer_delivery_ms": None}


def test_queued_cancellation_records_waiting_time_without_processing(store):
    session, queued = new_task(store)
    with patch("agent_platform.storage.memory.utc_now", return_value=BASE + timedelta(seconds=3)):
        final = store.cancel(session.id, queued.id)
    assert task_timing(final) == {"total_ms": 3000, "queue_ms": 3000,
                                  "processing_ms": None, "answer_delivery_ms": None}


def test_old_snapshots_decode_without_new_fields_and_unknown_pause_is_not_invented():
    store = InMemoryTaskStore()
    _, task = new_task(store)
    data = {**asdict(task), "events": []}
    data.pop("stopped_at")
    data.pop("answer_delivery_ms")
    old = decode_task(encode(data))
    assert old.stopped_at is None and old.answer_delivery_ms is None
    old.status = TaskStatus.INTERRUPTED
    assert task_timing(old, BASE + timedelta(days=1))["total_ms"] is None


def test_negative_wall_clock_differences_are_clamped():
    _, task = new_task(InMemoryTaskStore())
    assert task_timing(task, BASE - timedelta(seconds=5))["total_ms"] == 0

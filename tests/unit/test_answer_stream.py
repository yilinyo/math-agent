import asyncio
import json

import pytest

from agent_platform.models import PlatformError, TaskStatus
from agent_platform.runtime import RuntimeResult
from agent_platform.safety import sanitize_text
from agent_platform.service import TaskService
from agent_platform.storage import InMemoryTaskStore


class AcceptedRuntime:
    name = "stream_test"

    def __init__(self, response, ready=None):
        self.response = response
        self.ready = ready

    async def run(self, context):
        context.progress("solve")
        if self.ready:
            await self.ready.wait()
        context.progress("finalize", completed=True, checkpoint={"accepted": True})
        return RuntimeResult(self.response)


def setup(runtime):
    store = InMemoryTaskStore()
    session = store.create_session(1000)
    queued, _ = store.create_task(session.id, "Test streaming.", {}, runtime.name, "fixed")
    task = store.start(session.id, queued.id, 1200)
    service = TaskService(store, runtime)
    service.accepting = True
    return store, task, service


async def wait_for_delta(store, task):
    async with asyncio.timeout(5):
        while not any(event.event_type == "answer.delta"
                      for event in store.events_after(task.session_id, task.id, 0)):
            await asyncio.sleep(.001)


def test_only_accepted_sanitized_answer_streams_before_terminal_commit():
    async def scenario():
        ready = asyncio.Event()
        # Secrets straddle prospective chunk boundaries; per-chunk redaction is insufficient.
        response = "A" * 89 + " Bearer abcdefghijklmnopqrstuvwxyz " + "B" * 89 + r" C:\private\key.txt " + "C" * 200
        store, task, service = setup(AcceptedRuntime(response, ready))
        execution = asyncio.create_task(service._execute(task))
        await asyncio.sleep(.01)
        assert not any(event.event_type.startswith("answer.")
                       for event in store.events_after(task.session_id, task.id, 0))
        ready.set()
        await wait_for_delta(store, task)
        pending = store.get_task(task.session_id, task.id)
        assert pending.status == TaskStatus.RUNNING and pending.final_response is None
        await execution
        events = store.events_after(task.session_id, task.id, 0)
        deltas = [event for event in events if event.event_type == "answer.delta"]
        assert len(deltas) > 1
        assert [event.payload["index"] for event in deltas] == list(range(len(deltas)))
        assert len({event.payload["stream_id"] for event in deltas}) == 1
        accepted = store.get_task(task.session_id, task.id)
        assert "".join(event.payload["text"] for event in deltas) == accepted.final_response == sanitize_text(response)
        assert events[-2].event_type == "answer.completed"
        assert type(events[-2].payload["duration_ms"]) is int
        assert accepted.answer_delivery_ms == events[-2].payload["duration_ms"] >= 0
        assert events[-1].event_type == "task.succeeded"
        serialized = json.dumps([event.model_dump(mode="json") for event in events])
        assert "abcdefghijklmnopqrstuvwxyz" not in serialized and "private" not in serialized
        other = store.create_session(0)
        with pytest.raises(PlatformError, match="task_not_found"):
            store.events_after(other.id, task.id, 0)
    asyncio.run(scenario())


def test_cancel_during_answer_delivery_does_not_commit_partial_answer():
    async def scenario():
        store, task, service = setup(AcceptedRuntime("Accepted text. " * 100))
        execution = asyncio.create_task(service._execute(task))
        await wait_for_delta(store, task)
        service.cancel(task.session_id, task.id)
        await execution
        final = store.get_task(task.session_id, task.id)
        assert final.status == TaskStatus.CANCELLED and final.final_response is None
        assert not any(event.event_type == "answer.completed" for event in final.events)
        assert not any(message.role == "assistant" for message in store.get_session(task.session_id).messages)
    asyncio.run(scenario())


def test_resume_starts_a_new_answer_stream_after_interrupted_delivery():
    async def scenario():
        response = "Accepted result. " * 30
        store, task, service = setup(AcceptedRuntime(response))
        execution = asyncio.create_task(service._execute(task))
        await wait_for_delta(store, task)
        execution.cancel()
        await execution
        assert store.get_task(task.session_id, task.id).status == TaskStatus.INTERRUPTED
        store.resume(task.session_id, task.id)
        resumed = store.start(task.session_id, task.id, 1200)
        await service._execute(resumed)
        events = store.events_after(task.session_id, task.id, 0)
        starts = [event.payload["stream_id"] for event in events if event.event_type == "answer.started"]
        assert len(starts) == len(set(starts)) == 2
        assert "".join(event.payload["text"] for event in events
                       if event.event_type == "answer.delta" and event.payload["stream_id"] == starts[-1]) == response
        assert store.get_task(task.session_id, task.id).final_response == response
    asyncio.run(scenario())


def test_failed_runtime_does_not_emit_answer_deltas():
    class FailedRuntime:
        name = "failed_test"

        async def run(self, context):
            raise ValueError("Private model reply must not escape.")

    async def scenario():
        store, task, service = setup(FailedRuntime())
        await service._execute(task)
        final = store.get_task(task.session_id, task.id)
        assert final.status == TaskStatus.FAILED
        assert not any(event.event_type.startswith("answer.") for event in final.events)
    asyncio.run(scenario())

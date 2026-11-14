import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { taskFromEvent, type Task, type TraceEvent } from './api';
import { formatDuration, taskTimings } from './timing';
import TaskOutput from './TaskOutput';
import { batchMarkdown } from './QuestionBatches';
import type { QuestionBatch } from './api';

const base = Date.parse('2026-01-01T00:00:00Z');
const task = { id: 'task', session_id: 'session', status: 'running', final_response: null,
  accepted_at: new Date(base).toISOString(), started_at: new Date(base + 5000).toISOString(),
  finished_at: null } as Task;
const event = (event_type: string, payload: Record<string, unknown>): TraceEvent => ({
  event_type, payload, sequence: 1, stage_id: 'finalize', task_id: task.id,
  session_id: task.session_id, created_at: new Date(base + 9000).toISOString(),
});

describe('task durations', () => {
  it('updates running durations and distinguishes initial waiting from processing', () => {
    expect(taskTimings(task, base + 9000)).toEqual({ total_ms: 9000, queue_ms: 5000, processing_ms: 4000, answer_delivery_ms: null });
    expect(taskTimings(task, base + 10000).total_ms).toBe(10000);
    expect(taskTimings({ ...task, status: 'queued', started_at: null }, base + 3000).processing_ms).toBeNull();
  });
  it('freezes on completion and interruption, including historical timestamps', () => {
    const completed = { ...task, status: 'succeeded' as const, finished_at: new Date(base + 9000).toISOString() };
    expect(taskTimings(completed, base + 60000).total_ms).toBe(9000);
    expect(taskTimings({ ...task, status: 'interrupted', stopped_at: completed.finished_at }, base + 60000).total_ms).toBe(9000);
    expect(taskTimings({ ...task, status: 'interrupted' }, base + 60000).total_ms).toBeNull();
  });
  it('uses recorded server durations for completed snapshots', () => {
    const timing = { total_ms: 9000, queue_ms: 5000, processing_ms: 4000, answer_delivery_ms: 120 };
    const final = taskFromEvent(task, event('task.succeeded', {
      status: 'succeeded', final_response: 'Result.', finished_at: new Date(base + 9000).toISOString(), timing,
    }));
    expect(final.finished_at).toBe(new Date(base + 9000).toISOString());
    expect(taskTimings(final, base + 60000)).toEqual(timing);
    expect(renderToStaticMarkup(<TaskOutput task={final} now={base + 60000} />)).toContain('答案发送 120 毫秒');
  });
  it('applies SSE start and pause timestamps and ignores operation timestamps', () => {
    const timestamp = new Date(base + 9000).toISOString();
    expect(taskFromEvent({ ...task, started_at: null }, event('task.running', { started_at: timestamp })).started_at).toBe(timestamp);
    const paused = taskFromEvent(task, event('task.interrupted', { status: 'interrupted', stopped_at: timestamp }));
    expect(taskTimings(paused, base + 60000).total_ms).toBe(9000);
    expect(taskFromEvent(task, event('model.completed', { finished_at: timestamp })).finished_at).toBeNull();
    expect(taskFromEvent(task, event('task.succeeded', { timing: { total_ms: -1 } })).timing).toBeUndefined();
  });
  it('clamps negative differences and does not fabricate missing timestamps', () => {
    expect(taskTimings(task, base - 1000).total_ms).toBe(0);
    expect(taskTimings({ ...task, accepted_at: 'invalid', started_at: null }, base).total_ms).toBeNull();
    expect(formatDuration(Number.NaN)).toBe('--');
    expect(formatDuration(null)).toBe('--');
    expect(formatDuration(120)).toBe('120 毫秒');
    expect(formatDuration(1234)).toBe('1.2 秒');
    expect(formatDuration(61234)).toBe('1 分 1.2 秒');
  });
  it('shows measured stage duration in the public execution summary', () => {
    const html = renderToStaticMarkup(<TaskOutput task={task} view={{ events: [event('stage.completed', { duration_ms: 1234 })] }} />);
    expect(html).toContain('1.2 秒');
  });
  it('exports recorded per-question duration with file answers', () => {
    const batch = { original_name: 'fixture.md', status: 'completed', questions: [{ number: 1, problem: 'Fixture.',
      task: { ...task, status: 'succeeded', final_response: 'Result.', finished_at: new Date(base + 9000).toISOString() } }] } as QuestionBatch;
    expect(batchMarkdown(batch)).toContain('总耗时：9.0 秒');
  });
});

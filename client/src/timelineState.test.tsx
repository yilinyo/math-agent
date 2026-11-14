import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { timelineFromEvent, type TimelineState } from './timelineState';
import SolutionTimeline from './SolutionTimeline';
import TaskOutput from './TaskOutput';
import { type Task, type TraceEvent } from './api';

const event = (sequence: number, event_type: string, stage_id = 'solve', payload = {}): TraceEvent => ({
  task_id: 'task', session_id: 'session', sequence, event_type, stage_id,
  created_at: new Date(1000 * sequence).toISOString(), payload,
});
const task = { id: 'task', session_id: 'session', status: 'succeeded',
  accepted_at: new Date(0).toISOString(), finished_at: new Date(300000).toISOString(), final_response: 'Final accepted result.' } as Task;
const replay = (events: TraceEvent[]) => events.reduce<TimelineState | undefined>(timelineFromEvent, undefined)!;

describe('solution timeline history', () => {
  it('retains repeated repairs after more than 120 events and deduplicates history replay', () => {
    const events = [event(1, 'stage.started'),
      event(2, 'stage.explanation', 'solve', { kind: 'solution', content: 'Original $x=1$' }),
      event(3, 'stage.completed')];
    for (let sequence = 4; sequence <= 150; sequence++) events.push(event(sequence, 'model.completed'));
    events.push(event(151, 'stage.started', 'repair'),
      event(152, 'stage.explanation', 'repair', { title: '修复依据', content: 'Check the sign.' }),
      event(153, 'stage.explanation', 'repair', { kind: 'solution', content: 'Repair $x=2$' }),
      event(154, 'stage.completed', 'repair'), event(155, 'stage.started', 'repair'),
      event(156, 'stage.explanation', 'repair', { kind: 'solution', content: 'Second repair $x=3$' }),
      event(157, 'stage.completed', 'repair'));
    const timeline = replay(events);
    expect(timeline.stages.map(row => row.stage)).toEqual(['solve', 'repair', 'repair']);
    expect(timeline.stages[0].content[0].content).toContain('Original');
    expect(timeline.stages[0].logs).toHaveLength(149);
    expect(timeline.stages[0].logs[0].sequence).toBe(1);
    expect(events.reduce(timelineFromEvent, timeline)).toBe(timeline);
    const html = renderToStaticMarkup(<SolutionTimeline task={task} timeline={timeline} now={300000} />);
    for (const value of ['Original', 'Repair', 'Second repair', 'Check the sign.', '第 3 轮公开推导', 'katex']) expect(html).toContain(value);
  });

  it('validates chunks, completes a streamed draft once and excludes final delivery', () => {
    const timeline = replay([event(1, 'stage.started'),
      event(2, 'answer.started', 'solve', { stream_id: 'a', preview: true }),
      event(3, 'answer.delta', 'solve', { stream_id: 'a', index: 1, text: 'gap' }),
      event(4, 'answer.delta', 'solve', { stream_id: 'a', index: 0, text: 'Live $x=2$' }),
      event(5, 'answer.delta', 'solve', { stream_id: 'other', index: 1, text: 'foreign' }),
      event(6, 'answer.completed', 'solve', { stream_id: 'a', chunks: 1 }),
      event(7, 'stage.explanation', 'solve', { kind: 'solution', content: 'Complete $x=2$' }),
      event(8, 'answer.started', 'finalize', { stream_id: 'final' }),
      event(9, 'answer.delta', 'finalize', { stream_id: 'final', index: 0, text: 'Accepted answer' })]);
    expect(timeline.stages[0].content).toHaveLength(1);
    expect(timeline.stages[0].content[0].content).toBe('Complete $x=2$');
    expect(JSON.stringify(timeline)).not.toMatch(/gap|foreign|Accepted answer/);
  });

  it('retracts failed calls and preserves earlier drafts across interruption and resume', () => {
    const timeline = replay([event(1, 'stage.started'),
      event(2, 'answer.started', 'solve', { stream_id: 'good', preview: true }),
      event(3, 'answer.delta', 'solve', { stream_id: 'good', index: 0, text: 'Earlier draft' }),
      event(4, 'answer.completed', 'solve', { stream_id: 'good', chunks: 1 }),
      event(5, 'answer.started', 'solve', { stream_id: 'failed', preview: true }),
      event(6, 'answer.delta', 'solve', { stream_id: 'failed', index: 0, text: 'Failed prefix' }),
      event(7, 'answer.discarded', 'solve', { stream_id: 'failed' }),
      event(8, 'task.interrupted', 'system'), event(9, 'task.resumed', 'system'),
      event(10, 'stage.started', 'repair')]);
    expect(timeline.stages[0].content.map(row => row.content)).toEqual(['Earlier draft']);
    expect(timeline.stages[1].stage).toBe('repair');
  });

  it('keeps drafts beside the authoritative final result without duplicating the live preview', () => {
    const timeline = replay([event(1, 'stage.started'),
      event(2, 'stage.explanation', 'solve', { kind: 'solution', content: 'Old candidate' })]);
    const html = renderToStaticMarkup(<TaskOutput task={task} view={{ events: [], timeline }} now={300000} />);
    expect(html).toContain('Old candidate');
    expect(html).toContain('Final accepted result.');
    expect(html).toContain('阶段草稿，以最终答案为准');
    const running = renderToStaticMarkup(<TaskOutput task={{ ...task, status: 'running', final_response: null }}
      view={{ events: [], timeline, stream: { id: 'live', text: 'Old candidate', preview: true, sequence: 2, nextIndex: 1 } }} />);
    expect(running.match(/Old candidate/g)).toHaveLength(1);
  });
});

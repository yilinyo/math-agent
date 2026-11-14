import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { answerFromEvent, executionSummary } from './taskStream';
import TaskOutput from './TaskOutput';
import type { Task, TraceEvent } from './api';

const event = (sequence: number, event_type: string, payload = {}): TraceEvent => ({
  task_id: 'task', session_id: 'session', sequence, event_type, stage_id: 'solve', created_at: '', payload,
});
const start = event(1, 'answer.started', { stream_id: 'first' });
const first = event(2, 'answer.delta', { stream_id: 'first', index: 0, text: '中文 $x' });
const second = event(3, 'answer.delta', { stream_id: 'first', index: 1, text: '=2$' });
const task = { id: 'task', session_id: 'session', status: 'running', final_response: null } as Task;

describe('accepted answer streams', () => {
  it('appends ordered chunks once and preserves unicode and formula boundaries', () => {
    const stream = answerFromEvent(answerFromEvent(answerFromEvent(undefined, start), first), second);
    expect(stream?.text).toBe('中文 $x=2$');
    expect(answerFromEvent(stream, start)).toBe(stream);
    expect(answerFromEvent(stream, first)).toBe(stream);
    expect(answerFromEvent(stream, second)).toBe(stream);
  });
  it('rejects gaps and foreign stream IDs, then resets on a fresh stream', () => {
    const stream = answerFromEvent(undefined, start);
    expect(answerFromEvent(stream, second)).toBe(stream);
    expect(answerFromEvent(stream, event(2, 'answer.delta', { stream_id: 'other', index: 0, text: 'foreign' }))).toBe(stream);
    expect(answerFromEvent(stream, event(4, 'answer.started', { stream_id: 'second' }))?.text).toBe('');
  });
  it.each(['task.cancelled', 'task.interrupted', 'task.failed', 'task.resumed'])('discards the previous preview on %s', kind => {
    const stream = answerFromEvent(answerFromEvent(undefined, start), first);
    expect(answerFromEvent(stream, event(3, kind))).toBeUndefined();
  });
  it('shows an in-flight preview and renders the authoritative final result instead when complete', () => {
    const stream = answerFromEvent(answerFromEvent(undefined, start), first);
    const view = { events: [start], stream };
    const partial = renderToStaticMarkup(<TaskOutput task={task} view={view} />);
    expect(partial).toContain('streaming-answer');
    expect(partial).toContain('aria-busy="true"');
    expect(partial).toContain('中文');
    const final = renderToStaticMarkup(<TaskOutput task={{ ...task, status: 'succeeded', final_response: '$y=3$' }} view={view} />);
    expect(final).toContain('katex');
    expect(final).not.toContain('中文');
    expect(final).not.toContain('streaming-answer');
  });
  it.each(['cancelled', 'failed', 'interrupted'] as const)('hides partial output on %s snapshots', status => {
    const stream = answerFromEvent(answerFromEvent(undefined, start), first);
    const html = renderToStaticMarkup(<TaskOutput task={{ ...task, status }} view={{ events: [], stream }} />);
    expect(html).not.toContain('中文');
  });
});

it('summarizes public activity without exposing payloads or raw model replies', () => {
  const activity = event(1, 'model.completed', { raw_response: 'private text', prompt: 'private prompt' });
  expect(executionSummary(activity)).toBe('推导求解：模型处理结束。');
  expect(executionSummary(event(2, 'private.thought', { text: 'private' }))).toBeNull();
  const html = renderToStaticMarkup(<TaskOutput task={task} view={{ events: [activity] }} />);
  expect(html).toContain('执行摘要');
  expect(html).not.toContain('private');
});

it.each([
  ['incomplete_model_stream', '模型响应中断'],
  ['model_timeout', '等待模型响应超时'],
  ['model_auth_error', '模型服务认证失败'],
  ['model_rate_limited', '模型服务限流'],
  ['model_service_error', '模型服务暂时异常'],
  ['private prompt', '模型调用未成功'],
  ['__proto__', '模型调用未成功'],
])('shows only a fixed diagnostic for %s', (code, expected) => {
  const summary = executionSummary(event(1, 'model.failed', {
    error_code: code, message: 'private reply', response_body: 'private body',
  }));
  expect(summary).toContain(expected);
  expect(summary).not.toContain('private');
});

it('labels generated drafts until verification and retracts a failed draft', () => {
  let stream = answerFromEvent(undefined, event(1, 'answer.started', { stream_id: 'first', preview: true }));
  stream = answerFromEvent(stream, first);
  expect(renderToStaticMarkup(<TaskOutput task={task} view={{ events: [], stream }} />)).toContain('待校验解答 · 正在生成');
  stream = answerFromEvent(stream, event(3, 'answer.completed', { stream_id: 'first', chunks: 1, duration_ms: 500 }));
  expect(renderToStaticMarkup(<TaskOutput task={task} view={{ events: [], stream }} />)).toContain('待校验解答 · 正在校验');
  expect(answerFromEvent(stream, event(4, 'answer.discarded', { stream_id: 'other' }))).toBe(stream);
  expect(answerFromEvent(stream, event(4, 'answer.discarded', { stream_id: 'first' }))).toBeUndefined();
  expect(answerFromEvent(stream, event(4, 'answer.started', { stream_id: 'repair', preview: true }))?.text).toBe('');
});

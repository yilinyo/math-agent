import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { describeEvent, matchesTrace, publicTraceEvent, traceRows, traceStageGroups } from '../../agent_platform/static/trace-format.js';
import TraceLog from './TraceLog';
import { timelineFromEvent } from './timelineState';
import type { TraceEvent } from './api';

const event = (sequence: number, event_type: string, payload = {}, stage_id = 'solve'): TraceEvent => ({
  task_id: 'task', session_id: 'session', sequence, event_type, stage_id,
  created_at: new Date(sequence * 1000).toISOString(), payload,
});

describe('readable execution diagnostics', () => {
  it('shows the shared review budget and distinguishes an unfinished review from a pass', () => {
    const started = describeEvent(event(1, 'reasoning.event', {
      operation: 'review_round_started', budget_seconds: 150,
    }, 'verify'))!;
    expect(started.details).toContainEqual(['本轮审查预算', '150 秒']);
    const unfinished = describeEvent(event(2, 'reasoning.event', {
      operation: 'review_round_completed', review_status: 'service_unavailable',
    }, 'verify'))!;
    expect(unfinished.title).toContain('未完成');
    expect(unfinished.level).toBe('warning');
    expect(describeEvent(event(3, 'reasoning.event', { operation: 'audit_deep_started' }, 'verify'))!.title)
      .toContain('针对疑点');
  });
  it('correlates parallel model calls by operation ID and keeps their actual usage and duration', () => {
    const rows = traceRows([
      event(1, 'model.started', { operation_id: 'a', call_type: 'solver' }),
      event(2, 'model.started', { operation_id: 'b', call_type: 'solver_compressed' }),
      event(3, 'model.completed', { operation_id: 'b', call_type: 'solver_compressed', duration_ms: 400, usage: { total_tokens: 32 } }),
      event(4, 'model.failed', { operation_id: 'a', error_code: 'model_timeout', duration_ms: 900 }),
    ]);
    expect(rows).toHaveLength(2);
    expect(rows[0].events.map(row => row.sequence)).toEqual([1, 4]);
    expect(rows[0].view.level).toBe('error');
    expect(rows[1].durationMs).toBe(400);
    expect(rows[1].view.details).toContainEqual(['总 Token', '32']);
    expect(rows.filter(row => matchesTrace(row, '', true))).toHaveLength(1);
    expect(rows.filter(row => matchesTrace(row, '总 TOKEN'))).toHaveLength(1);
    expect(rows.filter(row => matchesTrace(row, 'b'))).toHaveLength(1);
  });

  it('explains acceptance failures and distinguishes execution from mathematical success', () => {
    const view = describeEvent(event(1, 'reasoning.event', { operation: 'final_candidate_checked', accepted: false,
      format_failures: ['multiple_final_candidates'], hard_failure_count: 0, budget_exhausted: true }, 'finalize'))!;
    expect(view.title).toContain('未通过最终验收');
    expect(view.details).toContainEqual(['格式检查', '存在冲突或尚无法证明等价的多个答案']);
    const executed = describeEvent(event(2, 'tool.completed', { name: 'math_verify', status: 'succeeded', verdict: 'uncertain' }))!;
    expect(executed.title).not.toContain('通过');
    expect(executed.details).toContainEqual(['核验结论', '无法确认']);
    expect(describeEvent(event(3, 'reasoning.event', { operation: 'final_candidate_checked', accepted: true }))!.title)
      .toContain('仍需后续核验');
  });

  it('shows actual tool values and sanitizes nested raw fields without echoing arbitrary model content', () => {
    const tool = event(1, 'tool.result', { name: 'sympy_calculate', result: { value: '8/5', conditions: ['a+b>0'],
      raw_response: 'PRIVATE_MODEL_RESPONSE' }, prompt: 'PRIVATE_PROMPT' });
    const html = renderToStaticMarkup(<TraceLog events={[tool]} query="" problemsOnly={false} active={false} />);
    expect(html).toContain('8/5');
    expect(html).toContain('适用条件');
    expect(html).not.toContain('PRIVATE');
    expect(JSON.stringify(publicTraceEvent(tool))).not.toContain('PRIVATE');
    expect(describeEvent(event(2, 'model.failed', { error_code: '__proto__', message: 'PRIVATE' }))!.title).toContain('模型调用未成功');
  });

  it('preserves repeated phases and does not mark an interrupted operation complete', () => {
    const events = [event(1, 'stage.started'), event(2, 'stage.context', { node: 'emergency', round: 2 }),
      event(3, 'model.started', { operation_id: 'a' }), event(4, 'task.interrupted', {}, 'system')];
    const state = events.reduce(timelineFromEvent, undefined);
    expect(state!.stages[0].node).toBe('emergency');
    expect(state!.stages[0].outcome).toBe('interrupted');
    expect(state!.stages[0].finishedAt).toBeUndefined();
    const groups = traceStageGroups([...events, event(5, 'stage.started'), event(6, 'stage.context', { node: 'solve', round: 3 })]);
    expect(groups.filter(group => group.stage === 'solve')).toHaveLength(2);
    const html = renderToStaticMarkup(<TraceLog events={events} query="" problemsOnly={false} active={false} />);
    expect(html).toContain('未记录此操作的结束事件');
  });

  it('paginates the display while retaining every event for filtering', () => {
    const events = Array.from({ length: 65 }, (_, index) => event(index + 1, 'model.completed', { operation_id: String(index) }));
    events.push(event(66, 'model.failed', { error_code: 'model_timeout' }));
    const html = renderToStaticMarkup(<TraceLog events={events} query="" problemsOnly={false} active={false} />);
    expect(html).toContain('剩余 36 条');
    const filtered = renderToStaticMarkup(<TraceLog events={events} query="超时" problemsOnly active={false} />);
    expect(filtered).toContain('等待模型响应超时');
    expect(filtered).not.toContain('剩余');
  });

  it('pairs interrupted operations and preserves the start transport when the completion omits it', () => {
    const rows = traceRows([
      event(1, 'tool.started', { operation_id: 'a', name: 'math_verify', transport: 'local' }),
      event(2, 'tool.completed', { operation_id: 'a', name: 'math_verify', verdict: 'uncertain' }),
      event(3, 'model.started', { operation_id: 'b', call_type: 'solver' }),
      event(4, 'model.interrupted', { operation_id: 'b' }),
    ]);
    expect(rows).toHaveLength(2);
    expect(rows[0].view.details).toContainEqual(['执行方式', '本地']);
    expect(rows[1].events).toHaveLength(2);
    expect(rows[1].view.level).toBe('warning');
    const html = renderToStaticMarkup(<TraceLog events={[event(1, 'stage.started'), event(2, 'stage.completed')]}
      query="" problemsOnly={false} active={false} />);
    expect(html).not.toContain('未记录此操作的结束事件');
  });
});

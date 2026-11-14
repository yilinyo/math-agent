import { afterEach, expect, it, vi } from 'vitest';
import { agentCommand, getAgents, saveAgent, startQuestionBatch, submitTask, type AgentDraft, type SolveAgent } from './api';
import { describeEvent, publicTraceEvent } from '../../agent_platform/static/trace-format.js';

afterEach(() => vi.unstubAllGlobals());
const draft: AgentDraft = { name: 'Solver', provider: 'compatible', model: 'test-model',
  api_url: 'https://example.com/v1/chat/completions', credential_env: 'CUSTOM_API_KEY',
  temperature: .3, max_tokens: 8192, timeout: 240, preference: '', enabled: true };

it('uses revisions for profile changes and only manually tests a saved model', async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response('{}'));
  vi.stubGlobal('fetch', fetch);
  await getAgents(); await saveAgent(draft);
  const item: SolveAgent = { ...draft, id: 'agent/id', revision: 2, builtin: false, credential_ready: true };
  await saveAgent({ ...draft, enabled: false }, item);
  await agentCommand(item, 'default'); await agentCommand(item, 'test'); await agentCommand(item, 'delete');
  expect(fetch.mock.calls.map(call => call[0])).toEqual(['/v1/solve-agents', '/v1/solve-agents',
    '/v1/solve-agents/agent%2Fid', '/v1/solve-agents/agent%2Fid/default?revision=2',
    '/v1/solve-agents/agent%2Fid/test?revision=2', '/v1/solve-agents/agent%2Fid?revision=2']);
  expect(JSON.parse(fetch.mock.calls[2][1].body).revision).toBe(2);
});

it('submits the selected solver for both text and file questions', async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response('{}'));
  vi.stubGlobal('fetch', fetch);
  await submitTask('session', 'question', 'key', 'detailed', undefined, 'solver-a');
  await startQuestionBatch('session', 'batch', 'explain', 'auto', 'solver-b');
  expect(JSON.parse(fetch.mock.calls[0][1].body).solve_agent_id).toBe('solver-a');
  expect(JSON.parse(fetch.mock.calls[1][1].body).solve_agent_id).toBe('solver-b');
});

it('shows actual agent, model, revision and responsibility in readable trace', () => {
  const event = { sequence: 1, created_at: '', event_type: 'model.started', stage_id: 'solve', payload: {
    call_type: 'solver_repair', agent: { id: 'a', name: 'Exact solver', model: 'math-model', revision: 3, role: 'solve' },
  } };
  const value = describeEvent(event);
  expect(value?.details).toContainEqual(['调用 Agent', 'Exact solver']);
  expect(value?.details).toContainEqual(['模型', 'math-model']);
  expect(value?.details).toContainEqual(['配置版本', 'v3']);
  expect(publicTraceEvent(event).payload.agent).toEqual(event.payload.agent);
});

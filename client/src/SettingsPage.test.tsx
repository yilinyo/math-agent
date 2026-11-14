import { expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import SettingsPage from './SettingsPage';
import type { Health } from './api';

const props = {
  section: 'general' as const, health: { solve_agents: true, custom_library: true, response_styles: ['auto'] } as Health,
  agentId: 'builtin', responseStyle: 'auto' as const, locked: false, agentsError: '',
  onAgentChange: vi.fn(), onStyleChange: vi.fn(), onAgentsChange: vi.fn(), onNavigate: vi.fn(), onGuardChange: vi.fn(),
  agents: { default_id: 'builtin', solving_available: true, items: [{ id: 'builtin', revision: 1,
    name: '默认模型', model: 'test', builtin: true, enabled: true, credential_ready: true }] },
};

it('provides separate settings navigation and model selection outside the chat composer', () => {
  const html = renderToStaticMarkup(<SettingsPage {...props} />);
  expect(html).toContain('返回对话');
  expect(html).toContain('模型与 Agents');
  expect(html).toContain('策略与 Skills');
  expect(html).toContain('默认模型');
  expect(html).not.toContain('role="dialog"');
  expect(html).not.toContain('数学问题');
});

it('locks task preferences while a task is active', () => {
  const html = renderToStaticMarkup(<SettingsPage {...props} locked />);
  expect(html.match(/<select[^>]*disabled/g)).toHaveLength(2);
});

it('embeds configuration as a page region and reports unsupported capabilities', () => {
  const html = renderToStaticMarkup(<SettingsPage {...props} section="agents" />);
  expect(html).toContain('role="region"');
  expect(html).not.toContain('aria-modal');
  const unavailable = renderToStaticMarkup(<SettingsPage {...props} section="library" health={{ ...props.health, custom_library: false }} />);
  expect(unavailable).toContain('当前服务未开放策略与领域手册管理');
});

it('manages existing resources instead of the legacy custom library', () => {
  const html = renderToStaticMarkup(<SettingsPage {...props} section="library"
    health={{ ...props.health, knowledge_resources: true, custom_library: false }} />);
  expect(html).toContain('搜索资源');
  expect(html).toContain('已有资源');
  expect(html).not.toContain('新增知识条目');
  expect(html).not.toContain('自定义知识');
});

import { ArrowLeft, BookOpen, Cpu, MessageSquare, Settings, Sigma } from 'lucide-react';
import AgentsPanel from './AgentsPanel';
import ResourcesPanel from './ResourcesPanel';
import type { AgentCatalog, Health, ResponseStyle } from './api';

export type SettingsSection = 'general' | 'agents' | 'library';

interface Props {
  section: SettingsSection;
  health: Health | null;
  agents?: AgentCatalog;
  agentId: string;
  responseStyle: ResponseStyle;
  locked: boolean;
  agentsError: string;
  onAgentChange: (id: string) => void;
  onStyleChange: (style: ResponseStyle) => void;
  onAgentsChange: (catalog: AgentCatalog) => void;
  onNavigate: (section?: SettingsSection) => void;
  onGuardChange: (guard: () => boolean) => void;
}

export default function SettingsPage(props: Props) {
  const { section, health, onNavigate, onGuardChange } = props;
  return <div className="settings-page">
    <aside className="settings-sidebar">
      <div className="brand"><span className="brand-mark"><Sigma size={21} /></span><span>MathS-Agent</span></div>
      <button className="settings-back" onClick={() => onNavigate()}><ArrowLeft size={17} />返回对话</button>
      <div className="settings-nav-heading"><Settings size={14} />设置</div>
      <nav aria-label="设置导航">
        {([
          ['general', MessageSquare, '对话偏好'],
          ['agents', Cpu, '模型与 Agents'],
          ['library', BookOpen, '策略与 Skills'],
        ] as const).map(([id, Icon, label]) => <button key={id}
          aria-current={section === id ? 'page' : undefined}
          onClick={() => onNavigate(id)}><Icon size={17} />{label}</button>)}
      </nav>
      <span className="settings-product">MathS-Agent · 设置</span>
    </aside>
    <main className="settings-main">
      <header className="settings-topbar"><span>设置</span><span>/</span>
        <span>{section === 'general' ? '对话偏好' : section === 'agents' ? '模型与 Agents' : '策略与 Skills'}</span>
      </header>
      <div className="settings-content" key={section}>
        {section === 'general' ? <section className="preferences" aria-labelledby="preferences-heading">
          <header><h1 id="preferences-heading">对话偏好</h1></header>
          <div className="preference-row"><label htmlFor="response-style">解答方式</label>
            <select id="response-style" value={props.responseStyle}
              disabled={props.locked || !health?.response_styles?.includes('auto')}
              onChange={event => props.onStyleChange(event.target.value as ResponseStyle)}>
              <option value="auto">按问题要求</option><option value="answer">仅答案</option>
              <option value="brief">简要过程</option><option value="detailed">详细讲解</option>
            </select></div>
          {health?.solve_agents && <div className="preference-row"><label htmlFor="selected-agent">解题模型</label>
            <select id="selected-agent" value={props.agentId} disabled={props.locked || !props.agents}
              onChange={event => props.onAgentChange(event.target.value)}>
              {!props.agents && <option value="">正在载入</option>}
              {props.agents?.items.filter(item => item.enabled).map(item => <option key={item.id} value={item.id}
                disabled={!item.credential_ready || (!props.agents?.solving_available && !item.builtin)}>
                {item.name}{item.id === props.agents?.default_id ? '（默认）' : ''}{!item.credential_ready ? '（缺少凭据）' : ''}
              </option>)}
            </select></div>}
          {props.agentsError && <p className="message-error" role="alert">{props.agentsError}</p>}
        </section> : !health ? <p className="settings-unavailable" role="status">正在连接服务</p>
          : section === 'agents' ? health.solve_agents
            ? <AgentsPanel embedded onClose={() => onNavigate()} onChange={props.onAgentsChange} onGuardChange={onGuardChange} />
            : <p className="settings-unavailable">当前服务未开放模型配置</p>
          : health.knowledge_resources
            ? <ResourcesPanel onGuardChange={onGuardChange} />
            : <p className="settings-unavailable">当前服务未开放策略与领域手册管理</p>}
      </div>
    </main>
  </div>;
}

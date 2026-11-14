import { useEffect, useRef, useState } from 'react';
import { Cpu, FlaskConical, Plus, RotateCcw, Save, Search, Star, Trash2, X } from 'lucide-react';
import { agentCommand, ApiError, errorMessage, getAgents, saveAgent, type AgentCatalog, type AgentDraft, type SolveAgent } from './api';

const empty = (): AgentDraft => ({ name: '', provider: 'compatible', api_url: '', model: '', credential_env: '',
  temperature: .3, max_tokens: 8192, timeout: 240, preference: '', enabled: true });
const draftOf = (item: SolveAgent): AgentDraft => ({ ...empty(), ...Object.fromEntries(
  Object.keys(empty()).map(key => [key, item[key as keyof SolveAgent] ?? empty()[key as keyof AgentDraft]])) });

export default function AgentsPanel({ onClose, onChange }: { onClose: () => void; onChange: (catalog: AgentCatalog) => void }) {
  const [catalog, setCatalog] = useState<AgentCatalog>();
  const [selected, setSelected] = useState<SolveAgent>();
  const [draft, setDraft] = useState<AgentDraft>(empty());
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const panel = useRef<HTMLElement>(null);
  const dirty = !selected?.builtin && JSON.stringify(draft) !== JSON.stringify(selected ? draftOf(selected) : empty());
  const canLeave = () => !busy && (!dirty || window.confirm('尚有未保存的修改，是否放弃？'));
  const close = () => { if (canLeave()) onClose(); };
  const apply = (value: AgentCatalog) => { setCatalog(value); onChange(value); };
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const controller = new AbortController();
    void getAgents(controller.signal).then(apply).catch(failure => { if (!controller.signal.aborted) setError(errorMessage(failure)); });
    return () => { controller.abort(); previous?.focus(); };
  }, []);
  const choose = (item?: SolveAgent) => {
    if (!canLeave()) return;
    setSelected(item); setDraft(item && !item.builtin ? draftOf(item) : empty()); setError(''); setNotice('');
  };
  async function reload() {
    if (!canLeave()) return;
    setBusy(true); setError('');
    try { const value = await getAgents(); apply(value); setSelected(undefined); setDraft(empty()); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  async function save() {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const item = await saveAgent(draft, selected);
      setSelected(item); setDraft(draftOf(item));
      apply(await getAgents()); setNotice('已保存');
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  async function command(action: 'delete' | 'default' | 'test') {
    if (!selected || busy) return;
    if (dirty) { setError('请先保存配置。'); return; }
    if (action === 'delete' && !window.confirm(`删除“${selected.name}”？`)) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await agentCommand(selected, action);
      if (action === 'test' && !result.ok) throw new ApiError(result.error_code || 'model_call_failed', 0);
      if (action === 'delete') { setSelected(undefined); setDraft(empty()); }
      apply(await getAgents());
      setNotice(action === 'test' ? '连接测试通过' : action === 'default' ? '已设为默认' : '已删除');
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  const set = <K extends keyof AgentDraft>(key: K, value: AgentDraft[K]) => setDraft(previous => ({ ...previous, [key]: value }));
  return <div className="library-backdrop" onClick={close}>
    <aside className="library-panel agents-panel" role="dialog" aria-modal="true" aria-labelledby="agents-heading" ref={panel}
      onClick={event => event.stopPropagation()} onKeyDown={event => {
        if (event.key === 'Escape') { event.stopPropagation(); close(); }
        if (event.key === 'Tab') {
          const controls = Array.from(panel.current!.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled)'))
            .filter(element => element.getClientRects().length > 0);
          const first = controls[0], last = controls.at(-1);
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
          if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
        }
      }}>
      <header className="library-header"><h2 id="agents-heading"><Cpu size={18} />模型与 Agents</h2><div>
        <button className="icon-button" disabled={busy} title="刷新" aria-label="刷新 Agents" onClick={() => void reload()}><RotateCcw size={17} /></button>
        <button className="icon-button" disabled={busy} title="关闭" aria-label="关闭模型配置" onClick={close}><X size={19} /></button>
      </div></header>
      <div className="library-scroll">
        <div className="library-search"><Search size={16} /><input aria-label="搜索 Agent" placeholder="搜索名称或模型" value={query} onChange={event => setQuery(event.target.value)} />
          <button className="icon-button" title="新增 Agent" aria-label="新增 Agent" disabled={busy} onClick={() => choose()}><Plus size={18} /></button></div>
        <div className="library-list">
          {!catalog && !error && <p className="muted">正在载入</p>}
          {catalog?.items.filter(item => `${item.name} ${item.model}`.toLowerCase().includes(query.toLowerCase())).map(item =>
            <button className={`library-item ${selected?.id === item.id ? 'selected' : ''}`} disabled={busy} key={item.id} onClick={() => choose(item)}>
              <span>{item.name}{catalog.default_id === item.id && <Star size={12} aria-label="默认" />}<small>{item.model} · v{item.revision}</small></span>
              <span className={item.enabled ? 'library-enabled' : 'muted'}>{!item.enabled ? '已停用' : item.credential_ready ? '已启用' : '缺少凭据'}</span>
            </button>)}
        </div>
        <form className="library-editor" onSubmit={event => { event.preventDefault(); void save(); }}>
          <div className="library-editor-heading"><h3>{selected?.builtin ? selected.name : selected ? '编辑 Solve Agent' : '新增 Solve Agent'}</h3>
            {!selected?.builtin && <label className="library-toggle"><input type="checkbox" checked={draft.enabled} disabled={busy} onChange={event => set('enabled', event.target.checked)} />启用</label>}</div>
          {!selected?.builtin && <fieldset disabled={busy || !catalog} className="agent-fields">
            <label>名称<input required maxLength={80} value={draft.name} onChange={event => set('name', event.target.value)} /></label>
            <label>接口类型<select value={draft.provider} onChange={event => set('provider', event.target.value as AgentDraft['provider'])}>
              <option value="compatible">兼容 Chat Completions</option><option value="intern">Intern</option></select></label>
            <label>API 地址<input required type="url" maxLength={500} placeholder="https://api.example.com/v1/chat/completions" value={draft.api_url} onChange={event => set('api_url', event.target.value)} /></label>
            <label>模型名称<input required maxLength={160} placeholder="模型 ID" value={draft.model} onChange={event => set('model', event.target.value)} /></label>
            <label>凭据环境变量名<input maxLength={100} pattern="([A-Z][A-Z0-9_]*_API_KEY)?" placeholder="CUSTOM_API_KEY" autoComplete="off" value={draft.credential_env} onChange={event => set('credential_env', event.target.value)} /></label>
            <div className="agent-numbers">
              <label>Temperature<input type="number" min={0} max={2} step={.1} required value={draft.temperature} onChange={event => set('temperature', Number(event.target.value))} /></label>
              <label>最大输出 Token<input type="number" min={256} max={65536} required value={draft.max_tokens} onChange={event => set('max_tokens', Number(event.target.value))} /></label>
              <label>超时（秒）<input type="number" min={10} max={600} required value={draft.timeout} onChange={event => set('timeout', Number(event.target.value))} /></label>
            </div>
            <label>求解偏好<textarea maxLength={1500} value={draft.preference} onChange={event => set('preference', event.target.value)} /></label>
          </fieldset>}
          <div className="library-actions">
            <div className="agent-actions">
              {selected && <>
                <button type="button" className="icon-button" disabled={busy || !selected.enabled || !catalog?.solving_available} title="测试连接（发送一次短请求）" aria-label="测试连接" onClick={() => void command('test')}><FlaskConical size={17} /></button>
                <button type="button" className="icon-button" disabled={busy || !selected.enabled || (!catalog?.solving_available && !selected.builtin) || catalog?.default_id === selected.id} title="设为默认" aria-label="设为默认" onClick={() => void command('default')}><Star size={17} /></button>
                {!selected.builtin && <button type="button" className="icon-button" disabled={busy} title="删除" aria-label="删除 Agent" onClick={() => void command('delete')}><Trash2 size={17} /></button>}
              </>}
            </div>
            {!selected?.builtin && <button className="secondary" type="submit" disabled={busy || !catalog}><Save size={15} />{busy ? '处理中' : '保存'}</button>}
          </div>
          {error && <p className="message-error" role="alert">{error}</p>}
          {notice && <p className="library-saved" role="status">{notice}</p>}
        </form>
      </div>
    </aside>
  </div>;
}

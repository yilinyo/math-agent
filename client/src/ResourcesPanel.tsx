import { useEffect, useRef, useState } from 'react';
import { BookOpen, ChevronLeft, ChevronRight, Eye, Pencil, Plus, RotateCcw, Save, Search, X } from 'lucide-react';
import { createStrategy, errorMessage, getResource, getResources, saveResource,
  type ResourceDetail, type ResourceKind, type ResourcePage } from './api';
import MathMarkdown from './MathMarkdown';

const strategyTemplate = () => JSON.stringify({ name: '', tags: [''], description: '',
  applicability: [''], steps: [{ step: '', detail: '' }], example: { problem: '', solution: '' } }, null, 2);

export default function ResourcesPanel({ onGuardChange }: { onGuardChange: (guard: () => boolean) => void }) {
  const [kind, setKind] = useState<ResourceKind>('strategy');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ResourcePage>();
  const [selected, setSelected] = useState<ResourceDetail>();
  const [creating, setCreating] = useState(false);
  const [content, setContent] = useState('');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const detailRequest = useRef<AbortController>();
  const dirty = creating || (!!selected && content !== selected.content);
  const canLeave = () => !busy && (!dirty || window.confirm('尚有未保存的修改，是否放弃？'));
  useEffect(() => {
    onGuardChange(() => !busy && (!dirty || window.confirm('尚有未保存的修改，是否放弃？')));
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (busy || dirty) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => { onGuardChange(() => true); window.removeEventListener('beforeunload', beforeUnload); };
  }, [busy, dirty, onGuardChange]);
  useEffect(() => () => detailRequest.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setPage(undefined);
    const timer = setTimeout(() => {
      void getResources(kind, query, offset, controller.signal).then(result => {
        if (!controller.signal.aborted) { setPage(result); setLoading(false); }
      }).catch(failure => {
        if (!controller.signal.aborted) { setError(errorMessage(failure)); setLoading(false); }
      });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [kind, query, offset, refresh]);
  function reset(nextKind: ResourceKind) {
    if (!canLeave()) return;
    detailRequest.current?.abort(); setSelected(undefined); setContent('');
    setCreating(false);
    setKind(nextKind); setQuery(''); setOffset(0); setError(''); setNotice(''); setEditing(false);
    setRefresh(value => value + 1);
  }
  async function select(id: string) {
    if (!canLeave()) return;
    detailRequest.current?.abort();
    const controller = new AbortController(); detailRequest.current = controller;
    setSelected(undefined); setContent(''); setError(''); setNotice(''); setEditing(false);
    setCreating(false);
    try {
      const item = await getResource(kind, id, controller.signal);
      if (!controller.signal.aborted) { setSelected(item); setContent(item.content); }
    } catch (failure) { if (!controller.signal.aborted) setError(errorMessage(failure)); }
  }
  function startCreate() {
    if (!canLeave()) return;
    detailRequest.current?.abort(); setSelected(undefined); setCreating(true);
    setContent(strategyTemplate()); setEditing(true); setError(''); setNotice('');
  }
  async function save() {
    if ((!selected && !creating) || busy || !dirty || !content.trim()) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const item = creating ? await createStrategy(content) : await saveResource(selected!, content);
      if (creating) { setQuery(item.title); setOffset(0); }
      setSelected(item); setContent(item.content); setNotice(creating ? `已新增 · ID ${item.id}` : '已保存');
      setCreating(false);
      setRefresh(value => value + 1);
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  return <section className="resources-panel" aria-labelledby="resources-heading">
    <header className="library-header"><h1 id="resources-heading"><BookOpen size={18} />策略与 Skills</h1>
      <div className="resource-actions">
        {kind === 'strategy' && <button className="icon-button" title="新增策略" aria-label="新增策略" disabled={busy} onClick={startCreate}><Plus size={18} /></button>}
        <button className="icon-button" title="刷新资源" aria-label="刷新资源" disabled={busy} onClick={() => reset(kind)}><RotateCcw size={17} /></button>
      </div></header>
    <div className="library-tabs" role="tablist" aria-label="资源类型">
      <button role="tab" aria-selected={kind === 'strategy'} disabled={busy} onClick={() => reset('strategy')}>策略</button>
      <button role="tab" aria-selected={kind === 'skill'} disabled={busy} onClick={() => reset('skill')}>Skills</button>
    </div>
    <div className="resource-status" role="status">{page && <>
      {kind === 'skill' ? '领域手册' : '策略总数'}：{page.corpus_total}
      {kind === 'strategy' && <span>词法索引：{page.indexes.lexical ? '已存在' : '缺失'} · 向量索引：{page.indexes.vector ? '已存在' : '缺失'}</span>}
    </>}</div>
    {error && <p className="message-error" role="alert">{error}</p>}
    {notice && <p className="resource-notice" role="status">{notice}</p>}
    <div className="resources-layout">
      <div className="resources-catalog">
        <label className="library-search"><Search size={16} /><input aria-label="搜索资源" placeholder="搜索名称、领域、ID"
          value={query} disabled={busy} onChange={event => { setQuery(event.target.value); setOffset(0); }} /></label>
        <div className="resources-list" aria-label="已有资源" aria-busy={loading}>
          {loading ? <p role="status">正在载入</p> : page?.items.length === 0 ? <p>没有匹配的资源</p>
            : page?.items.map(item => <button key={item.id} className={selected?.id === item.id ? 'selected' : ''}
              aria-pressed={selected?.id === item.id} disabled={busy} onClick={() => void select(item.id)}>
              <strong>{item.title}</strong><span>{kind === 'strategy' ? `ID ${item.id} · ` : ''}{item.category}</span>
            </button>)}
        </div>
        <div className="resources-pagination">
          <button className="icon-button" title="上一页" aria-label="上一页" disabled={busy || loading || !offset} onClick={() => setOffset(Math.max(0, offset - 40))}><ChevronLeft size={17} /></button>
          <span>{page ? `${offset + (page.total ? 1 : 0)}–${Math.min(offset + 40, page.total)} / ${page.total}` : '…'}</span>
          <button className="icon-button" title="下一页" aria-label="下一页" disabled={busy || loading || page?.next_offset == null} onClick={() => setOffset(page!.next_offset!)}><ChevronRight size={17} /></button>
        </div>
      </div>
      <div className="resource-detail">
        {!selected && !creating ? <p className="resource-empty">{kind === 'skill' ? '选择领域手册' : '选择策略'}</p> : <>
          <header className="resource-detail-header"><div><h2>{creating ? '新增策略' : selected!.title}</h2><code>{creating ? 'strategy_data/strategy_meta.json' : selected!.source}</code></div>
            <div className="resource-actions">
              {creating && <button className="icon-button" title="取消新增" aria-label="取消新增" disabled={busy} onClick={() => reset(kind)}><X size={17} /></button>}
              <button className="icon-button" title={editing ? '预览' : '编辑'} aria-label={editing ? '预览资源' : '编辑资源'} disabled={busy} onClick={() => setEditing(value => !value)}>{editing ? <Eye size={17} /> : <Pencil size={17} />}</button>
              <button className="resource-save" disabled={busy || !dirty || !content.trim()} onClick={() => void save()}><Save size={16} />{busy ? '保存中…' : '保存'}</button>
            </div></header>
          {editing ? <textarea className="resource-source" aria-label={kind === 'skill' ? 'Skill Markdown 内容' : '策略 JSON 内容'} value={content} disabled={busy} maxLength={1000000}
            spellCheck={false} onChange={event => setContent(event.target.value)} />
            : <div className="resource-preview">{kind === 'skill' ? <MathMarkdown content={content} /> : <StrategyPreview content={content} />}</div>}
        </>}
      </div>
    </div>
  </section>;
}

function StrategyPreview({ content }: { content: string }) {
  try {
    const card = JSON.parse(content);
    return <><MathMarkdown content={[card.description, ...(card.applicability || []).map((x: string) => `- ${x}`),
      ...(card.steps || []).map((x: { step: string; detail: string }) => `### ${x.step}\n${x.detail}`)].join('\n\n')} />
      <details><summary>完整策略数据</summary><pre>{content}</pre></details></>;
  } catch { return <pre>{content}</pre>; }
}

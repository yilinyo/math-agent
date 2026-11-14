import { useEffect, useRef, useState } from 'react';
import { BookOpen, Eye, FileUp, Pencil, Plus, RotateCcw, Save, Search, Trash2, X } from 'lucide-react';
import { deleteLibrary, errorMessage, getLibrary, saveLibrary, type LibraryDraft, type LibraryItem } from './api';
import MathMarkdown from './MathMarkdown';

const empty = (kind: LibraryDraft['kind']): LibraryDraft => ({ kind, title: '', category: '', keywords: '', content: '', enabled: true });
const draftOf = (item: LibraryItem): LibraryDraft => ({ kind: item.kind, title: item.title,
  category: item.category, keywords: item.keywords, content: item.content, enabled: item.enabled });

export default function LibraryPanel({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [kind, setKind] = useState<LibraryDraft['kind']>('strategy');
  const [draft, setDraft] = useState(empty('strategy'));
  const [selected, setSelected] = useState<LibraryItem>();
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');
  const [preview, setPreview] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(selected ? draftOf(selected) : empty(kind));
  const canLeave = () => !busy && (!dirty || window.confirm('尚有未保存的修改，是否放弃？'));
  const close = () => { if (canLeave()) onClose(); };
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const controller = new AbortController();
    void getLibrary(controller.signal).then(result => { setItems(result.items); setLoaded(true); })
      .catch(failure => { if (!controller.signal.aborted) setError(errorMessage(failure)); });
    return () => { controller.abort(); previous?.focus(); };
  }, []);
  const reset = (nextKind: LibraryDraft['kind'], item?: LibraryItem) => {
    if (!canLeave()) return;
    setKind(nextKind); setSelected(item); setDraft(item ? draftOf(item) : empty(nextKind));
    setError(''); setSaved(''); setPreview(false); setConfirmDelete(false);
  };
  async function reload() {
    setBusy(true); setError('');
    try { setItems((await getLibrary()).items); setLoaded(true); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  async function save() {
    if (busy || !loaded || !draft.title.trim() || !draft.content.trim()) return;
    setBusy(true); setError(''); setSaved('');
    try {
      const item = await saveLibrary(draft, selected);
      setItems(previous => [item, ...previous.filter(row => row.id !== item.id)]);
      setSelected(item); setDraft(draftOf(item)); setSaved('已保存');
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!selected || busy) return;
    setBusy(true); setError('');
    try {
      await deleteLibrary(selected);
      setItems(previous => previous.filter(row => row.id !== selected.id));
      setSelected(undefined); setDraft(empty(kind)); setConfirmDelete(false); setSaved('已删除');
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  const filtered = items.filter(item => item.kind === kind
    && `${item.title} ${item.category} ${item.keywords} ${item.content}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <div className="library-backdrop" onClick={close}>
    <aside className="library-panel" role="dialog" aria-modal="true" aria-labelledby="library-heading" ref={panel}
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
      <header className="library-header"><h2 id="library-heading"><BookOpen size={18} />自定义知识</h2>
        <div><button className="icon-button" disabled={busy} title="刷新列表" aria-label="刷新知识列表" onClick={() => void reload()}><RotateCcw size={17} /></button>
          <button className="icon-button" disabled={busy} title="关闭" aria-label="关闭知识面板" onClick={close}><X size={19} /></button></div></header>
      <div className="library-tabs" role="tablist" aria-label="知识类型">
        <button role="tab" aria-selected={kind === 'strategy'} aria-controls="library-list" disabled={busy} onClick={() => reset('strategy')}>策略 <span>{items.filter(item => item.kind === 'strategy').length}</span></button>
        <button role="tab" aria-selected={kind === 'skill'} aria-controls="library-list" disabled={busy} onClick={() => reset('skill')}>Skills <span>{items.filter(item => item.kind === 'skill').length}</span></button>
      </div>
      <div className="library-scroll">
        <div className="library-search"><Search size={16} /><input aria-label="搜索自定义知识" placeholder="搜索标题、分类、关键词" value={query} onChange={event => setQuery(event.target.value)} />
          <button className="icon-button" disabled={busy} title={kind === 'skill' ? '新增 Skill' : '新增策略'} aria-label="新增知识条目" onClick={() => reset(kind)}><Plus size={18} /></button></div>
        <div id="library-list" role="tabpanel" className="library-list">
          {!loaded && !error && <p className="muted">正在载入</p>}
          {loaded && !filtered.length && <p className="muted">{query ? '没有匹配的条目' : kind === 'skill' ? '暂无自定义 Skill' : '暂无自定义策略'}</p>}
          {filtered.map(item => <button key={item.id} disabled={busy} className={`library-item ${selected?.id === item.id ? 'selected' : ''}`} onClick={() => reset(kind, item)}>
            <span>{item.title}<small>{item.category || '未分类'}</small></span><span className={item.enabled ? 'library-enabled' : 'muted'}>{item.enabled ? '已启用' : '已停用'}</span>
          </button>)}
        </div>
        <form className="library-editor" onSubmit={event => { event.preventDefault(); void save(); }}>
          <div className="library-editor-heading"><h3>{selected ? '编辑' : '新增'}{kind === 'skill' ? ' Skill' : '策略'}</h3>
            <label className="library-toggle"><input type="checkbox" checked={draft.enabled} disabled={busy} onChange={event => setDraft({ ...draft, enabled: event.target.checked })} />启用</label></div>
          <label>标题<input required maxLength={120} disabled={busy} value={draft.title} onChange={event => setDraft({ ...draft, title: event.target.value })} /></label>
          <label>分类<input maxLength={80} disabled={busy} value={draft.category} onChange={event => setDraft({ ...draft, category: event.target.value })} /></label>
          <label>关键词<input maxLength={300} disabled={busy} value={draft.keywords} onChange={event => setDraft({ ...draft, keywords: event.target.value })} /></label>
          <div className="library-content-heading"><span>内容</span><div>
            <button className="icon-button" type="button" title="导入 Markdown" aria-label="导入 Markdown" disabled={busy} onClick={() => file.current?.click()}><FileUp size={16} /></button>
            <button className="icon-button" type="button" disabled={busy} title={preview ? '编辑内容' : '预览内容'} aria-label={preview ? '编辑内容' : '预览内容'} onClick={() => setPreview(!preview)}>{preview ? <Pencil size={16} /> : <Eye size={16} />}</button>
          </div></div>
          <input ref={file} hidden type="file" accept=".md,.markdown,text/markdown" onChange={async event => {
            const chosen = event.target.files?.[0]; event.target.value = '';
            if (!chosen) return;
            if (chosen.size > 50000 || !/\.(md|markdown)$/i.test(chosen.name)) { setError('请选择不超过 50 KB 的 Markdown 文件。'); return; }
            setBusy(true);
            try {
              const content = new TextDecoder('utf-8', { fatal: true }).decode(await chosen.arrayBuffer());
              if (content.length > 10000) { setError('内容不能超过 10,000 字符。'); return; }
              setDraft(previous => ({ ...previous, content, title: previous.title || chosen.name.replace(/\.(md|markdown)$/i, '').slice(0, 120) }));
              setError(''); setPreview(false); setSaved('');
            } catch { setError('无法读取文件，请使用 UTF-8 编码的 Markdown。'); }
            finally { setBusy(false); }
          }} />
          {preview ? <div className="library-preview"><MathMarkdown content={draft.content} /></div>
            : <textarea aria-label="知识内容" required maxLength={10000} disabled={busy} value={draft.content} onChange={event => setDraft({ ...draft, content: event.target.value })} />}
          <small className="library-count">{draft.content.length.toLocaleString()} / 10,000</small>
          {error && <p className="message-error" role="alert">{error}</p>}
          {saved && !dirty && <p className="library-saved" role="status">{saved}</p>}
          <div className="library-actions"><button className="secondary" type="submit" disabled={busy || !loaded || !draft.title.trim() || !draft.content.trim() || !dirty}><Save size={16} />{busy ? '处理中' : '保存'}</button>
            {selected && <button className="icon-button" type="button" title="删除条目" aria-label="删除条目" disabled={busy} onClick={() => setConfirmDelete(!confirmDelete)}><Trash2 size={17} /></button>}</div>
          {confirmDelete && <div className="library-delete-confirm"><span>删除“{selected?.title}”？</span><button type="button" className="secondary" disabled={busy} onClick={() => void remove()}>确认删除</button></div>}
        </form>
      </div>
    </aside>
  </div>;
}

import { useMemo, useState } from 'react';
import { Code2, ChevronDown } from 'lucide-react';
import { matchesTrace, publicTraceEvent, traceRows } from '../../agent_platform/static/trace-format.js';
import type { TraceEvent } from './api';
import { formatDuration } from './timing';

export default function TraceLog({ events, query, problemsOnly, active }: {
  events: TraceEvent[]; query: string; problemsOnly: boolean; active: boolean;
}) {
  const [limit, setLimit] = useState(30);
  const rows = useMemo(() => traceRows(events).map(row => !active && row.view.level === 'running'
    ? { ...row, view: { ...row.view, level: 'warning' } } : row)
    .filter(row => matchesTrace(row, query, problemsOnly)), [events, query, problemsOnly, active]);
  return <>
    <ol className="trace-log-list">
      {rows.slice(0, limit).map(row => {
        const level = row.view.level === 'running' && !active ? 'warning' : row.view.level;
        return <li key={row.id} className={`trace-row trace-${level}`}>
          <div className="trace-row-heading"><time>{Number.isFinite(Date.parse(row.startedAt))
            ? new Date(row.startedAt).toLocaleTimeString('zh-CN', { hour12: false }) : '时间未记录'}</time>
            <span>{row.view.title}</span>
            {row.durationMs !== null && <small>{formatDuration(row.durationMs)}</small>}</div>
          {row.events.at(-1)?.event_type.endsWith('.started') && row.events[0].event_type !== 'stage.started'
            && !active && <p className="muted">未记录此操作的结束事件。</p>}
          {!!row.view.details.length && <dl className="trace-fields">{row.view.details.map(([label, value], index) =>
            <div key={index}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
          <details className="trace-raw"><summary><Code2 size={12} />事件字段 · {row.events.length}</summary>
            <pre>{JSON.stringify(row.events.map(publicTraceEvent), null, 2)}</pre></details>
        </li>;
      })}
    </ol>
    {!rows.length && <p className="muted">没有匹配的运行记录。</p>}
    {rows.length > limit && <button type="button" className="trace-more" onClick={() => setLimit(value => value + 30)}>
      <ChevronDown size={14} />加载更多（剩余 {rows.length - limit} 条）</button>}
  </>;
}

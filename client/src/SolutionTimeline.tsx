import { useEffect, useState } from 'react';
import { Activity, BrainCircuit, Check, ChevronRight, LoaderCircle, Search, TriangleAlert } from 'lucide-react';
import { stageNames, terminal, watchTask, type Task } from './api';
import { timelineFromEvent, type TimelineState } from './timelineState';
import { formatDuration } from './timing';
import MathMarkdown from './MathMarkdown';
import TraceLog from './TraceLog';
import { matchesTrace, stageLabels, traceRows } from '../../agent_platform/static/trace-format.js';

export default function SolutionTimeline({ task, timeline, now }: { task: Task; timeline?: TimelineState; now: number }) {
  const [history, setHistory] = useState<{ taskId: string; timeline?: TimelineState }>();
  const [connectionError, setConnectionError] = useState(false);
  const [query, setQuery] = useState('');
  const [problemsOnly, setProblemsOnly] = useState(false);
  useEffect(() => {
    if (timeline) return;
    setConnectionError(false);
    return watchTask(task.session_id, task.id, {
      task: () => {}, connection: () => {}, error: () => setConnectionError(true),
      event: event => setHistory(previous => ({ taskId: task.id,
        timeline: timelineFromEvent(previous?.taskId === task.id ? previous.timeline : undefined, event) })),
    });
  }, [task.id, task.session_id, !!timeline]);
  const current = timeline || (history?.taskId === task.id ? history.timeline : undefined);
  const active = !terminal(task.status);
  if (!current?.stages.length) return connectionError ? <p className="muted">过程记录暂不可用。</p> : null;
  const filtering = !!query.trim() || problemsOnly;
  const visibleStages = new Set(current.stages.filter(stage => !filtering || traceRows(stage.logs)
    .some(row => matchesTrace(row, query, problemsOnly))).map(stage => stage.id));
  const end = task.finished_at || task.stopped_at;
  return <details className="solution-timeline" open data-testid="solution-timeline">
    <summary><ChevronRight size={14} /><Activity size={15} />{active ? '解题进行中' : '解题记录'}</summary>
    <div className="trace-filters">
      <label className="trace-search"><Search size={14} /><input aria-label="搜索运行记录" placeholder="搜索运行记录"
        value={query} onChange={event => setQuery(event.target.value)} /></label>
      <label><input type="checkbox" checked={problemsOnly} onChange={event => setProblemsOnly(event.target.checked)} />仅异常与待确认</label>
    </div>
    <ol aria-label="解题过程">
      {current.stages.map((stage, index) => {
        if (!visibleStages.has(stage.id)) return null;
        const durationEnd = stage.finishedAt || stage.stoppedAt || current.stages[index + 1]?.startedAt || end;
        const elapsed = (durationEnd ? Date.parse(durationEnd) : active ? now : NaN) - Date.parse(stage.startedAt);
        const content = stage.content.filter(item => item.content || item.kind === 'reasoning');
        const running = active && index === current.stages.length - 1 && !stage.finishedAt && !stage.stoppedAt;
        const passed = stage.outcome === 'pass' || stage.outcome === 'accepted';
        const warning = !!stage.outcome && !['completed', 'pass', 'accepted', 'succeeded'].includes(stage.outcome);
        const outcomes: Record<string, string> = { pass: '检查通过', accepted: '答案已接受', rejected: '验收未通过',
          needs_review: '检查发现问题', unverified: '尚未验证通过', recovered: '进入恢复流程', incomplete: '候选不完整',
          cancelled: '已取消', interrupted: '已中断', failed: '执行失败' };
        let round = current.stages.slice(0, index).reduce((total, row) =>
          total + row.content.filter(item => item.kind === 'solution' && item.content).length, 0);
        return <li key={stage.id} className={`${running ? 'is-active' : ''} ${warning ? 'has-warning' : ''}`}>
          <div className="timeline-heading">
            {running ? <LoaderCircle size={14} className="spin" /> : warning ? <TriangleAlert size={14} />
              : passed ? <Check size={14} /> : <Activity size={14} />}
            <span>{stageLabels[stage.node || ''] || stageNames[stage.stage] || '任务调度'}
              {!!stage.round && <small> · 第 {stage.round} 轮</small>}</span>
            <time>{Number.isFinite(elapsed) ? formatDuration(Math.max(0, elapsed)) : '耗时未知'}</time>
          </div>
          <p className={`timeline-outcome ${warning ? 'trace-warning' : passed ? 'trace-success' : ''}`}>
            {running ? '正在执行' : outcomes[stage.outcome || ''] || (stage.finishedAt ? '执行结束' : '未记录阶段结束')}
          </p>
          {!filtering && content.map(item => {
            if (item.kind === 'reasoning') return <details key={item.id} className="timeline-reasoning" open>
              <summary><BrainCircuit size={14} /><span>{item.title}</span><small>
                {item.truncated ? '已达展示上限' : item.interrupted || (!item.complete && !running) ? '已中断'
                  : item.complete ? '生成结束' : '正在思考'}
              </small></summary>
              {item.content ? <MathMarkdown content={item.content} /> : <p className="muted">
                {item.complete || item.interrupted || !running ? '未收到可展示内容。' : '正在接收思考内容。'}
              </p>}
            </details>;
            if (item.kind === 'solution') round++;
            return <section key={item.id} className="timeline-content">
              {item.kind === 'solution' ? <p className="timeline-draft-label">
                第 {round} 轮公开推导 · {item.complete ? '阶段草稿，以最终答案为准'
                  : running ? '正在生成，仍需核验' : '未完成草稿，以最终答案为准'}
              </p> : item.title && <h4>{item.title}</h4>}
              <MathMarkdown content={item.content} />
            </section>;
          })}
          {!filtering && !content.length && <p className="muted">{running ? '正在执行本阶段。' : '本阶段未记录单独的数学说明。'}</p>}
          {!!stage.logs.length && <details className="timeline-logs" open={filtering ? true : undefined}>
            <summary>运行记录 · {stage.logs.length}</summary>
            <TraceLog events={stage.logs} query={query} problemsOnly={problemsOnly} active={running} />
          </details>}
        </li>;
      })}
    </ol>
    {!visibleStages.size && <p className="muted">没有匹配的运行记录。</p>}
    {connectionError && <p className="muted">过程记录暂不可用。</p>}
  </details>;
}

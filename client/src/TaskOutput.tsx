import { ChevronRight, LoaderCircle } from 'lucide-react';
import { ApiError, errorMessage, stageNames, terminal, type Task } from './api';
import MathMarkdown from './MathMarkdown';
import { executionSummary, type LiveTaskView } from './taskStream';
import TaskTiming from './TaskTiming';
import { formatDuration } from './timing';
import SolutionTimeline from './SolutionTimeline';

interface Props { task?: Task; view?: LiveTaskView; error?: string; testId?: string; now?: number }

export default function TaskOutput({ task, view, error, testId = 'answer', now = Date.now() }: Props) {
  const active = !!task && !terminal(task.status);
  const summaries = (view?.events || []).flatMap(event => {
    const text = executionSummary(event);
    const ms = event.payload.duration_ms;
    const duration = typeof ms === 'number' && Number.isFinite(ms) && ms >= 0 ? ms : null;
    return text ? [{ sequence: event.sequence, text, duration }] : [];
  });
  const hasDraft = view?.timeline?.stages.some(stage => stage.content.some(item => item.kind === 'solution' && item.content));
  const preview = task?.status === 'running' && !(hasDraft && view?.stream?.preview) ? view?.stream?.text : undefined;
  const content = task?.final_response || preview;
  return <>
    {task?.solve_agent && <p className="task-agent"><span>{task.solve_agent.name}</span><span>{task.solve_agent.model} · v{task.solve_agent.revision}</span></p>}
    {task && <TaskTiming task={task} now={now} deliveryMs={active && !view?.stream?.preview ? view?.stream?.durationMs : undefined} />}
    {task && <SolutionTimeline task={task} timeline={view?.timeline} now={now} />}
    {!view?.timeline?.stages.length && summaries.length > 0 && <details className="execution-summary" open={active}>
      <summary><ChevronRight size={14} />执行摘要{active && <LoaderCircle size={13} className="spin" />}</summary>
      <ol>{summaries.map(item => <li key={item.sequence}>{item.text}
        {item.duration !== null && <small className="event-duration">{formatDuration(item.duration)}</small>}</li>)}</ol>
    </details>}
    {preview && view?.stream?.preview && <p className="muted" role="status">
      {view.stream.completed ? '待校验解答 · 正在校验' : '待校验解答 · 正在生成'}
    </p>}
    {task?.final_response && <p className="message-label">最终答案</p>}
    {content ? <div className={`answer${!task?.final_response ? ' streaming-answer' : ''}`} data-testid={testId}
      aria-busy={!task?.final_response}><MathMarkdown content={content} /></div>
      : error ? <p className="message-error" role="alert">{error}</p>
        : active ? <div className="waiting" role="status"><LoaderCircle size={16} className="spin" />
          <span>{task.status === 'queued' ? '等待执行' : task.status === 'cancelling' ? '正在取消' : stageNames[task.current_stage || 'system'] || '正在执行'}</span></div>
          : task?.status === 'cancelled' ? <p className="muted">任务已取消。</p>
            : task?.status === 'failed' ? <p className="message-error">{errorMessage(new ApiError(task.error_code || 'failed', 0))}</p>
              : task?.status === 'interrupted' ? <p className="muted">任务已中断。</p>
                : task?.status === 'succeeded' ? <p className="message-error">任务已完成，但未收到最终答案。</p>
                  : <div className="waiting"><LoaderCircle size={16} className="spin" />载入中</div>}
  </>;
}

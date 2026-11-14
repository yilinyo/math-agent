import { Clock3 } from 'lucide-react';
import type { Task } from './api';
import { formatDuration, taskTimings } from './timing';

export default function TaskTiming({ task, now, deliveryMs }: { task: Task; now: number; deliveryMs?: number }) {
  const timing = taskTimings(task, now);
  const delivery = timing.answer_delivery_ms ?? deliveryMs;
  return <div className="task-timing" data-testid="task-timing" aria-label="任务耗时">
    <span title="从接收任务到结束，包含排队与暂停"><Clock3 size={13} />总耗时 {formatDuration(timing.total_ms)}</span>
    {timing.queue_ms !== null && <span title="接收任务到首次开始执行">首次排队 {formatDuration(timing.queue_ms)}</span>}
    {timing.processing_ms !== null && <span title="首次执行到结束，包含中途暂停和答案发送">处理历时 {formatDuration(timing.processing_ms)}</span>}
    {delivery !== null && delivery !== undefined && <span>答案发送 {formatDuration(delivery)}</span>}
  </div>;
}

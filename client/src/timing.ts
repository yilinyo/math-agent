import { terminal, type Task, type TaskTiming } from './api';

const milliseconds = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
const timestamp = (value: string | null | undefined) => value && Number.isFinite(Date.parse(value)) ? Date.parse(value) : null;

export function taskTimings(task: Task, now: number): TaskTiming {
  const stopped = terminal(task.status);
  const end = stopped ? timestamp(task.finished_at) ?? timestamp(task.stopped_at) : now;
  const accepted = timestamp(task.accepted_at), started = timestamp(task.started_at);
  const duration = (start: number | null, finish: number | null) =>
    start === null || finish === null ? null : Math.max(0, finish - start);
  return {
    total_ms: (stopped ? milliseconds(task.timing?.total_ms) : null) ?? duration(accepted, end),
    queue_ms: (stopped ? milliseconds(task.timing?.queue_ms) : null) ?? duration(accepted, started ?? end),
    processing_ms: (stopped ? milliseconds(task.timing?.processing_ms) : null) ?? duration(started, end),
    answer_delivery_ms: milliseconds(task.timing?.answer_delivery_ms),
  };
}

export function formatDuration(value: number | null | undefined): string {
  if (milliseconds(value) === null) return '--';
  const ms = value as number;
  if (ms < 1000) return `${Math.round(ms)} 毫秒`;
  const seconds = Math.round(ms / 100) / 10;
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`;
  return `${Math.floor(seconds / 60)} 分 ${(seconds % 60).toFixed(1)} 秒`;
}

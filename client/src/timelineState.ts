import { type TraceEvent } from './api';
import { executionSummary } from './taskStream';

export interface TimelineContent {
  id: string; kind: 'summary' | 'solution'; title: string; content: string;
  nextIndex?: number; complete?: boolean;
}
export interface TimelineStage {
  id: number; stage: string; startedAt: string; finishedAt?: string;
  node?: string; round?: number; outcome?: string; stoppedAt?: string;
  content: TimelineContent[]; logs: TraceEvent[];
}
export interface TimelineState { sequence: number; stages: TimelineStage[] }

export function timelineFromEvent(previous: TimelineState | undefined, event: TraceEvent): TimelineState {
  const before = previous || { sequence: 0, stages: [] };
  if (event.sequence <= before.sequence) return before;
  const stages = [...before.stages];
  const state = { sequence: event.sequence, stages };
  if (['task.failed', 'task.cancelled', 'task.interrupted', 'task.succeeded'].includes(event.event_type)) {
    state.stages = stages.map(stage => stage.finishedAt || stage.stoppedAt ? stage : {
      ...stage, stoppedAt: event.created_at, outcome: event.event_type.slice(5), logs: [...stage.logs, event],
    });
    return state;
  }
  if (event.event_type === 'answer.discarded') {
    state.stages = stages.map(stage => ({ ...stage,
      content: stage.content.filter(item => item.id !== event.payload.stream_id) }));
    return state;
  }
  const preview = event.payload.preview === true;
  if (event.event_type.startsWith('answer.') && event.event_type === 'answer.started' && !preview) return state;
  let index = stages.map(stage => stage.stage).lastIndexOf(event.stage_id);
  if (event.event_type === 'stage.started' || (index < 0 && event.event_type === 'stage.explanation')) {
    stages.push({ id: event.sequence, stage: event.stage_id, startedAt: event.created_at, content: [], logs: [] });
    index = stages.length - 1;
  }
  if (index < 0) return state;
  const stage = { ...stages[index], content: [...stages[index].content], logs: [...stages[index].logs] };
  stages[index] = stage;
  const { stream_id: id, text, content, kind, title } = event.payload;
  if (event.event_type === 'stage.completed') stage.finishedAt = event.created_at;
  if (event.event_type === 'stage.context') {
    stage.node = typeof event.payload.node === 'string' ? event.payload.node : undefined;
    stage.round = typeof event.payload.round === 'number' ? event.payload.round : undefined;
  }
  if (event.event_type === 'stage.outcome' && typeof event.payload.status === 'string') stage.outcome = event.payload.status;
  if (event.event_type === 'answer.started' && preview && typeof id === 'string') {
    stage.content.push({ id, kind: 'solution', title: '', content: '', nextIndex: 0 });
  } else if (event.event_type === 'answer.delta' || event.event_type === 'answer.completed') {
    const position = stage.content.findIndex(item => item.id === id && item.nextIndex !== undefined);
    if (position >= 0) {
      const item = stage.content[position];
      if (event.event_type === 'answer.delta' && event.payload.index === item.nextIndex
          && typeof text === 'string' && item.content.length + text.length <= 1000000) {
        stage.content[position] = { ...item, content: item.content + text, nextIndex: item.nextIndex! + 1 };
      } else if (event.event_type === 'answer.completed' && event.payload.chunks === item.nextIndex) {
        stage.content[position] = { ...item, complete: true };
      }
    }
  } else if (event.event_type === 'stage.explanation' && typeof content === 'string' && content) {
    const item: TimelineContent = { id: `explanation-${event.sequence}`, kind: kind === 'solution' ? 'solution' : 'summary',
      title: typeof title === 'string' ? title : '', content, complete: true };
    // A stage result completes the latest streamed draft without duplicating that round.
    const last = stage.content.map(row => row.kind).lastIndexOf('solution');
    if (kind === 'solution' && last >= 0) stage.content[last] = { ...item, id: stage.content[last].id };
    else stage.content.push(item);
  }
  if (executionSummary(event)) stage.logs.push(event);
  return state;
}

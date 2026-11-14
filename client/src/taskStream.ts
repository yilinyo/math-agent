import { type Task, type TraceEvent } from './api';
import { describeEvent } from '../../agent_platform/static/trace-format.js';
import type { TimelineState } from './timelineState';

export interface AnswerStream {
  id: string; text: string; nextIndex: number; sequence: number;
  durationMs?: number;
  preview?: boolean; completed?: boolean;
}
export interface LiveTaskView { task?: Task; events: TraceEvent[]; stream?: AnswerStream; timeline?: TimelineState }

export function answerFromEvent(stream: AnswerStream | undefined, event: TraceEvent): AnswerStream | undefined {
  if (stream && event.sequence <= stream.sequence) return stream;
  if (event.event_type === 'task.resumed' || event.event_type === 'task.cancelled'
      || event.event_type === 'task.failed' || event.event_type === 'task.interrupted') return undefined;
  const { stream_id: id, text, index } = event.payload;
  if (event.event_type === 'answer.discarded' && id === stream?.id) return undefined;
  if (event.event_type === 'answer.started' && typeof id === 'string') {
    return { id, text: '', nextIndex: 0, sequence: event.sequence, preview: event.payload.preview === true };
  }
  if (event.event_type === 'answer.completed' && stream && id === stream.id
      && event.payload.chunks === stream.nextIndex && typeof event.payload.duration_ms === 'number'
      && Number.isSafeInteger(event.payload.duration_ms) && event.payload.duration_ms >= 0) {
    return { ...stream, durationMs: event.payload.duration_ms, sequence: event.sequence, completed: true };
  }
  if (event.event_type !== 'answer.delta' || !stream || id !== stream.id
      || index !== stream.nextIndex || typeof text !== 'string' || stream.text.length + text.length > 1000000) return stream;
  return { ...stream, text: stream.text + text, nextIndex: stream.nextIndex + 1, sequence: event.sequence };
}

// Describe public execution events only; model replies and prompts never enter this view.
export function executionSummary(event: TraceEvent): string | null {
  return describeEvent(event)?.title || null;
}

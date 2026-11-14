export interface TraceInput {
  sequence: number; stage_id: string; event_type: string; created_at: string; payload: Record<string, unknown>;
}
export interface TraceDescription { title: string; level: string; details: [string, string][] }
export interface TraceRow {
  id: number; stage: string; startedAt: string; endedAt?: string; durationMs: number | null;
  view: TraceDescription; events: TraceInput[];
}
export const stageLabels: Record<string, string>;
export const formatReasons: Record<string, string>;
export function describeEvent(event: TraceInput): TraceDescription | null;
export function traceRows(events: TraceInput[]): TraceRow[];
export function matchesTrace(row: TraceRow, query?: string, problemsOnly?: boolean): boolean;
export function publicTraceEvent(event: TraceInput): TraceInput;
export function traceStageGroups(events: TraceInput[]): {
  id: number; stage: string; startedAt: string; endedAt?: string; events: TraceInput[];
  node?: string; round?: number; outcome?: TraceDescription;
}[];

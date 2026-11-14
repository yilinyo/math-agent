export const STAGES = ['profile', 'retrieve', 'plan', 'solve', 'tool', 'verify', 'repair', 'finalize'] as const;
export const stageNames: Record<string, string> = {
  profile: '题意分析', retrieve: '策略检索', plan: '解题规划', solve: '推导求解',
  tool: '工具验证', verify: '独立审查', repair: '定向修复', finalize: '整理答案', system: '任务调度',
};
export const statusNames: Record<TaskStatus, string> = {
  queued: '等待执行', running: '正在解题', cancelling: '正在取消', cancelled: '已取消',
  succeeded: '已完成', failed: '执行失败', interrupted: '执行中断',
};
export type TaskStatus = 'queued' | 'running' | 'cancelling' | 'cancelled' | 'succeeded' | 'failed' | 'interrupted';
export type ResponseStyle = 'auto' | 'answer' | 'brief' | 'detailed';
export interface TaskTiming {
  total_ms: number | null; queue_ms: number | null; processing_ms: number | null; answer_delivery_ms: number | null;
}
export interface Task {
  solve_agent?: AgentSummary | null;
  id: string; session_id: string; status: TaskStatus; runtime_mode: string;
  current_stage: string | null; final_response: string | null; error_code: string | null;
  accepted_at: string; started_at: string | null; finished_at: string | null;
  deadline_at: string | null; queue_position: number; checkpoint_available: boolean;
  stopped_at?: string | null; timing?: TaskTiming;
  response_style?: ResponseStyle | null;
  question_source?: { batch_id: string; number: number; label: string; filename: string; page_start: number | null; page_end: number | null } | null;
}
export interface TraceEvent {
  task_id: string; session_id: string; sequence: number; stage_id: string;
  event_type: string; created_at: string; payload: Record<string, unknown>;
}
export interface Health { status: string; runtime_mode: string; storage: string; restart_durable: boolean; response_styles?: ResponseStyle[]; server_history?: boolean; document_search?: string; question_attachments?: boolean; question_submission?: string | null; custom_library?: boolean; solve_agents?: boolean; knowledge_resources?: boolean }
export type ResourceKind = 'skill' | 'strategy';
export interface ResourceSummary { id: string; title: string; category: string; source: string }
export interface ResourceDetail extends ResourceSummary { kind: ResourceKind; revision: string; content: string }
export interface ResourcePage { items: ResourceSummary[]; total: number; corpus_total: number; next_offset: number | null;
  indexes: { lexical: boolean; vector: boolean; embedding_dim?: number; embedding_model?: string } }
export interface AgentSummary { id: string; name: string; model: string; revision: number }
export interface AgentDraft { name: string; provider: 'intern' | 'compatible'; api_url: string; model: string; credential_env: string;
  temperature: number; max_tokens: number; timeout: number; preference: string; enabled: boolean }
export interface SolveAgent extends AgentSummary { builtin: boolean; enabled: boolean; credential_ready: boolean;
  provider?: AgentDraft['provider']; api_url?: string; credential_env?: string; temperature?: number; max_tokens?: number; timeout?: number; preference?: string }
export interface AgentCatalog { items: SolveAgent[]; default_id: string; solving_available: boolean }
export interface LibraryDraft { kind: 'strategy' | 'skill'; title: string; category: string; keywords: string; content: string; enabled: boolean }
export interface LibraryItem extends LibraryDraft { id: string; revision: number; updated_at: string }
export interface QuestionItem { number: number; label: string; problem: string; page_start: number | null; page_end: number | null;
  status: TaskStatus | 'pending'; attempt: number; task: Task | null }
export interface QuestionBatch { id: string; session_id: string; original_name: string;
  status: 'parsing' | 'ready' | 'solving' | 'completed' | 'failed' | 'cancelled'; question_count: number; user_instruction?: string | null;
  created_at: string; error_code: string | null; counts: Record<string, number>; questions?: QuestionItem[] }
export interface Page<T> { items: T[]; next_cursor: string | null }
export interface SessionSummary { id: string; title: string; created_at: string; last_activity_at: string; task_count: number }
export interface HistoricalTask extends Task { problem: string }
export const terminal = (status: TaskStatus) => ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(status);
export const taskPath = (session: string, task: string) => `/v1/sessions/${encodeURIComponent(session)}/tasks/${encodeURIComponent(task)}`;

export class ApiError extends Error {
  constructor(public code: string, public status: number) { super(code); }
}
const messages: Record<string, string> = {
  resource_busy: '有解题任务正在使用资源，请等待任务结束后保存。',
  resource_conflict: '资源已被其他页面修改，请刷新后重新编辑。',
  resource_not_found: '未找到该资源，请刷新列表。',
  resource_unavailable: '资源暂不可用，请检查后端日志与资源目录的读写权限。',
  resource_invalid: '内容不能为空。', resource_invalid_strategy: '策略 JSON 格式无效，请保留原 ID、已有字段和字段类型。',
  resource_invalid_new_strategy: '请填写名称、描述、标签、适用条件、步骤及 example 中的 problem、solution；ID 由服务端分配。',
  resource_invalid_index: '策略索引与语料不匹配，请检查后端索引文件。',
  resource_embedding_failed: '本地向量编码失败，原策略和索引保持不变。请检查模型和后端日志。',
  solve_agents_unavailable: '当前服务未启用真实模型配置，请使用 langgraph 模式启动后端。',
  solve_agent_not_found: 'Agent 已被删除，请刷新配置。', solve_agent_disabled: '该 Agent 已停用，请选择其他 Agent。',
  solve_agent_credential_missing: '后端未读取到凭据环境变量。请在启动后端的终端设置变量后重新启动服务。',
  solve_agent_conflict: '配置已发生变化，请刷新后重试。', solve_agent_capacity: '最多保存 100 个 Agent。',
  solve_agent_secret_in_config: '请移除配置中的密钥，只填写后端凭据环境变量名。',
  model_auth_error: '认证失败，请检查后端凭据和模型访问权限。', model_connection_error: '无法连接模型服务，请检查 API 地址与网络。',
  model_timeout: '连接测试超时，请检查 API 地址或稍后重试。', model_request_rejected: '服务拒绝请求，请检查模型名称和接口类型。',
  model_rate_limited: '模型服务限流，请稍后重试。', model_service_error: '模型服务暂时异常。',
  library_unavailable: '自定义知识库暂不可用。', library_capacity: '自定义条目已达到 500 条上限。',
  library_conflict: '条目已被修改或删除，请刷新列表后重新选择。',
  rate_limit_exceeded: '请求过于频繁，请稍后重试。', session_not_found: '会话已不可用，请新建会话。',
  task_not_found: '任务已不可用，服务可能已重启。', not_ready: '服务暂未就绪，请稍后重试。',
  task_already_terminal: '任务已经结束，无法取消。', checkpoint_incompatible: '检查点与当前版本不兼容。',
  invalid_request: '请求内容不符合要求。', task_deadline_exceeded: '任务已达到执行时限。',
  task_not_interrupted: '任务当前不可恢复。', runtime_mismatch: '当前服务与任务的运行模式不一致。',
  unsupported_media_type: '仅支持 PDF 和 Markdown 文件。', file_too_large: '文件不能超过 20 MB。',
  empty_document: '文件内容为空。', media_mismatch: '文件内容与格式不一致。',
  no_extractable_text: '未找到可提取的文本，扫描件暂不支持。',
  storage_capacity_exceeded: '题目附件存储空间不足。', parser_timeout: '文档解析超时。',
  question_service_unavailable: '题目附件暂未启用。', question_batch_active: '本会话已有正在处理的题目附件。',
  question_capacity_exceeded: '待处理题目附件过多，请稍后重试。', question_batch_not_found: '题目批次已不可用。',
  question_upload_conflict: '相同文件已按其他解答设置上传。', ambiguous_question_structure: '题目分隔不明确，请使用“第1题”或“Question 1”等题号。',
  question_not_ready: '题目仍在解析，请稍后提交。', question_start_conflict: '该附件已提交或取消，不能更改本次解题要求。',
  too_many_questions: '每个文件最多包含 20 道题。', question_too_long: '单道题目超过 24,000 字符。',
  empty_question: '发现只有题号、没有内容的题目。', incomplete_pdf_text: 'PDF 存在未提取出文字的页面，请检查扫描页或缺失内容。',
  question_file_contains_solutions: '文件包含答案或解析章节，请上传仅含题目的文件。',
  unreliable_question_text: '文字提取不完整，请检查编码或 PDF 字体。', question_processing_failed: '题目附件处理失败。',
  question_batch_terminal: '题目批次已经结束。', question_not_retryable: '这道题当前不能重试或已达到重试上限。',
  invalid_utf8: 'Markdown 需要使用 UTF-8 编码。', encrypted_pdf: '暂不支持加密 PDF。',
  unclosed_formula_or_fence: '文件中的公式或代码块未闭合。', parse_failed: '文件解析失败，请检查文件内容。',
};
export const errorMessage = (error: unknown) => error instanceof ApiError
  ? messages[error.code] || '请求未成功，请稍后重试。' : '连接未成功，请检查服务后重试。';

async function request<T>(path: string, options: RequestInit = {}, timeoutMs = 10000): Promise<T> {
  const timeout = AbortSignal.timeout(timeoutMs);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  const headers = options.body instanceof FormData ? options.headers : { 'Content-Type': 'application/json', ...options.headers };
  const response = await fetch(path, { ...options, signal, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(typeof body?.error?.code === 'string' ? body.error.code : 'request_failed', response.status);
  }
  return response.json();
}
export const getHealth = (signal?: AbortSignal) => request<Health>('/health/ready', { signal });
export const getResources = (kind: ResourceKind, query: string, offset: number, signal?: AbortSignal) =>
  request<ResourcePage>(`/v1/resources/${kind}?q=${encodeURIComponent(query)}&offset=${offset}`, { signal });
export const getResource = (kind: ResourceKind, id: string, signal?: AbortSignal) =>
  request<ResourceDetail>(`/v1/resources/${kind}/${encodeURIComponent(id)}`, { signal });
export const saveResource = (item: ResourceDetail, content: string) =>
  request<ResourceDetail>(`/v1/resources/${item.kind}/${encodeURIComponent(item.id)}`,
    { method: 'PUT', body: JSON.stringify({ revision: item.revision, content }) }, 180000);
export const createStrategy = (content: string) => request<ResourceDetail>('/v1/resources/strategy',
  { method: 'POST', body: JSON.stringify({ content }) }, 180000);
export const getAgents = (signal?: AbortSignal) => request<AgentCatalog>('/v1/solve-agents', { signal });
export const saveAgent = (draft: AgentDraft, item?: SolveAgent) => request<SolveAgent>(
  item ? `/v1/solve-agents/${encodeURIComponent(item.id)}` : '/v1/solve-agents', {
    method: item ? 'PUT' : 'POST', body: JSON.stringify(item ? { ...draft, revision: item.revision } : draft),
  });
export const agentCommand = (item: SolveAgent, command: 'delete' | 'default' | 'test') => request<{ ok?: boolean; error_code?: string }>(
  `/v1/solve-agents/${encodeURIComponent(item.id)}${command === 'delete' ? '' : `/${command}`}?revision=${item.revision}`,
  { method: command === 'delete' ? 'DELETE' : 'POST' });
export const getLibrary = (signal?: AbortSignal) => request<{ items: LibraryItem[] }>('/v1/library', { signal });
export const saveLibrary = (draft: LibraryDraft, item?: LibraryItem) => request<LibraryItem>(
  item ? `/v1/library/${encodeURIComponent(item.id)}` : '/v1/library', {
    method: item ? 'PUT' : 'POST', body: JSON.stringify(item ? { ...draft, revision: item.revision } : draft),
  });
export const deleteLibrary = (item: LibraryItem) => request<{ deleted: boolean }>(
  `/v1/library/${encodeURIComponent(item.id)}?revision=${item.revision}`, { method: 'DELETE' });
export const createSession = (signal?: AbortSignal) => request<{ id: string }>('/v1/sessions', { method: 'POST', body: '{}', signal });
export const newIdempotencyKey = () => Array.from(crypto.getRandomValues(new Uint8Array(16)),
  byte => byte.toString(16).padStart(2, '0')).join('');
export const getTask = (session: string, id: string, signal?: AbortSignal) => request<Task>(taskPath(session, id), { signal });
export const getSessions = (cursor?: string | null, signal?: AbortSignal) => request<Page<SessionSummary>>(
  `/v1/sessions?limit=30${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, { signal });
export const getSessionTasks = (session: string, cursor?: string | null, signal?: AbortSignal) => request<Page<HistoricalTask>>(
  `/v1/sessions/${encodeURIComponent(session)}/tasks?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, { signal });
export const submitTask = (session: string, problem: string, key: string, responseStyle?: ResponseStyle, signal?: AbortSignal, solveAgentId?: string) => request<Task>(
  `/v1/sessions/${encodeURIComponent(session)}/tasks`, {
    method: 'POST', body: JSON.stringify({ problem, response_style: responseStyle, solve_agent_id: solveAgentId,
      metadata: { document_ids: [] } }), headers: { 'Idempotency-Key': key }, signal,
  });
export function validateFile(file: File): string {
  const extension = file.name.toLowerCase().split('.').at(-1);
  const type = extension === 'pdf' ? 'application/pdf' : ['md', 'markdown'].includes(extension || '') ? 'text/markdown' : '';
  if (!type) throw new ApiError('unsupported_media_type', 415);
  if (!file.size) throw new ApiError('empty_document', 400);
  if (file.size > 20 * 1024 * 1024) throw new ApiError('file_too_large', 413);
  return type;
}
export const questionBatchPath = (session: string, id?: string) => `/v1/sessions/${encodeURIComponent(session)}/question-batches${id ? `/${encodeURIComponent(id)}` : ''}`;
export const getQuestionBatches = (session: string, cursor?: string | null, signal?: AbortSignal) => request<Page<QuestionBatch>>(
  `${questionBatchPath(session)}?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, { signal });
export const getQuestionBatch = (session: string, id: string, signal?: AbortSignal) => request<QuestionBatch>(questionBatchPath(session, id), { signal });
export function uploadQuestions(session: string, file: File, style: ResponseStyle, signal?: AbortSignal) {
  const form = new FormData();
  form.append('file', new Blob([file], { type: validateFile(file) }), file.name);
  form.append('response_style', style);
  form.append('document_ids', '[]');
  return request<QuestionBatch>(questionBatchPath(session), { method: 'POST', body: form, signal });
}
export const cancelQuestionBatch = (session: string, id: string) => request<QuestionBatch>(`${questionBatchPath(session, id)}/cancel`, { method: 'POST' });
export const startQuestionBatch = (session: string, id: string, prompt: string, style: ResponseStyle, solveAgentId?: string) => request<QuestionBatch>(
  `${questionBatchPath(session, id)}/start`, { method: 'POST', body: JSON.stringify({ prompt, response_style: style, solve_agent_id: solveAgentId }) });
export const retryQuestion = (session: string, id: string, number: number) => request<QuestionBatch>(`${questionBatchPath(session, id)}/questions/${number}/retry`, { method: 'POST' });
export const cancelTask = (session: string, id: string) => request<Task>(`${taskPath(session, id)}/cancel`, { method: 'POST', body: '{}' });
export const resumeTask = (session: string, id: string) => request<Task>(`${taskPath(session, id)}/resume`, { method: 'POST' });

export interface SSEFrame { event: string; data: string; id: string }
// Parse the SSE wire protocol, retaining incomplete frames between network chunks.
export class SSEDecoder {
  private buffer = '';
  push(chunk: string): SSEFrame[] {
    this.buffer += chunk;
    if (this.buffer.length > 1024 * 1024) throw new ApiError('invalid_stream', 0);
    const frames: SSEFrame[] = [];
    let match: RegExpExecArray | null;
    while ((match = /\r?\n\r?\n/.exec(this.buffer))) {
      const block = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      let event = 'message', id = '';
      const data: string[] = [];
      for (const line of block.split(/\r?\n/)) {
        if (!line || line.startsWith(':')) continue;
        const colon = line.indexOf(':');
        const field = colon < 0 ? line : line.slice(0, colon);
        const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '');
        if (field === 'event') event = value;
        if (field === 'id') id = value;
        if (field === 'data') data.push(value);
      }
      if (data.length) frames.push({ event, data: data.join('\n'), id });
    }
    return frames;
  }
}

export function parseEvent(raw: unknown, session: string, task: string): TraceEvent | null {
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as TraceEvent;
  if (value.session_id !== session || value.task_id !== task || !Number.isSafeInteger(value.sequence)
      || value.sequence < 1 || typeof value.stage_id !== 'string' || typeof value.event_type !== 'string'
      || typeof value.created_at !== 'string' || !value.payload || typeof value.payload !== 'object'
      || Array.isArray(value.payload)) return null;
  return value;
}
export function taskFromEvent(task: Task, event: TraceEvent): Task {
  if ((terminal(task.status) && !(task.status === 'interrupted' && event.event_type === 'task.resumed'))
      || event.task_id !== task.id || event.session_id !== task.session_id) return task;
  const payload = event.payload;
  // Tool/model statuses describe an operation, not the enclosing task.
  const taskEvent = event.event_type.startsWith('task.');
  const timestamp = (key: string, previous: string | null | undefined) => {
    if (!taskEvent || !(key in payload)) return previous;
    const value = payload[key];
    return value === null || (typeof value === 'string' && Number.isFinite(Date.parse(value))) ? value : previous;
  };
  const timing = payload.timing;
  const validTiming = taskEvent && !!timing && typeof timing === 'object' && !Array.isArray(timing)
    && ['total_ms', 'queue_ms', 'processing_ms', 'answer_delivery_ms'].every(key => {
      const value = (timing as Record<string, unknown>)[key];
      return value === null || (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0);
    });
  const status = taskEvent && typeof payload.status === 'string' && Object.hasOwn(statusNames, payload.status)
    ? payload.status as TaskStatus : task.status;
  return { ...task, status,
    started_at: timestamp('started_at', task.started_at) ?? null,
    finished_at: timestamp('finished_at', task.finished_at) ?? null,
    stopped_at: timestamp('stopped_at', task.stopped_at),
    timing: validTiming ? timing as TaskTiming : task.timing,
    current_stage: event.stage_id === 'system' ? task.current_stage : event.stage_id,
    final_response: taskEvent && typeof payload.final_response === 'string' ? payload.final_response : task.final_response,
    error_code: taskEvent && typeof payload.error_code === 'string' ? payload.error_code : task.error_code,
  };
}

export function watchTask(session: string, id: string, callbacks: {
  task: (value: Task) => void; event: (value: TraceEvent) => void;
  connection: (value: string) => void; error: (error: unknown) => void;
}): () => void {
  const controller = new AbortController();
  const { signal } = controller;
  let current: Task | undefined, sequence = 0, poll: ReturnType<typeof setTimeout> | undefined;
  const deliver = (raw: unknown, apply = true) => {
    const event = parseEvent(raw, session, id);
    if (!event || event.sequence <= sequence || signal.aborted) return;
    sequence = event.sequence;
    callbacks.event(event);
    if (current && apply) {
      current = taskFromEvent(current, event);
      callbacks.task(current);
    }
  };
  const sync = async () => {
    const incoming = await getTask(session, id, signal);
    if (!current || !terminal(current.status) || current.status === 'interrupted' || terminal(incoming.status)) current = incoming;
    if (!signal.aborted) callbacks.task(current);
  };
  const stopIfDone = () => {
    if (current && terminal(current.status)) {
      callbacks.connection('已结束');
      controller.abort();
      if (poll) clearTimeout(poll);
      return true;
    }
    return signal.aborted;
  };
  const pollStatus = async () => {
    try { await sync(); } catch (error) {
      if (!signal.aborted) callbacks.error(error);
      if (error instanceof ApiError && error.status === 404) { controller.abort(); return; }
    }
    if (!stopIfDone()) poll = setTimeout(() => void pollStatus(), 3000);
  };
  const run = async () => {
    try {
      await sync();
      while (!signal.aborted) {
        const previousSequence = sequence;
        const trace = await request<{ events: unknown[]; next_sequence: number }>(
          `${taskPath(session, id)}/trace?after_sequence=${sequence}&limit=500`, { signal });
        trace.events.forEach(raw => deliver(raw, false));
        if (trace.events.length < 500) break;
        if (sequence <= previousSequence) throw new ApiError('invalid_trace', 502);
      }
      if (!signal.aborted) await sync();
      if (stopIfDone()) return;
      poll = setTimeout(() => void pollStatus(), 3000);
      let retry = 1000;
      while (!signal.aborted) {
        callbacks.connection('连接中');
        try {
          const response = await fetch(`${taskPath(session, id)}/events?after=${sequence}`, { signal });
          if (!response.ok || !response.body) throw new ApiError('stream_unavailable', response.status);
          callbacks.connection('已连接');
          retry = 1000;
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          const sse = new SSEDecoder();
          try {
            while (!signal.aborted) {
              const { value, done } = await reader.read();
              if (done) break;
              for (const frame of sse.push(decoder.decode(value, { stream: true }))) {
                deliver(JSON.parse(frame.data));
              }
              if (current && terminal(current.status)) break;
            }
          } finally {
            await reader.cancel().catch(() => {});
            reader.releaseLock();
          }
          if (!signal.aborted) await sync();
          if (stopIfDone()) return;
        } catch (error) {
          if (signal.aborted) return;
          if (error instanceof ApiError && error.status === 404) throw error;
        }
        callbacks.connection('重连中');
        await new Promise<void>(resolve => {
          const done = () => { clearTimeout(timer); signal.removeEventListener('abort', done); resolve(); };
          const timer = setTimeout(done, retry);
          signal.addEventListener('abort', done, { once: true });
        });
        retry = Math.min(retry * 2, 8000);
      }
    } catch (error) {
      if (!signal.aborted) { callbacks.error(error); callbacks.connection('连接失败'); }
      controller.abort();
      if (poll) clearTimeout(poll);
    }
  };
  void run();
  return () => { controller.abort(); if (poll) clearTimeout(poll); };
}

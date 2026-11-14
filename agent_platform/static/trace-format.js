// Shared by the chat timeline and the standalone trace workspace.
export const stageLabels = {
  profile: '题意分析', retrieve: '策略检索', plan: '解题规划', solve: '推导求解',
  tool: '工具验证', verify: '独立审查', repair: '定向修复', finalize: '最终验收',
  emergency: '应急求解', arbitrate: '候选仲裁', terminal: '结束', system: '任务调度',
};
const calls = {
  classifier: '题型识别', strategy: '方法规划', solver: '解答生成', solver_repair: '修复解答生成',
  solver_compressed: '压缩解答', solver_compressed_retry: '压缩解答重试',
  targeted_audit: '数学审查', model_fidelity: '题意一致性检查',
  emergency_integrator: '应急整合', emergency_direct_solver: '应急直接求解', final_arbitrator: '最终仲裁',
};
const tools = { math_verify: '数学检查', sympy_calculate: '符号计算', strategy_search: '内置策略检索', document_search: '文档检索' };
export const formatReasons = {
  multiple_final_candidates: '存在冲突或尚无法证明等价的多个答案',
  non_concept_final_answer_contains_chinese: '数值答案字段含有中文文字',
};
const reasons = {
  reasoning_content_exhausted: '模型未给出可用的公开解答', compressed_solution_invalid: '压缩解答格式不完整',
  solver_no_candidate: '未提取到可用答案', candidate_too_large: '候选解答超过长度限制',
  stage_failed: '阶段执行异常，转入恢复流程', local_check_failed: '本地检查未能完成',
  no_acceptable_candidate: '没有候选答案通过最终验收', candidate_check_unavailable: '最终检查未能完成',
  convergence_deadline_reached: '已达到收敛时限', disabled: '当前配置未启用',
  constraint_ledger_unavailable: '缺少可用的约束记录',
};
const modelErrors = {
  incomplete_model_stream: '模型响应中断，未收到完整解答。', invalid_model_stream: '模型响应格式异常，无法读取完整解答。',
  model_stream_error: '模型服务在生成过程中返回错误。', model_stream_too_large: '模型响应超过可接收的大小。',
  model_timeout: '等待模型响应超时。', model_connection_error: '无法连接模型服务或连接已中断。',
  model_auth_error: '模型服务认证失败，请检查后端 API Key 和访问权限。',
  model_rate_limited: '模型服务限流，请稍后重试。', model_service_error: '模型服务暂时异常，请稍后重试。',
  model_request_rejected: '模型服务拒绝请求，请检查后端模型配置。',
};
const outcomes = {
  completed: '执行结束', pass: '检查通过', needs_review: '检查发现问题', unverified: '尚未验证通过',
  recovered: '进入恢复流程', incomplete: '未产生完整候选', accepted: '答案已接受', rejected: '答案未通过验收',
};
const sourceLabels = { solve: '首次求解', repair: '修复草稿', verified: '通过审查的草稿', emergency: '应急求解',
  final_arbitration: '最终仲裁', evidence_selection: '候选比较', fallback: '保留草稿', final_candidate: '当前候选' };
const verdicts = { pass: '通过', fail: '不通过', uncertain: '无法确认', unknown: '未能确定' };
const text = value => typeof value === 'string' ? value : '';
const known = (map, key, fallback) => Object.hasOwn(map, text(key)) ? map[key] : fallback;
const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
const sourceName = value => /^solver_attempt_\d+$/.test(text(value)) ? `第 ${value.split('_').at(-1)} 轮求解草稿`
  : known(sourceLabels, value, '已保存的候选');

export function describeEvent(event) {
  const p = event.payload || {}, stage = known(stageLabels, event.stage_id, '任务调度');
  let title = '', level = 'info';
  const details = [];
  const add = (label, value) => { if (value !== null && value !== undefined && value !== '') details.push([label, String(value)]); };
  if (event.event_type.startsWith('model.') && p.agent) {
    add('调用 Agent', text(p.agent.name));
    add('模型', text(p.agent.model));
    if (number(p.agent.revision) !== null) add('配置版本', `v${p.agent.revision}`);
    add('职责', p.agent.role === 'solve' ? '求解与修复' : '控制与审查');
  }
  const call = known(calls, p.call_type, text(p.call_type).startsWith('solver') ? '解答生成' : '模型调用');
  const tool = known(tools, p.name, '工具检查');
  switch (event.event_type) {
    case 'stage.context': return null;
    case 'stage.started': title = `${stage}开始。`; break;
    case 'stage.completed': title = `${stage}执行结束。`; break;
    case 'stage.outcome':
      title = known(outcomes, p.status, '执行状态已更新');
      level = ['needs_review', 'unverified', 'recovered', 'incomplete'].includes(p.status) ? 'warning'
        : p.status === 'rejected' ? 'error' : ['pass', 'accepted'].includes(p.status) ? 'success' : 'info';
      add('后续动作', known(stageLabels, p.next_stage, '未记录'));
      add('执行节点', known(stageLabels, p.node, '未记录'));
      add('采用草稿', p.candidate_source ? sourceName(p.candidate_source) : '');
      if (number(p.candidate_round) !== null) add('最终采用轮次', `第 ${p.candidate_round} 轮`);
      if (p.routing_reason) add('流转依据', known({
        task_budget_low: '剩余任务预算不足，进入最终整理', solver_no_candidate: '主求解未产生可用候选，进入应急求解',
        audit_requires_repair: '审查发现需要修正的问题', compare_available_candidates: '比较当前可用候选，尝试保留可返回的答案',
        finalize_existing_candidate: '按收敛或部分草稿恢复规则，进入最终验收', review_finished: '审查流程结束，进入最终验收',
      }, p.routing_reason, '按当前阶段的实际结果继续'));
      if (p.review_source) add('审查方式', p.review_source === 'local_checks' ? '复用本地检查，未调用独立模型审查' : '执行模型审查流程，结论以审查记录为准');
      break;
    case 'model.started': title = `${stage}：${p.call_type ? `正在执行${call}` : '正在等待模型处理'}。`; level = 'running'; break;
    case 'model.completed': title = `${stage}：${p.call_type ? `${call}完成` : '模型处理结束'}。`; break;
    case 'model.failed': title = `${stage}：${known(modelErrors, p.error_code, '模型调用未成功。')}`; level = 'error'; break;
    case 'model.budget_exhausted': title = '模型调用预算已耗尽。'; level = 'warning'; break;
    case 'model.interrupted': title = `${call}已中断。`; level = 'warning'; break;
    case 'retrieval.started': title = '正在检索参考资料。'; level = 'running'; break;
    case 'retrieval.completed': title = `检索结束${number(p.hit_count) !== null ? `，命中 ${p.hit_count} 条` : ''}。`; break;
    case 'retrieval.cited': title = '解答中报告了引用，仍需核对适用性。'; break;
    case 'library.selected': title = `自定义知识库选入 ${Array.isArray(p.references) ? p.references.length : 0} 条资料。`; break;
    case 'library.injected': title = `已将参考资料注入${call}调用。`; break;
    case 'tool.started': title = `正在执行${tool}。`; level = 'running'; break;
    case 'tool.completed': title = `${tool}执行结束。`; break;
    case 'tool.result': {
      title = `${tool}的实际结果。`;
      const value = p.result || {};
      for (const [key, label] of [['normalized_expression', '计算表达式'], ['value', '计算值'], ['conditions', '适用条件'],
        ['warnings', '注意事项'], ['checked_claims', '已检查结论'], ['findings', '检查说明'], ['counterexample', '反例或矛盾']]) {
        const item = value[key];
        if (Array.isArray(item)) {
          for (const part of item.slice(0, 12)) if (typeof part === 'string') add(label, part);
        } else if (typeof item === 'string') add(label, item);
      }
      if (value.verdict) add('数学结论', known(verdicts, value.verdict, '未能确定'));
      level = p.status === 'failed' || value.verdict === 'fail' ? 'error' : value.verdict === 'uncertain' ? 'warning' : 'info';
      break;
    }
    case 'tool.committed': title = `${tool}结果已保存。`; level = p.status === 'failed' ? 'error' : 'info'; break;
    case 'tool.replayed': title = `${tool}：已复用工具检查记录。`; break;
    case 'tool.failed': case 'tool.rejected': title = `${tool}${event.event_type === 'tool.rejected' ? '请求被拒绝' : '执行失败'}。`; level = 'error'; break;
    case 'tool_fallback.started': title = `${tool}切换到本地回退。`; level = 'running'; break;
    case 'tool_fallback.completed': title = `${tool}本地回退结束。`; level = p.status === 'failed' ? 'error' : 'info'; break;
    case 'tool.interrupted': case 'tool_fallback.interrupted': title = `${tool}已中断。`; level = 'warning'; break;
    case 'retrieval.interrupted': title = '检索已中断。'; level = 'warning'; break;
    case 'checks.completed':
      title = '本地检查结果已汇总。';
      level = p.hard_failures?.length || p.format_failures?.length ? 'error' : p.verdict === 'pass' ? 'success' : 'warning';
      break;
    case 'verification.completed':
      title = `审查结论：${known(verdicts, p.verdict, '无法确认')}。`;
      level = p.verdict === 'pass' ? 'success' : p.verdict === 'fail' ? 'error' : 'warning';
      break;
    case 'reasoning.event': {
      switch (p.operation) {
        case 'final_candidate_checked':
          title = event.stage_id === 'finalize'
            ? p.accepted === true ? '候选答案通过最终验收。' : '候选答案未通过最终验收。'
            : p.accepted === true ? '候选满足当前最小返回条件，仍需后续核验。' : '候选未满足当前最小返回条件。';
          level = p.accepted === true ? 'success' : 'error';
          if (number(p.hard_failure_count) !== null) add('计算矛盾数', p.hard_failure_count);
          if (p.confirmed_audit_failure) add('审查依据', '存在有证据支持的数学错误');
          if (p.extraction && !['ok', 'unsectioned_answer'].includes(p.extraction)) add('答案提取', known({
            missing_final_answer_section: '缺少可识别的最终答案', empty_final_answer_section: '最终答案章节为空',
            placeholder_final_answer: '最终答案仍为占位或不确定表述', malformed_latex: '答案公式未闭合',
            unusable_final_answer: '最终答案不可用', unusable_or_malformed_answer: '最终答案不可用或公式格式异常',
          }, p.extraction, '未提取到可用答案'));
          add('候选来源', sourceName(p.source));
          break;
        case 'final_acceptance_failed': title = '所有候选均未通过最终验收。'; level = 'error'; break;
        case 'compressed_solution_invalid': title = '压缩解答不完整，尚不能作为最终候选。'; level = 'warning'; break;
        case 'recovery_routed': title = '已选择修复路径。'; break;
        case 'best_candidate_saved': title = '已保留本轮可用草稿。'; break;
        case 'solution_candidate_selected': title = '正文为空，已将思考内容送入候选检查。'; break;
        case 'review_round_started':
          title = '开始本轮审查，一致性检查、快速审查、深度复核和格式恢复共用预算。';
          if (number(p.budget_seconds) !== null) add('本轮审查预算', `${p.budget_seconds} 秒`);
          break;
        case 'review_round_completed':
          title = p.review_status === 'service_unavailable' ? '本轮审查未完成，保留候选但不标记审查通过。' : '本轮审查执行结束。';
          level = p.review_status === 'service_unavailable' ? 'warning' : 'info';
          break;
        case 'audit_fast_completed': title = '快速审查已结束。'; break;
        case 'audit_deep_started': title = '快速审查发现疑点，开始针对疑点深度复核。'; break;
        case 'audit_deep_completed': title = '针对疑点的深度复核已结束。'; break;
        case 'deadline_candidate_selected': title = '已根据现有检查记录选择候选草稿。'; break;
        case 'model_fidelity_skipped': title = '本轮跳过题意一致性模型检查。'; level = 'warning'; break;
        case 'model_fidelity_unavailable': title = '未获得题意一致性检查结论。'; level = 'warning'; break;
        case 'chat_response_rendered': title = '最终答案已整理。'; break;
        default: title = '推理状态已更新。';
      }
      break;
    }
    case 'candidate_check.failed': title = '候选检查未完成。'; level = 'error'; break;
    case 'stage.recovered_error': title = `${stage}：本阶段发生异常，进入恢复流程。`; level = 'warning'; break;
    case 'answer.started': title = p.preview ? '正在生成解答。' : '校验后的答案已就绪。'; break;
    case 'answer.completed': title = p.preview ? '解答已生成，等待校验。' : '答案发送完成。'; break;
    case 'answer.discarded': title = '本轮解答已撤回。'; level = 'warning'; break;
    case 'task.accepted': title = '任务已接收，等待执行。'; break;
    case 'task.running': title = '任务开始执行。'; break;
    case 'task.succeeded': title = '任务执行结束。'; break;
    case 'task.failed': title = '任务执行失败。'; level = 'error'; break;
    case 'task.cancelled': title = '任务已取消。'; level = 'warning'; break;
    case 'task.cancelling': title = '正在取消任务。'; level = 'warning'; break;
    case 'task.interrupted': title = '任务已中断。'; level = 'warning'; break;
    case 'task.resumed': title = '任务从检查点恢复。'; break;
    case 'checkpoint.incompatible': title = '检查点与当前配置不兼容。'; level = 'error'; break;
    default: return null;
  }
  if (p.call_type) add('调用', call);
  if (p.name) add('工具', tool);
  if (p.reason) add('原因', known(reasons, p.reason, '详见本阶段公开说明'));
  if (p.budget_exhausted) add('检查预算', '已耗尽，部分检查未完成');
  if (p.verdict) add('核验结论', known(verdicts, p.verdict, '未能确定'));
  if (p.status === 'succeeded' || p.status === 'fallback') add('执行结果', '成功执行，不代表数学结论已证明');
  if (p.status === 'failed') add('执行结果', '失败');
  if (p.transport) add('执行方式', p.transport === 'local' ? '本地' : p.transport === 'mcp' ? 'MCP' : '未记录');
  if (number(p.attempt) !== null && event.event_type.startsWith('tool')) add('本工具第几次尝试', p.attempt + 1);
  if (number(p.retry_count) !== null) add('已重试次数', p.retry_count);
  if (number(p.attempts) !== null) add('实际尝试次数', p.attempts);
  if (number(p.http_status) !== null) add('HTTP 状态', p.http_status);
  if (number(p.content_length) !== null) add('公开输出字符数', p.content_length);
  if (p.usage && typeof p.usage === 'object') {
    for (const [key, label] of [['prompt_tokens', '输入 Token'], ['completion_tokens', '输出 Token'], ['total_tokens', '总 Token']]) {
      if (number(p.usage[key]) !== null) add(label, p.usage[key]);
    }
  }
  if (Array.isArray(p.format_failures)) for (const code of p.format_failures.slice(0, 8)) add('格式检查', known(formatReasons, code, '答案格式尚未通过'));
  if (Array.isArray(p.hard_failures)) for (const expression of p.hard_failures.slice(0, 12)) if (typeof expression === 'string') add('计算矛盾', expression);
  if (Array.isArray(p.program_checks)) for (const check of p.program_checks.slice(0, 12)) {
    if (typeof check.expression === 'string') add('表达式检查', `${check.expression} → ${text(check.result)}（${known(verdicts, check.verdict, '未能确定')}）`);
  }
  if (Array.isArray(p.references)) for (const ref of p.references.slice(0, 20)) {
    if (!ref || typeof ref !== 'object') continue;
    const name = text(ref.title) || text(ref.name) || text(ref.chunk_id) || text(ref.id);
    const revision = number(ref.revision) !== null ? ` · 版本 ${ref.revision}` : '';
    const score = number(ref.score) !== null ? ` · 匹配分 ${ref.score.toFixed(3)}` : '';
    add(ref.kind === 'skill' ? 'Skill' : '参考条目', name + revision + score);
  }
  return { title, level, details };
}

export function traceRows(events) {
  const rows = [], operations = new Map();
  for (const event of events) {
    const view = describeEvent(event);
    if (!view) continue;
    const family = /^(model|retrieval|tool|tool_fallback)\.(started|completed|failed|interrupted)$/.exec(event.event_type)?.[1];
    const key = family && typeof event.payload.operation_id === 'string' ? `${family}:${event.payload.operation_id}` : null;
    const prior = key ? operations.get(key) : undefined;
    const duration = number(event.payload.duration_ms) ?? number(event.payload.latency_ms);
    if (prior) {
      prior.events.push(event);
      const replaced = new Set(view.details.map(([label]) => label));
      prior.view = { ...view, details: [...prior.view.details.filter(([label]) => !replaced.has(label)), ...view.details] };
      prior.durationMs = duration ?? prior.durationMs;
      prior.endedAt = event.created_at;
    } else {
      const row = { id: event.sequence, stage: event.stage_id, startedAt: event.created_at,
        durationMs: duration, view, events: [event] };
      rows.push(row);
      if (key) operations.set(key, row);
    }
  }
  return rows;
}

export function matchesTrace(row, query = '', problemsOnly = false) {
  return (!problemsOnly || ['warning', 'error'].includes(row.view.level)) &&
    `${row.view.title} ${row.view.details.flat().join(' ')} ${row.events.map(e => `${e.event_type} ${e.payload.operation_id || ''} ${e.payload.call_id || ''}`).join(' ')}`
      .toLowerCase().includes(query.toLowerCase().trim());
}

export function publicTraceEvent(event) {
  const allowed = ['operation', 'operation_id', 'call_id', 'call_type', 'node', 'round', 'status', 'next_stage',
    'reason', 'source', 'candidate_source', 'candidate_id', 'accepted', 'budget_exhausted', 'hard_failure_count', 'review_source', 'routing_reason', 'candidate_round',
    'confirmed_audit_failure', 'format_failures', 'local_verdict', 'verdict', 'duration_ms', 'latency_ms',
    'name', 'transport', 'attempt', 'attempts', 'retry_count', 'retryable', 'error_code', 'error_type', 'http_status',
    'content_length', 'usage', 'hit_count', 'references', 'program_checks', 'hard_failures', 'review_status', 'budget_seconds',
    'action', 'recovery_action', 'kind', 'title', 'content', 'preview', 'stream_id', 'chunks', 'index', 'text', 'result', 'extraction', 'agent'];
  const nested = new Set(['prompt_tokens', 'completion_tokens', 'total_tokens', 'id', 'revision', 'kind', 'title',
    'category', 'name', 'score', 'chunk_id', 'document_id', 'rank', 'expression', 'source', 'status', 'verdict', 'result',
    'value', 'normalized_expression', 'conditions', 'warnings', 'findings', 'checked_claims', 'counterexample', 'model', 'role']);
  const clean = value => {
    if (Array.isArray(value)) return value.map(clean);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).filter(([key]) => nested.has(key)).map(([key, item]) => [key, clean(item)]));
    return value;
  };
  return { sequence: event.sequence, stage_id: event.stage_id, event_type: event.event_type, created_at: event.created_at,
    payload: Object.fromEntries(allowed.filter(key => Object.hasOwn(event.payload, key)).map(key => [key, clean(event.payload[key])])) };
}

export function traceStageGroups(events) {
  const groups = [], latest = new Map();
  for (const event of events) {
    let group = latest.get(event.stage_id);
    if (event.event_type === 'stage.started' || !group) {
      group = { id: event.sequence, stage: event.stage_id, startedAt: event.created_at, events: [] };
      groups.push(group);
      latest.set(event.stage_id, group);
    }
    group.events.push(event);
    if (event.event_type === 'stage.context') {
      group.node = event.payload.node;
      group.round = event.payload.round;
    }
    if (event.event_type === 'stage.outcome') group.outcome = describeEvent(event);
    if (event.event_type.startsWith('task.')) group.outcome = describeEvent(event);
    if (event.event_type === 'stage.completed') group.endedAt = event.created_at;
  }
  return groups;
}

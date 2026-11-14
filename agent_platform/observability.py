"""Opt-in LangSmith tracing with credentials and runtime objects removed."""
import os
import logging
import json
import math
import re
import time
from contextlib import contextmanager
from functools import lru_cache

from agent_platform.safety import sanitize_text


def redact_trace_value(value, depth=0):
    """Keep debugging content without serializing clients or authentication data."""
    if depth > 12:
        return "[depth limit]"
    if isinstance(value, str):
        for key, secret in os.environ.items():
            if secret and any(part in key.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
                value = value.replace(secret, "[redacted]")
        value = sanitize_text(value[:120000])
        return re.sub(r"/(?:Users|home|tmp|private|opt|var)/[^\s<>\"']+", "[local path]", value)
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:200]:
            if not isinstance(key, str):
                continue
            normalized = key.lower().replace("-", "_")
            if (normalized in {"headers", "credentials", "authorization", "cookie", "cookies",
                               "client", "model_client", "session", "http_client", "authorization_header"}
                    or any(part in normalized for part in ("api_key", "apikey", "password", "secret"))
                    or normalized in {"token", "access_token", "refresh_token"}
                    or normalized.endswith("_token")):
                result[key] = "[redacted]"
            else:
                result[key] = redact_trace_value(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_trace_value(item, depth + 1) for item in value[:200]]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return "[unsupported object]"


def tracing_enabled():
    value = os.environ.get("LANGSMITH_TRACING", "false").lower().strip()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError("LANGSMITH_TRACING 必须为 true 或 false")
    enabled = value in {"true", "1"}
    if enabled and not os.environ.get("LANGSMITH_API_KEY", "").strip():
        raise ValueError("启用 LangSmith 需要配置 LANGSMITH_API_KEY")
    return enabled


def redact_runs(operations):
    # Exceptions can contain raw HTTP responses, credentials or local paths.
    for operation in operations:
        for key in ("inputs", "outputs", "extra", "events"):
            if key in operation:
                operation[key] = redact_trace_value(operation[key])
        if operation.get("error"):
            operation["error"] = "execution_failed (details available locally)"
        for key in ("serialized", "attachments"):
            operation.pop(key, None)
    return operations


@lru_cache(maxsize=1)
def tracing_client():
    from langsmith import Client

    return Client(hide_inputs=redact_trace_value, hide_outputs=redact_trace_value,
                  hide_metadata=redact_trace_value,
                  omit_traced_runtime_info=True, process_buffered_run_ops=redact_runs,
                  run_ops_buffer_size=100, run_ops_buffer_timeout_ms=1000)


@contextmanager
def graph_tracing(task_id):
    from langsmith import tracing_context

    enabled = tracing_enabled()
    with tracing_context(enabled=enabled, client=tracing_client() if enabled else None,
                         project_name=os.environ.get("LANGSMITH_PROJECT", "math-reasoning")):
        if enabled:
            from langchain_core.tracers.langchain import LangChainTracer

            tracer = LangChainTracer(client=tracing_client(),
                                    project_name=os.environ.get("LANGSMITH_PROJECT", "math-reasoning"))
            try:
                yield {"callbacks": [tracer], "tags": [f"task:{task_id}"],
                       "run_name": "math_reasoning"}
            finally:
                # The SDK buffer timeout is checked only when another run arrives.
                # Without flushing, a finished graph can remain pending indefinitely.
                try:
                    tracing_client().flush(timeout=0)
                except Exception as error:
                    logging.getLogger("uvicorn.error").warning(
                        "[LangSmith] 追踪发送未完成（%s），请检查网络与配置。", type(error).__name__)
        else:
            yield {}


def invoke_model(client, kwargs, call_type):
    from reasoning_agent.custom2.model_call import _invoke_client, _normalize_response

    if not tracing_enabled():
        return _invoke_client(client, kwargs)
    from langsmith import trace

    model = getattr(client, "model", None)
    metadata = {"ls_model_name": model, "ls_model_type": "chat"} if isinstance(model, str) else {}
    with trace(name=call_type, run_type="llm", client=tracing_client(),
               inputs=redact_trace_value(kwargs), metadata=metadata) as run:
        raw = _invoke_client(client, kwargs)
        response = _normalize_response(raw, 0)
        message = {"role": "assistant", "content": response.content}
        if response.reasoning_content:
            message["reasoning_content"] = response.reasoning_content
        if isinstance(raw, dict) and raw.get("tool_calls"):
            message["tool_calls"] = raw["tool_calls"]
        outputs = {"choices": [{"message": message, "finish_reason": response.finish_reason}]}
        usage = response.token_usage if isinstance(response.token_usage, dict) else {}
        counts = {}
        for source, target in (("prompt_tokens", "input_tokens"),
                               ("completion_tokens", "output_tokens"), ("total_tokens", "total_tokens")):
            count = usage.get(source, usage.get(target))
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                counts[target] = count
        if "total_tokens" not in counts and {"input_tokens", "output_tokens"} <= counts.keys():
            counts["total_tokens"] = counts["input_tokens"] + counts["output_tokens"]
        if counts:
            outputs["usage_metadata"] = counts
        run.end(outputs=redact_trace_value(outputs))
        return raw


def log_runtime_event(task_id, stage, event_type, payload=None):
    labels = {
        "stage.started": "节点开始", "stage.completed": "节点完成",
        "model.started": "模型开始", "model.completed": "模型完成",
        "model.failed": "模型失败", "model.budget_exhausted": "模型预算耗尽",
        "retrieval.started": "检索开始", "retrieval.completed": "检索完成",
        "tool.started": "工具开始", "tool.completed": "工具完成",
        "tool.failed": "工具失败", "tool.rejected": "工具拒绝",
        "tool.committed": "工具提交", "tool.replayed": "工具重放",
        "tool_fallback.started": "工具回退开始", "tool_fallback.completed": "工具回退完成",
        "verification.completed": "校验完成", "stage.recovered_error": "节点异常恢复",
        "stage.context": "阶段信息", "stage.outcome": "阶段结果", "checks.completed": "本地检查汇总",
        "library.selected": "自定义资料选入", "library.injected": "自定义资料注入",
    }
    payload = payload or {}
    if event_type == "reasoning.event":
        operation_labels = {
            "final_candidate_checked": "最终候选验收" if stage == "finalize" else "候选返回检查", "final_acceptance_failed": "最终验收失败",
            "compressed_solution_invalid": "压缩解答不完整", "recovery_routed": "选择修复路径",
            "best_candidate_saved": "保留候选草稿", "deadline_candidate_selected": "选择时限内候选",
            "model_fidelity_unavailable": "题意检查未完成", "model_fidelity_skipped": "跳过题意检查",
        }
        label = operation_labels.get(payload.get("operation"))
        if label is None:
            return
        labels[event_type] = label
    if event_type not in labels:
        return
    details = []
    readable = {
        "profile": "题意分析", "retrieve": "策略检索", "plan": "解题规划", "solve": "推导求解",
        "tool": "工具验证", "verify": "独立审查", "repair": "定向修复", "finalize": "最终验收",
        "emergency": "应急求解", "arbitrate": "候选仲裁", "terminal": "结束",
        "completed": "执行结束", "accepted": "答案已接受", "rejected": "答案未通过验收",
        "needs_review": "检查发现问题", "unverified": "尚未验证通过", "recovered": "进入恢复流程",
        "incomplete": "未产生完整候选", "pass": "通过", "fail": "不通过", "uncertain": "无法确认", "unknown": "未能确定",
        "classifier": "题型识别", "strategy": "方法规划", "solver": "解答生成", "solver_repair": "修复解答生成",
        "targeted_audit": "数学审查", "model_fidelity": "题意一致性检查", "math_verify": "数学检查",
        "sympy_calculate": "符号计算", "strategy_search": "内置策略检索", "document_search": "文档检索",
        "no_acceptable_candidate": "没有候选通过最终验收", "reasoning_content_exhausted": "未获得可用公开解答",
    }
    for key, label in (("call_type", "调用"), ("name", "工具"), ("call_id", "调用ID"),
                       ("operation_id", "操作ID"), ("transport", "方式"), ("status", "状态"),
                       ("error_code", "错误码"), ("error_type", "错误类型"), ("verdict", "结论"),
                       ("next_stage", "下一步"), ("node", "执行节点"), ("candidate_source", "采用草稿"),
                       ("source", "候选来源"), ("reason", "原因"), ("extraction", "答案提取状态")):
        value = payload.get(key)
        if isinstance(value, str):
            value = redact_trace_value(value).replace("\n", " ").replace("\r", " ")[:200]
            translated = readable.get(value)
            details.append(f"{label}={value}" + (f"（{translated}）" if translated else ""))
    for key, label in (("duration_ms", "耗时毫秒"), ("latency_ms", "耗时毫秒"),
                       ("hit_count", "命中条数"), ("retry_count", "重试次数"), ("attempt", "尝试序号"),
                       ("http_status", "HTTP状态"), ("attempts", "尝试次数"), ("round", "解答轮次"),
                       ("hard_failure_count", "计算矛盾数")):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            details.append(f"{label}={value}")
    usage = payload.get("usage", {})
    agent = payload.get("agent")
    if isinstance(agent, dict):
        public = {key: agent[key] for key in ("id", "name", "revision", "model", "role") if key in agent}
        details.append("Agent=" + json.dumps(redact_trace_value(public), ensure_ascii=False))
    if isinstance(usage, dict):
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                details.append(f"{key}={value}")
    for key, label in (("accepted", "最终验收通过" if stage == "finalize" else "当前返回检查通过"), ("budget_exhausted", "检查预算耗尽"),
                       ("confirmed_audit_failure", "存在已证实审查错误")):
        if isinstance(payload.get(key), bool):
            details.append(f"{label}={'是' if payload[key] else '否'}")
    format_labels = {"multiple_final_candidates": "多个答案冲突或尚无法验证等价",
                     "non_concept_final_answer_contains_chinese": "数值答案字段含中文"}
    for code in (payload.get("format_failures") or [])[:8]:
        details.append(f"格式检查={format_labels.get(code, '格式未通过')}")
    for item in (payload.get("program_checks") or [])[:12]:
        if isinstance(item, dict):
            expression = redact_trace_value(str(item.get("expression", ""))).replace("\n", " ")[:500]
            result = redact_trace_value(str(item.get("result", ""))).replace("\n", " ")[:500]
            details.append(f"核对=[{expression} -> {result}; {item.get('verdict', 'unknown')}]")
    for item in (payload.get("references") or [])[:20]:
        if isinstance(item, dict):
            reference = {key: item[key] for key in ("id", "revision", "kind", "title", "name") if key in item}
            details.append("资料=" + json.dumps(redact_trace_value(reference), ensure_ascii=False))
    if event_type in {"library.selected", "library.injected"}:
        details.append(f"资料条数={len(payload.get('references') or [])}")
    routing = {"task_budget_low": "剩余预算不足", "solver_no_candidate": "未获得可用候选",
               "audit_requires_repair": "审查发现问题", "compare_available_candidates": "比较当前候选",
               "finalize_existing_candidate": "按收敛或部分恢复规则进入验收", "review_finished": "审查流程结束"}
    if payload.get("routing_reason") in routing:
        details.append("流转依据=" + routing[payload["routing_reason"]])
    # Only selected diagnostic fields are logged, never raw model payloads.
    identifier = str(task_id).replace("\n", "").replace("\r", "")[:64]
    stage_labels = {"profile": "题意分析", "retrieve": "策略检索", "plan": "解题规划", "solve": "推导求解",
                    "tool": "工具验证", "verify": "独立审查", "repair": "定向修复", "finalize": "最终验收"}
    stage_code = str(stage).replace("\n", "").replace("\r", "")[:32]
    stage_name = f"{stage_code}（{stage_labels.get(stage, '任务调度')}）"
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [任务 {identifier}] "
          f"[{labels[event_type]}] {stage_name} {' '.join(details)}".rstrip(), flush=True)


def log_tool_result(task_id, stage, name, call_id, result, *, replayed=False):
    if not isinstance(result, dict):
        return
    fields = {
        "strategy_search": ("matches", "index_version", "degraded_channels"),
        "sympy_calculate": ("value", "normalized_expression", "conditions", "warnings"),
        "math_verify": ("verdict", "findings", "counterexample", "checked_claims"),
        "document_search": ("passages",),
    }
    value = result.get("value")
    summary = {key: result[key] for key in ("status", "error_code", "latency_ms", "citations") if key in result}
    if isinstance(value, dict):
        summary["value"] = {key: value[key] for key in fields.get(name, ()) if key in value}
    text = json.dumps(redact_trace_value(summary), ensure_ascii=False, allow_nan=False)
    if len(text) > 12000:
        text = json.dumps({"truncated": True, "preview": text[:12000]}, ensure_ascii=False)
    identity = redact_trace_value({"task": task_id, "stage": stage, "tool": name, "call_id": call_id})
    prefix = json.dumps(identity, ensure_ascii=False, allow_nan=False)
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [工具调用结果] {prefix} "
          f"来源={'缓存重放' if replayed else '本次调用'} 结果={text}", flush=True)


def log_retrieval_results(task_id, results, solver_cards):
    prefix = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [任务 {task_id}]"
    print(f"{prefix} [策略检索结果] 最终召回={len(results)} 条；"
          f"解题策略卡={'已注入' if solver_cards else '未注入'}", flush=True)
    for rank, item in enumerate(results, 1):
        # Card headers preserve original ranks even when earlier cards are dropped.
        header = f"【策略 {rank}：{item.get('name', 'unknown')}】"
        injected = header in solver_cards
        fields = []
        for key in ("score", "vector_score", "lexical_score", "raw_score", "structure_score"):
            if key not in item:
                continue
            value = item.get(key)
            fields.append(f"{key}={value:.6f}" if isinstance(value, (int, float))
                          and not isinstance(value, bool) and math.isfinite(value) else f"{key}=无")
        identifier = redact_trace_value(str(item.get("id", "unknown"))).replace("\n", " ").replace("\r", " ")
        name = redact_trace_value(str(item.get("name", "unknown"))).replace("\n", " ").replace("\r", " ")
        print(f"{prefix} [最终召回策略] 排名={rank} ID={identifier} 名称={name} "
              f"{' '.join(fields)} 解题注入={'是' if injected else '否'}", flush=True)

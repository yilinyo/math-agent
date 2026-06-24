from typing import Any


def normalize_final_response(answer: Any) -> str:
    text = str(answer or "").strip()
    if not text:
        return "无法确定唯一答案"

    for prefix in ("最终答案：", "最终答案:", "答案：", "答案:", "Answer:", "Final Answer:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()

    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`").strip()
    return text or "无法确定唯一答案"


def fallback_answer(ctx: Any) -> str:
    for candidate in reversed(getattr(ctx, "candidates", [])):
        answer = normalize_final_response(getattr(candidate, "answer", ""))
        if answer:
            return answer
    for raw in reversed(getattr(ctx, "raw_responses", [])):
        answer = normalize_final_response(raw)
        if answer:
            return answer
    return "无法确定唯一答案"

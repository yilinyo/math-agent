"""Bounded strategy-example cards for Action Graph prompts and trace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyCardBundle:
    planner: str
    executor: str
    planner_truncated: bool = False
    executor_truncated: bool = False


def strategy_result_confidence(
    mode: str, result: dict[str, Any], *, high: float = 0.5, low: float = 0.4,
) -> tuple[str, float | None]:
    if mode == "lexical":
        return "high", None
    if high < low:
        raise ValueError("strategy confidence high threshold must be >= low threshold")
    similarity = _number(result.get("vector_score") if mode == "hybrid" else result.get("score"))
    if similarity is not None and similarity >= high:
        return "high", similarity
    if similarity is not None and similarity >= low:
        return "medium", similarity
    return "low", similarity


def build_strategy_cards(
    results: list[dict[str, Any]],
    *,
    max_chars: int,
    detail_levels: list[str] | None = None,
) -> StrategyCardBundle:
    """Render ranked result cards, dropping whole low-ranked cards on overflow."""
    if detail_levels is not None and len(detail_levels) != len(results):
        raise ValueError("detail_levels must match results")
    planner_cards: list[str] = []
    executor_cards: list[str] = []
    planner_size = executor_size = 0
    planner_truncated = executor_truncated = False
    for rank, result in enumerate(results, 1):
        detail = detail_levels[rank - 1] if detail_levels is not None else "high"
        if detail == "low":
            continue
        if detail not in {"high", "medium"}:
            raise ValueError("detail level must be high, medium, or low")
        summary = _card(result, rank, include_example=False)
        executor = _card(result, rank, include_example=detail == "high")
        summary_size = len(summary) + (2 if planner_cards else 0)
        executor_card_size = len(executor) + (2 if executor_cards else 0)
        if planner_size + summary_size <= max_chars:
            planner_cards.append(summary)
            planner_size += summary_size
        else:
            planner_truncated = True
        if executor_size + executor_card_size <= max_chars:
            executor_cards.append(executor)
            executor_size += executor_card_size
        else:
            executor_truncated = True
    return StrategyCardBundle(
        planner="\n\n".join(planner_cards),
        executor="\n\n".join(executor_cards),
        planner_truncated=planner_truncated,
        executor_truncated=executor_truncated,
    )


def trace_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return stable score metadata without serializing an embedding or example twice."""
    return [
        {
            "rank": rank,
            "id": item.get("id"),
            "name": str(item.get("name", "")),
            "score": _number(item.get("score")),
            "raw_score": _number(item.get("raw_score")),
            "structure_score": _number(item.get("structure_score")),
            "lexical_score": _number(item.get("lexical_score")),
            "vector_score": _number(item.get("vector_score")),
            "vector_raw_score": _number(item.get("vector_raw_score")),
            "vector_structure_score": _number(item.get("vector_structure_score")),
            "injection_confidence": str(item.get("injection_confidence", "")) or None,
            "injection_similarity": _number(item.get("injection_similarity")),
            "lexical_rank": _integer(item.get("lexical_rank")),
            "vector_rank": _integer(item.get("vector_rank")),
        }
        for rank, item in enumerate(results, 1)
    ]


def bound_card_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Keep complete cards only, so trace never silently cuts an example."""
    if len(text) <= max_chars:
        return text, False
    cards = [card for card in text.split("\n\n") if card]
    kept: list[str] = []
    used = 0
    for card in cards:
        separator = 2 if kept else 0
        if used + separator + len(card) > max_chars:
            break
        kept.append(card)
        used += separator + len(card)
    return "\n\n".join(kept), True


def _card(item: dict[str, Any], rank: int, *, include_example: bool) -> str:
    lines = [
        f"【策略 {rank}：{item.get('name', 'unknown')}】",
        "该案例仅作方法参考；必须核验其适用条件并独立推出当前题结论。",
        f"标签：{_joined(item.get('tags'))}",
        f"描述：{item.get('description', '')}",
        f"适用条件：{_joined(item.get('applicability'))}",
        "步骤：" + _steps(item.get("steps")),
    ]
    if include_example:
        example = item.get("example") if isinstance(item.get("example"), dict) else {}
        lines.extend([
            "【参考例题】",
            str(example.get("problem", "")),
            "【参考解法】",
            str(example.get("solution", "")),
        ])
    return "\n".join(lines)


def _joined(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(str(item) for item in value)
    return str(value or "")


def _steps(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return "；".join(
        f"{item.get('step', '')}：{item.get('detail', '')}" if isinstance(item, dict) else str(item)
        for item in value
    )


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None

"""Stable document representation used when building strategy embeddings."""
from typing import Any


def build_strategy_text(item: dict[str, Any]) -> str:
    applicability = item.get('applicability', [])
    if not isinstance(applicability, list):
        applicability = [str(applicability)]
    tags = item.get('tags', [])
    if not isinstance(tags, list):
        tags = [str(tags)]
    steps = item.get('steps', [])
    if not isinstance(steps, list):
        steps = []
    step_text = '; '.join(
        f"{str(step.get('step', '')).strip()}: {str(step.get('detail', '')).strip()}"
        for step in steps if isinstance(step, dict)
        and (str(step.get('step', '')).strip() or str(step.get('detail', '')).strip()))
    return (
        f"Strategy: {item.get('name', '').strip()}\n"
        f"Tags: {'; '.join(str(tag).strip() for tag in tags)}\n"
        f"Description: {item.get('description', '').strip()}\n"
        f"Applicable when: {'; '.join(str(part).strip() for part in applicability)}\n"
        f"Key derivation: {step_text}"
    )

"""Deterministic recovery routing for staged solution audits."""

from dataclasses import dataclass
from typing import Literal

from reasoning_agent.custom2.staged_models import StagedAudit


RecoveryAction = Literal[
    "local_repair",
    "proof_completion",
    "strategy_rethink",
    "global_restart",
]


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    reason: str
    target: str


_KNOWN_ERROR_TYPES = {
    "model", "direction", "definition", "calculation", "counterexample",
    "missing_proof", "coverage", "format", "other",
}
_CORE_ROUTE_SIGNALS = (
    "模型", "定义", "状态", "转移", "核心", "主方法", "主路线", "核心引理",
    "最终结论", "model", "definition", "state", "transition", "main method",
    "core lemma", "final conclusion",
)


def normalize_error_type(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _KNOWN_ERROR_TYPES else "other"


def route_recovery(audit: StagedAudit) -> RecoveryDecision:
    """Select recovery scope from one evidence-backed audit without a model call."""
    error_type = normalize_error_type(audit.error_type)
    target = audit.invalid_claim.strip() or audit.first_fatal_error.strip()

    if error_type in {"calculation", "format"}:
        return RecoveryDecision("local_repair", "localized calculation or format defect", target)
    if error_type in {"missing_proof", "coverage"}:
        return RecoveryDecision("proof_completion", "proof obligation is incomplete", target)
    if error_type in {"model", "direction", "definition"}:
        return RecoveryDecision("global_restart", "core model or assumption conflicts with the problem", target)
    if error_type == "counterexample":
        if _affects_core_route(audit):
            return RecoveryDecision("global_restart", "counterexample invalidates the core route", target)
        return RecoveryDecision("local_repair", "counterexample has a bounded affected scope", target)
    return RecoveryDecision("strategy_rethink", "unclassified or repeated-route failure", target)


def _affects_core_route(audit: StagedAudit) -> bool:
    evidence = " ".join((
        audit.invalid_claim,
        audit.affected_reasoning if hasattr(audit, "affected_reasoning") else "",
        audit.first_fatal_error,
        audit.replacement_route,
    )).lower()
    return any(signal.lower() in evidence for signal in _CORE_ROUTE_SIGNALS)

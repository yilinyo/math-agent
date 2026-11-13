"""Rank-fusion retrieval over the lexical and embedding strategy indexes."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from reasoning_agent.lexical_strategy_retrieval import (
    DEFAULT_DATA_DIR,
    get_shared_lexical_strategy_retriever,
)
from reasoning_agent.strategy_retrieval import (
    DEFAULT_MODEL_DIR,
    get_shared_strategy_retriever,
)


DEFAULT_LEXICAL_WEIGHT = 0.3
DEFAULT_VECTOR_WEIGHT = 0.7
DEFAULT_RRF_K = 10
DEFAULT_CANDIDATE_K = 4


def fuse_ranked_results(
    lexical_results: list[dict[str, Any]],
    vector_results: list[dict[str, Any]],
    *,
    top_k: int,
    lexical_weight: float = DEFAULT_LEXICAL_WEIGHT,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[dict[str, Any]]:
    """Fuse two rankings by strategy ID using weighted reciprocal rank."""
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if lexical_weight < 0 or vector_weight < 0 or lexical_weight + vector_weight <= 0:
        raise ValueError("at least one retrieval weight must be positive")
    if rrf_k < 0:
        raise ValueError("rrf_k must be nonnegative")

    merged: dict[str, dict[str, Any]] = {}

    def add_channel(
        results: list[dict[str, Any]], *, channel: str, weight: float,
    ) -> None:
        seen: set[str] = set()
        for rank, source in enumerate(results, 1):
            strategy_id = str(source.get("id", ""))
            if not strategy_id or strategy_id in seen:
                continue
            seen.add(strategy_id)
            entry = merged.setdefault(strategy_id, {
                "item": dict(source),
                "score": 0.0,
                "lexical_rank": None,
                "vector_rank": None,
                "lexical_score": None,
                "vector_score": None,
                "vector_raw_score": None,
                "vector_structure_score": None,
            })
            entry[f"{channel}_rank"] = rank
            entry[f"{channel}_score"] = _number(source.get("score"))
            if channel == "vector":
                entry["vector_raw_score"] = _number(source.get("raw_score"))
                entry["vector_structure_score"] = _number(source.get("structure_score"))
            entry["score"] += weight / (rrf_k + rank)

    add_channel(lexical_results, channel="lexical", weight=lexical_weight)
    add_channel(vector_results, channel="vector", weight=vector_weight)
    ordered = sorted(
        merged.values(),
        key=lambda entry: (-entry["score"], str(entry["item"].get("id", ""))),
    )
    fused: list[dict[str, Any]] = []
    for entry in ordered[:top_k]:
        item = dict(entry["item"])
        item.update(
            score=float(entry["score"]),
            lexical_rank=entry["lexical_rank"],
            vector_rank=entry["vector_rank"],
            lexical_score=entry["lexical_score"],
            vector_score=entry["vector_score"],
            vector_raw_score=entry["vector_raw_score"],
            vector_structure_score=entry["vector_structure_score"],
        )
        fused.append(item)
    return fused


def fuse_weighted_results(
    lexical_results: list[dict[str, Any]],
    vector_results: list[dict[str, Any]],
    *,
    top_k: int,
    lexical_weight: float = DEFAULT_LEXICAL_WEIGHT,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    agreement_bonus: float = 0.05,
) -> list[dict[str, Any]]:
    """Fuse candidates using normalized channel scores instead of rank only."""
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if lexical_weight < 0 or vector_weight < 0 or lexical_weight + vector_weight <= 0:
        raise ValueError("at least one retrieval weight must be positive")
    if agreement_bonus < 0:
        raise ValueError("agreement_bonus must be nonnegative")

    merged: dict[str, dict[str, Any]] = {}

    def add_channel(results: list[dict[str, Any]], *, channel: str) -> None:
        scores = [_number(item.get("score")) for item in results]
        finite_scores = [score for score in scores if score is not None]
        low = min(finite_scores) if finite_scores else 0.0
        high = max(finite_scores) if finite_scores else 0.0
        for rank, (source, raw_score) in enumerate(zip(results, scores), 1):
            strategy_id = str(source.get("id", ""))
            if not strategy_id:
                continue
            entry = merged.setdefault(strategy_id, {
                "item": dict(source),
                "lexical_rank": None,
                "vector_rank": None,
                "lexical_score": None,
                "vector_score": None,
                "vector_raw_score": None,
                "vector_structure_score": None,
                "lexical_normalized_score": 0.0,
                "vector_normalized_score": 0.0,
            })
            entry[f"{channel}_rank"] = rank
            entry[f"{channel}_score"] = raw_score
            entry[f"{channel}_normalized_score"] = (
                1.0 if high == low and raw_score is not None
                else ((raw_score - low) / (high - low) if raw_score is not None and high > low else 0.0)
            )
            if channel == "vector":
                entry["vector_raw_score"] = _number(source.get("raw_score"))
                entry["vector_structure_score"] = _number(source.get("structure_score"))

    add_channel(lexical_results, channel="lexical")
    add_channel(vector_results, channel="vector")
    for entry in merged.values():
        entry["score"] = (
            lexical_weight * entry["lexical_normalized_score"]
            + vector_weight * entry["vector_normalized_score"]
            + (agreement_bonus if entry["lexical_rank"] and entry["vector_rank"] else 0.0)
        )
    ordered = sorted(
        merged.values(),
        key=lambda entry: (-entry["score"], str(entry["item"].get("id", ""))),
    )
    fused: list[dict[str, Any]] = []
    for entry in ordered[:top_k]:
        item = dict(entry["item"])
        item.update(
            score=float(entry["score"]),
            lexical_rank=entry["lexical_rank"],
            vector_rank=entry["vector_rank"],
            lexical_score=entry["lexical_score"],
            vector_score=entry["vector_score"],
            vector_raw_score=entry["vector_raw_score"],
            vector_structure_score=entry["vector_structure_score"],
            lexical_normalized_score=float(entry["lexical_normalized_score"]),
            vector_normalized_score=float(entry["vector_normalized_score"]),
        )
        fused.append(item)
    return fused


class HybridStrategyRetriever:
    """Retrieve from both local indexes and combine their rankings."""

    def __init__(
        self,
        *,
        data_dir: Path = DEFAULT_DATA_DIR,
        model_dir: Path = DEFAULT_MODEL_DIR,
        device: str | None = None,
        lexical_weight: float = DEFAULT_LEXICAL_WEIGHT,
        vector_weight: float = DEFAULT_VECTOR_WEIGHT,
        rrf_k: int = DEFAULT_RRF_K,
        candidate_k: int = DEFAULT_CANDIDATE_K,
        fusion_mode: str = "rrf",
    ) -> None:
        if candidate_k < 1:
            raise ValueError("candidate_k must be positive")
        if fusion_mode not in {"rrf", "weighted"}:
            raise ValueError("fusion_mode must be 'rrf' or 'weighted'")
        self.data_dir = Path(data_dir)
        self.model_dir = Path(model_dir)
        self.device = device
        self.lexical_weight = lexical_weight
        self.vector_weight = vector_weight
        self.rrf_k = rrf_k
        self.candidate_k = candidate_k
        self.fusion_mode = fusion_mode

    def retrieve_for_structure(
        self,
        raw_problem: str,
        retrieval_text: str,
        *,
        top_k: int = 5,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        pool_size = max(self.candidate_k, top_k)
        channel_errors: dict[str, str] = {}
        lexical: dict[str, Any] | None = None
        vector: dict[str, Any] | None = None
        try:
            lexical = get_shared_lexical_strategy_retriever(
                data_dir=self.data_dir,
            ).retrieve_for_structure(
                raw_problem, retrieval_text, top_k=pool_size, metadata=metadata,
            )
        except Exception as exc:
            channel_errors["lexical"] = type(exc).__name__
        try:
            vector = get_shared_strategy_retriever(
                data_dir=self.data_dir, model_dir=self.model_dir, device=self.device,
            ).retrieve_for_structure(
                raw_problem, retrieval_text, top_k=pool_size,
            )
        except Exception as exc:
            channel_errors["vector"] = type(exc).__name__
        if lexical is None and vector is None:
            raise RuntimeError(
                "Both lexical and vector strategy retrieval failed: "
                + ", ".join(f"{name}={error}" for name, error in channel_errors.items())
            )

        lexical_results = list(lexical.get("results", [])) if lexical else []
        vector_results = list(vector.get("results", [])) if vector else []
        if self.fusion_mode == "weighted":
            results = fuse_weighted_results(
                lexical_results, vector_results, top_k=top_k,
                lexical_weight=self.lexical_weight,
                vector_weight=self.vector_weight,
            )
        else:
            results = fuse_ranked_results(
                lexical_results, vector_results, top_k=top_k,
                lexical_weight=self.lexical_weight,
                vector_weight=self.vector_weight,
                rrf_k=self.rrf_k,
            )
        return {
            "retrieval_text": (
                lexical.get("retrieval_text", retrieval_text)
                if lexical else vector.get("retrieval_text", retrieval_text)
            ),
            "results": results,
            "index_version": f"hybrid_{self.fusion_mode}_v1",
            "structured_query_used": (
                lexical.get("structured_query_used", True) if lexical else True
            ),
            "degraded_channels": channel_errors,
        }


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


_SHARED: dict[tuple[Path, Path, str | None], HybridStrategyRetriever] = {}
_SHARED_LOCK = threading.Lock()


def get_shared_hybrid_strategy_retriever(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    model_dir: Path = DEFAULT_MODEL_DIR,
    device: str | None = None,
) -> HybridStrategyRetriever:
    key = (Path(data_dir).resolve(), Path(model_dir).resolve(), device)
    with _SHARED_LOCK:
        retriever = _SHARED.get(key)
        if retriever is None:
            retriever = HybridStrategyRetriever(
                data_dir=key[0], model_dir=key[1], device=device,
            )
            _SHARED[key] = retriever
        return retriever

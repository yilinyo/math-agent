"""Build normalized retrieval embeddings for the ReasonFlux strategy corpus.

The resulting files are intentionally simple: the row at position ``i`` in
``strategy_embeddings.npy`` belongs to the strategy with ``id == i`` in
``strategy_meta.json``.  Retrieval can therefore use a NumPy matrix product
without an external vector database.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reasoning_agent.strategy_documents import build_strategy_text


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "strategyrag" / "ReasonFlux_v2_template.json"
DEFAULT_MODEL = REPO_ROOT / "strategyrag" / "Qwen3-Embedding-0.6B"
DEFAULT_OUTPUT = REPO_ROOT / "strategy_data"
MODEL_ID = "Qwen/Qwen3-Embedding-0.6B"
FIELDS_USED = ["name", "tags", "description", "applicability", "steps"]


def preferred_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--device", default=preferred_device())
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("--batch-size must be positive")
    if not args.dataset.is_file():
        raise FileNotFoundError(f"Strategy dataset not found: {args.dataset}")
    if not args.model.is_dir():
        raise FileNotFoundError(f"Embedding model not found: {args.model}")

    strategies = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not isinstance(strategies, list) or not strategies:
        raise ValueError("Dataset must be a non-empty JSON list")
    texts = [build_strategy_text(item) for item in strategies]

    model = SentenceTransformer(str(args.model), device=args.device)
    embeddings = model.encode(
        texts,
        batch_size=args.batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if embeddings.shape != (len(strategies), 1024):
        raise ValueError(f"Expected ({len(strategies)}, 1024) embeddings, got {embeddings.shape}")
    # Sentence Transformers is asked to normalize, but explicitly normalize
    # again after moving MPS results into NumPy.  This makes the on-disk
    # float32 representation satisfy the cosine-via-dot-product invariant
    # regardless of accelerator rounding behaviour.
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    if not np.isfinite(norms).all() or np.any(norms == 0):
        raise ValueError("Embedding output contains a non-finite or zero row")
    embeddings /= norms
    if not np.allclose(np.linalg.norm(embeddings, axis=1), 1.0, atol=1e-5):
        raise ValueError("Embedding rows are not L2-normalized after normalization")

    metadata = [{"id": index, **item} for index, item in enumerate(strategies)]
    index = {
        "dataset": "ReasonFlux-V2-Template",
        "num_strategies": len(strategies),
        "embedding_model": MODEL_ID,
        "embedding_dim": 1024,
        "normalized": True,
        "dtype": "float32",
        "fields_used": FIELDS_USED,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    embedding_path = args.output_dir / "strategy_embeddings.npy"
    metadata_path = args.output_dir / "strategy_meta.json"
    index_path = args.output_dir / "strategy_index.json"
    temporary_embedding = args.output_dir / "strategy_embeddings.tmp.npy"
    temporary_metadata = args.output_dir / "strategy_meta.tmp.json"
    temporary_index = args.output_dir / "strategy_index.tmp.json"
    np.save(temporary_embedding, embeddings)
    temporary_metadata.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary_index.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_embedding.replace(embedding_path)
    temporary_metadata.replace(metadata_path)
    temporary_index.replace(index_path)
    print(f"Wrote {embedding_path} with shape {embeddings.shape}")
    print(f"Wrote {metadata_path}")
    print(f"Wrote {index_path}")


if __name__ == "__main__":
    main()

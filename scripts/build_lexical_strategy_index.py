"""Build the checked-in dependency-free lexical strategy index."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reasoning_agent.lexical_strategy_retrieval import build_lexical_payloads  # noqa: E402


def atomic_json(path: Path, value: object) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def build(data_dir: Path) -> None:
    cards = json.loads((data_dir / "strategy_meta.json").read_text(encoding="utf-8"))
    index, manifest = build_lexical_payloads(cards)
    atomic_json(data_dir / "strategy_lexical_index.json", index)
    atomic_json(data_dir / "strategy_lexical_manifest.json", manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "strategy_data")
    build(parser.parse_args().data_dir)


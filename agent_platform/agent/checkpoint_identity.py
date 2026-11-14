"""Source identity with a bounded mapping for the structural migration."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[2]
LEGACY_DIRS = ("agent_platform", "reasoning_agent/custom2", "reasoning_agent/custom")
RESOURCE_FILES = (
    "reasoning_agent/action_graph/strategy_cards.py", "reasoning_agent/strategy_retrieval.py",
    "reasoning_agent/lexical_strategy_retrieval.py", "reasoning_agent/hybrid_strategy_retrieval.py",
    "reasoning_agent/strategy_documents.py", "reasoning_agent/resource_files.py",
    "strategy_data/strategy_lexical_manifest.json", "strategy_data/strategy_index.json",
)


def source_files(root: Path) -> dict[str, bytes]:
    paths = set()
    for folder in LEGACY_DIRS:
        paths.update((root / folder).rglob("*.py"))
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(paths)}


def logical_sources(root: Path) -> dict[str, bytes]:
    current = source_files(root)
    compatibility = root / "agent_platform/agent/_compat"
    try:
        manifest = json.loads((compatibility / "migration.json").read_text())
        if not isinstance(manifest, dict):
            return current
        if not isinstance(manifest.get("protected"), dict):
            return current
        if not all(isinstance(manifest.get(key), list) and all(isinstance(path, str)
                   for path in manifest[key]) for key in ("new_paths", "removed_paths")):
            return current
        snapshot_bytes = (compatibility / "source_snapshot.json").read_bytes()
        if hashlib.sha256(snapshot_bytes).hexdigest() != manifest["snapshot_sha256"]:
            return current
        if any(path in current for path in manifest["removed_paths"]):
            return current
        for relative, expected in manifest["protected"].items():
            value = current.get(relative)
            if value is None or hashlib.sha256(value).hexdigest() != expected:
                return current
        snapshot = json.loads(snapshot_bytes)
        if not isinstance(snapshot, dict) or not all(isinstance(path, str) and isinstance(value, str)
                                                     for path, value in snapshot.items()):
            return current
    except (OSError, ValueError, KeyError, TypeError):
        return current
    # Unlisted new files remain in the identity, so additions cannot evade validation.
    logical = {path: value for path, value in current.items() if path not in manifest["new_paths"]}
    logical.update({path: value.encode() for path, value in snapshot.items()})
    return logical


def config_hash(config, client, client_identity, tools, function_calling, *, root=None):
    root = SOURCE_ROOT if root is None else root
    digest = hashlib.sha256(json.dumps(asdict(config), sort_keys=True).encode())
    identity = client_identity or f"{type(client).__module__}.{type(client).__qualname__}"
    digest.update(identity.encode())
    digest.update(f"{tools.identity}:{function_calling}".encode())
    sources = logical_sources(root)
    for folder in LEGACY_DIRS:
        for relative in sorted(path for path in sources if path.startswith(folder + "/")):
            digest.update(relative.encode())
            digest.update(sources[relative])
    for relative in sorted(path for path in sources if not any(
            path.startswith(folder + "/") for folder in LEGACY_DIRS)):
        digest.update(relative.encode())
        digest.update(sources[relative])
    for relative in RESOURCE_FILES:
        path = root / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes() if path.is_file() else b"missing")
    for folder in ("skill2_en", "skill2"):
        for path in sorted((root / folder).glob("*.md")):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()

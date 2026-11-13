#!/usr/bin/env python3
"""Append, validate, and update submission log records."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_FIELDS = (
    "commit_sha:",
    "timestamp:",
    "change_summary:",
    "logic_details:",
    "validation:",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_text(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"log file does not exist: {path}")
    return path.read_text(encoding="utf-8")


def split_records(text: str) -> list[str]:
    return re.split(r"(?=^## )", text, flags=re.MULTILINE)[1:]


def append_record(args: argparse.Namespace) -> None:
    path = Path(args.log)
    text = read_text(path)
    if not SHA_RE.fullmatch(args.commit_sha):
        raise SystemExit("commit-sha must be a 40-character full SHA")
    if f"commit_sha: `{args.commit_sha}`" in text:
        raise SystemExit(f"commit SHA already recorded: {args.commit_sha}")

    timestamp = args.timestamp or now_iso()
    score_block = (
        f"- score: `{args.score}`\n"
        f"- score_source: {args.score_source or ''}\n"
        f"- score_updated_at: `{timestamp}`\n"
        f"- score_notes: {args.score_notes or ''}\n"
        if args.score
        else "- score:\n- score_source:\n- score_updated_at:\n- score_notes:\n"
    )

    details = [
        line.strip()
        for line in args.logic_details.replace("\\n", "\n").splitlines()
        if line.strip()
    ]
    detail_block = "\n".join(f"  - {line}" for line in details) or "  -"
    record = f"""
## {timestamp} - {args.title}

- source_branch: `{args.source_branch}`
- target_branch: `{args.target_branch}`
- commit_sha: `{args.commit_sha}`
- timestamp: `{timestamp}`
- status: `submitted`
{score_block}- validation: `{args.validation}`
- change_summary: {args.summary}
- logic_details:
{detail_block}
- notes: {args.notes or ''}
"""
    path.write_text(text.rstrip() + "\n" + record.strip() + "\n", encoding="utf-8")
    print(f"appended submission record for {args.commit_sha}")


def validate(args: argparse.Namespace) -> None:
    text = read_text(Path(args.log))
    blocks = split_records(text)
    errors: list[str] = []
    seen: set[str] = set()
    for index, block in enumerate(blocks, start=1):
        for field in REQUIRED_FIELDS:
            if field not in block:
                errors.append(f"record {index}: missing {field}")
        sha_match = re.search(r"^- commit_sha: `([^`]+)`", block, re.MULTILINE)
        if not sha_match or not SHA_RE.fullmatch(sha_match.group(1)):
            errors.append(f"record {index}: commit_sha must be a full 40-character SHA")
        else:
            sha = sha_match.group(1)
            if sha in seen:
                errors.append(f"record {index}: duplicate commit_sha {sha}")
            seen.add(sha)
        for field in ("change_summary", "validation"):
            field_match = re.search(rf"^- {field}:\s*(.*)$", block, re.MULTILINE)
            if not field_match or not field_match.group(1).strip():
                errors.append(f"record {index}: {field} is empty")
        logic_match = re.search(r"^- logic_details:\s*$([\s\S]*?)(?=^- \w|\Z)", block, re.MULTILINE)
        if not logic_match or not logic_match.group(1).strip():
            errors.append(f"record {index}: logic_details is empty")
        if args.require_score and not re.search(r"^- score:\s*`[^`]+`", block, re.MULTILINE):
            errors.append(f"record {index}: score is required")
        if args.source_branch and f"source_branch: `{args.source_branch}`" not in block:
            errors.append(f"record {index}: unexpected source branch")
        if args.target_branch and f"target_branch: `{args.target_branch}`" not in block:
            errors.append(f"record {index}: unexpected target branch")

    if errors:
        print("validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"validated {len(blocks)} submission record(s)")


def update_score(args: argparse.Namespace) -> None:
    path = Path(args.log)
    text = read_text(path)
    if not SHA_RE.fullmatch(args.commit_sha):
        raise SystemExit("commit-sha must be a 40-character full SHA")

    pattern = re.compile(
        rf"(^## .*?^- commit_sha: `{re.escape(args.commit_sha)}`.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        raise SystemExit(f"submission record not found: {args.commit_sha}")

    block = match.group(1)
    timestamp = args.updated_at or now_iso()
    block = re.sub(r"^- score:.*$", f"- score: `{args.score}`", block, count=1, flags=re.MULTILINE)
    block = re.sub(
        r"^- score_source:.*$",
        f"- score_source: {args.score_source or ''}",
        block,
        count=1,
        flags=re.MULTILINE,
    )
    block = re.sub(
        r"^- score_updated_at:.*$",
        f"- score_updated_at: `{timestamp}`",
        block,
        count=1,
        flags=re.MULTILINE,
    )
    block = re.sub(
        r"^- score_notes:.*$",
        f"- score_notes: {args.score_notes or ''}",
        block,
        count=1,
        flags=re.MULTILINE,
    )
    block = re.sub(r"^- status:.*$", "- status: `evaluated`", block, count=1, flags=re.MULTILINE)
    path.write_text(text[: match.start()] + block + text[match.end() :], encoding="utf-8")
    print(f"updated score for {args.commit_sha}")


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    append = sub.add_parser("append")
    append.add_argument("--log", required=True)
    append.add_argument("--commit-sha", required=True)
    append.add_argument("--source-branch", default="main")
    append.add_argument("--target-branch", default="judge")
    append.add_argument("--title", required=True)
    append.add_argument("--summary", required=True)
    append.add_argument("--logic-details", required=True)
    append.add_argument("--validation", required=True)
    append.add_argument("--timestamp")
    append.add_argument("--score")
    append.add_argument("--score-source")
    append.add_argument("--score-notes")
    append.add_argument("--notes")
    append.set_defaults(func=append_record)

    validate_cmd = sub.add_parser("validate")
    validate_cmd.add_argument("--log", required=True)
    validate_cmd.add_argument("--source-branch", default="main")
    validate_cmd.add_argument("--target-branch", default="judge")
    validate_cmd.add_argument("--require-score", action="store_true")
    validate_cmd.set_defaults(func=validate)

    score = sub.add_parser("update-score")
    score.add_argument("--log", required=True)
    score.add_argument("--commit-sha", required=True)
    score.add_argument("--score", required=True)
    score.add_argument("--score-source")
    score.add_argument("--score-notes")
    score.add_argument("--updated-at")
    score.set_defaults(func=update_score)
    return root


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

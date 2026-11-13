"""Existing public solution section extraction."""
import re
from agent_platform.safety import sanitize_text
from agent_platform.presentation.instructions import SECTIONS

def strip_private_thoughts(draft: str) -> str:
    text = str(draft or "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"<(think|analysis)\b[^>]*>[\s\S]*?(?:</\1\s*>|\Z)", "", text, flags=re.I)


def _parse_solution(draft: str) -> tuple[dict[str, str], str]:
    # Ignore private thought tags and executable checks, including unfinished blocks.
    text = strip_private_thoughts(draft)
    sections: dict[str, list[str]] = {}
    current = None
    fence = None
    check_block = False
    cleaned_lines = []
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if (
                marker
                and marker[1][0] == fence[0]
                and len(marker[1]) >= len(fence)
                and not marker[2].strip()
            ):
                fence = None
                if check_block:
                    check_block = False
                    continue
            if check_block:
                continue
        elif marker:
            fence = marker[1]
            check_block = marker[2].strip().lower().split(maxsplit=1)[:1] == ["check"]
            if check_block:
                continue
        cleaned_lines.append(line)
        if not fence and not marker:
            heading = re.match(r"^\s{0,3}##\s+(.+?)\s*#*\s*$", line)
            if heading:
                current = heading[1] if heading[1] in SECTIONS else None
                if current:
                    sections.setdefault(current, [])
                continue
        if current:
            sections[current].append(line)
    return (
        {name: sanitize_text("\n".join(lines).strip()) for name, lines in sections.items()},
        sanitize_text("\n".join(cleaned_lines)),
    )


def public_sections(draft: str) -> dict[str, str]:
    return _parse_solution(draft)[0]

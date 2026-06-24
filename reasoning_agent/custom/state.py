from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskPhase(str, Enum):
    RUN = "run"
    VERIFY = "verify"
    FINALIZE = "finalize"
    DONE = "done"


@dataclass
class Candidate:
    answer: str
    source: str
    reasoning_summary: str = ""


@dataclass
class TaskResult:
    final_response: str
    trace: list[dict[str, Any]] = field(default_factory=list)

"""Existing checkpoint validation and restoration, without a state migration."""
import copy
import hashlib
from datetime import datetime, timedelta, timezone
from pydantic import ValidationError
from agent_platform.runtime import CheckpointIncompatible, RuntimeContext
from agent_platform.presentation import RESOLVED_STYLES, requested_style
from agent_platform.agent.state import GRAPH_STAGES, WORKFLOW_VERSION, GraphCheckpoint, GraphState


class CheckpointRuntime:
    def checkpoint_compatible(self, checkpoint: dict | None) -> bool:
        if checkpoint is None:
            return True
        try:
            parsed = GraphCheckpoint.model_validate(checkpoint)
        except ValidationError:
            return False
        effective = parsed.adapter.get("_response_style")
        if parsed.response_style == "auto":
            if not isinstance(effective, str) or effective not in RESOLVED_STYLES:
                return False
        elif effective != parsed.response_style:
            return False
        if parsed.next_stage in {*GRAPH_STAGES, "terminal"} - {"profile", "finalize", "terminal"} and parsed.profile is None:
            return False
        if parsed.next_stage in {"solve", "tool", "verify", "repair", "emergency", "arbitrate"} and parsed.plan is None:
            return False
        if parsed.next_stage in {"tool", "verify", "repair"} and not parsed.draft:
            return False
        if parsed.next_stage == "verify" and not isinstance(parsed.checks.get("ok"), bool):
            return False
        if parsed.next_stage == "repair" and parsed.verification is None:
            return False
        if parsed.next_stage == "arbitrate" and not parsed.candidates:
            return False
        if parsed.next_stage == "terminal" and not parsed.final_response.strip():
            return False
        return (parsed.schema_version == WORKFLOW_VERSION
                and parsed.config_hash == self.config_hash
                and parsed.next_stage in {*GRAPH_STAGES, "terminal"}
                and parsed.repair_count <= parsed.max_repairs
                and parsed.solve_calls_used <= parsed.max_solve_calls)

    def _load(self, context: RuntimeContext) -> GraphState:
        if not context.deadline_at:
            context.deadline_at = datetime.now(timezone.utc) + timedelta(seconds=1200)
        problem_hash = hashlib.sha256(context.problem.encode()).hexdigest()
        if context.checkpoint is not None:
            state = copy.deepcopy(context.checkpoint)
            if (not self.checkpoint_compatible(state)
                    or state.get("task_id") != context.task_id
                    or state.get("session_id") != context.session_id
                    or state.get("problem_hash") != problem_hash
                    or state.get("response_style") != requested_style(context.metadata)
                    or state.get("deadline_at") != context.deadline_at.isoformat()):
                raise CheckpointIncompatible("checkpoint_incompatible")
            return state
        max_repairs = min(3, max(0, int(self.config.custom2_max_repairs)))
        solve_multiplier = 2 if self.config.staged_solver_compressed_retry_enabled else 1
        return {
            "schema_version": WORKFLOW_VERSION, "task_id": context.task_id,
            "session_id": context.session_id, "problem_hash": problem_hash,
            "config_hash": self.config_hash, "deadline_at": context.deadline_at.isoformat(),
            "repair_count": 0, "max_repairs": max_repairs, "solve_calls_used": 0,
            "max_solve_calls": (max_repairs + 1) * solve_multiplier, "next_stage": "profile",
            "adapter": {}, "recoverable_error": "",
            "response_style": requested_style(context.metadata),
            "workflow_started_at": datetime.now(timezone.utc).isoformat(), "candidates": [],
            "convergence_due": False, "return_due": False, "recovery_action": None, "partial_solution": "",
        }

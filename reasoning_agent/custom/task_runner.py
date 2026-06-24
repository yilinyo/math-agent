from typing import Any

from reasoning_agent.custom.config import AgentConfig
from reasoning_agent.custom.runner.context import RunnerContext
from reasoning_agent.custom.runner.loop import ToolUseRunner
from reasoning_agent.custom.parsers.final_answer_parser import fallback_answer, normalize_final_response
from reasoning_agent.custom.state import TaskResult
from reasoning_agent.custom.tools.executor import ToolExecutor
from reasoning_agent.custom.verifier.answer_verifier import AnswerVerifier


class TaskRunner:
    """Runs one problem from input normalization to final response."""

    def __init__(
        self,
        client: Any,
        tools: dict[str, Any],
        config: AgentConfig,
    ) -> None:
        self.client = client
        self.config = config
        self.tool_executor = ToolExecutor(tools=tools, config=config)
        self.tool_use_runner = ToolUseRunner(
            client=client,
            tool_executor=self.tool_executor,
            config=config,
        )
        self.verifier = AnswerVerifier()

    def run(self, problem: str, metadata: dict | None) -> TaskResult:
        ctx = RunnerContext.create(problem=problem, metadata=metadata)
        try:
            candidate = self.tool_use_runner.run(ctx)
            ctx.candidates.append(candidate)
            verification = self.verifier.verify(ctx, candidate)
            ctx.trace.append({"step": "verify", "content": verification})
            final_response = normalize_final_response(candidate.answer)
        except Exception as exc:  # noqa: BLE001 - keep platform output contract stable.
            ctx.errors.append({"type": type(exc).__name__, "message": str(exc)})
            ctx.trace.append(
                {
                    "step": "error",
                    "content": {"type": type(exc).__name__, "message": str(exc)},
                }
            )
            final_response = fallback_answer(ctx)

        ctx.trace.append({"step": "finalize", "content": {"answer": final_response}})
        return TaskResult(final_response=final_response, trace=ctx.trace)

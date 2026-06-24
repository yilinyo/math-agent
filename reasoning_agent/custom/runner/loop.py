from typing import Any

from reasoning_agent.custom.config import AgentConfig
from reasoning_agent.custom.runner.context import RunnerContext
from reasoning_agent.custom.errors import (
    EmptyModelResponse,
    ModelBudgetExceeded,
    ToolBudgetExceeded,
)
from reasoning_agent.custom.runner.events import FinalAnswerEvent, InvalidEvent, ToolCallEvent
from reasoning_agent.custom.parsers.final_answer_parser import fallback_answer
from reasoning_agent.custom.parsers.tool_call_parser import parse_model_event
from reasoning_agent.custom.runner.policy import RunnerPolicy
from reasoning_agent.custom.prompts.tool_use import build_observation_message
from reasoning_agent.custom.state import Candidate
from reasoning_agent.custom.tools.executor import ToolExecutor


class ToolUseRunner:
    """Controlled ReAct-style loop for one problem."""

    def __init__(
        self,
        client: Any,
        tool_executor: ToolExecutor,
        config: AgentConfig,
    ) -> None:
        self.client = client
        self.tool_executor = tool_executor
        self.config = config
        self.policy = RunnerPolicy(config)

    def run(self, ctx: RunnerContext) -> Candidate:
        while not self.policy.should_stop(ctx):
            raw = self._chat(ctx)
            event = parse_model_event(raw)
            ctx.trace.append({"step": "model_event", "content": {"type": event.type}})

            if isinstance(event, FinalAnswerEvent):
                return Candidate(
                    answer=event.answer,
                    source="tool_loop",
                    reasoning_summary=event.reasoning_summary,
                )

            if isinstance(event, ToolCallEvent):
                if not self.policy.can_call_tool(ctx):
                    raise ToolBudgetExceeded("tool call budget exhausted")
                ctx.tool_calls += 1
                observation = self.tool_executor.execute(event.name, event.arguments)
                ctx.add_observation(observation)
                ctx.messages.append(build_observation_message(observation))
                ctx.loop_steps += 1
                continue

            if isinstance(event, InvalidEvent):
                ctx.errors.append({"type": "InvalidModelResponse", "message": event.message})
                return Candidate(answer=fallback_answer(ctx), source="fallback")

        raise ModelBudgetExceeded("model call budget exhausted")

    def _chat(self, ctx: RunnerContext) -> str:
        if ctx.model_calls >= self.config.max_model_calls:
            raise ModelBudgetExceeded("model call budget exhausted")

        ctx.model_calls += 1
        ctx.loop_steps += 1
        response = self.client.chat(
            messages=ctx.messages,
            temperature=self.config.tool_loop_temperature,
            max_tokens=self.config.tool_loop_max_tokens,
        )
        if not isinstance(response, str) or not response.strip():
            raise EmptyModelResponse("client.chat returned empty content")

        text = response.strip()[: self.config.max_response_chars]
        ctx.raw_responses.append(text)
        ctx.trace.append(
            {
                "step": "model_call",
                "content": {"call_index": ctx.model_calls, "chars": len(text)},
            }
        )
        return text

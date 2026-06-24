import json
from typing import Any

from reasoning_agent.custom.prompts.system import SYSTEM_PROMPT


def build_initial_messages(problem: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "请解决下面的数学题。你每次只能输出一个 JSON 对象。\n"
                "若已经可以作答，输出："
                "{\"type\":\"final_answer\",\"answer\":\"...\",\"reasoning_summary\":\"...\"}\n"
                "若需要调用工具，输出："
                "{\"type\":\"tool_call\",\"tool\":\"工具名\",\"arguments\":{}}\n"
                "当前脚手架暂未开放数学工具；能直接推理时请输出 final_answer。\n\n"
                f"题目：\n{problem}"
            ),
        },
    ]


def build_observation_message(observation: dict[str, Any]) -> dict[str, str]:
    return {
        "role": "user",
        "content": "工具返回结果：\n" + json.dumps(observation, ensure_ascii=False),
    }

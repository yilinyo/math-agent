import pytest

from reasoning_agent.custom.config import AgentConfig
from reasoning_agent.custom2.staged_models import StagedStrategy
from reasoning_agent.custom2.staged_runtime import StagedReasoningRuntime
from reasoning_agent.custom2.text_models import ProblemProfile


def draft(final, steps="Apply the definition and check the denominator."):
    return ("## 问题分析\nUse the supplied definition.\n"
            f"## 详细解题步骤\n{steps}\n## 最终答案\n{final}\n"
            "## 关键验证点\nThe inputs satisfy the stated conditions.")


def check(candidate):
    runtime = StagedReasoningRuntime(object(), AgentConfig())
    runtime._final_profile = ProblemProfile(answer_mode="computation")
    result = runtime._local_checks("Compute the requested value.", runtime._final_profile,
                                   StagedStrategy(), candidate)
    return runtime, result


@pytest.mark.parametrize("final", [
    r"- 适用条件：$a,b\geq0$ 且 $a+b>0$。" "\n" r"- 指标值：$\boxed{\dfrac{8}{5}}$（即 $\boxed{1.6}$）。",
    r"计算结果为 $\boxed{\frac{2}{5}}$，等价地 $\boxed{0.4}$。",
    r"\boxed{\frac{25}{8}}=\boxed{3.125}",
    r"\boxed{\frac{1}{\frac{3}{2}}}=\boxed{2/3}",
    r"\boxed{2^3}=\boxed{8}",
    r"\boxed{-\frac{3}{4}}=\boxed{-0.75}",
    r"\boxed{0.1+0.2}=\boxed{0.3}",
    r"\boxed{x^2+1}=\boxed{x^2+1}",
    r"条件已经满足，最终结果为 $\boxed{7}$。",
])
def test_equivalent_answers_and_surrounding_prose_are_accepted(final):
    candidate = draft(final)
    runtime, checks = check(candidate)
    assert checks["format_failures"] == []
    assert runtime._candidate_acceptable(candidate)
    assert runtime._final_result(candidate)["final_response"] != "无法确定唯一答案"


@pytest.mark.parametrize("final", [
    r"\boxed{\frac{8}{5}}\quad\boxed{1.7}",
    r"\boxed{\frac{1}{3}}\quad\boxed{0.333333333333}",
    r"\boxed{9007199254740992}\quad\boxed{9007199254740993.0}",
    r"\boxed{x+1}\quad\boxed{x-1}",
    r"\boxed{1/0}\quad\boxed{2}",
    r"\boxed{2^{999999}}\quad\boxed{1}",
    r"\boxed{__import__('os')}\quad\boxed{1}",
])
def test_conflicting_or_unverifiable_distinct_answers_remain_rejected(final):
    candidate = draft(final)
    runtime, checks = check(candidate)
    assert "multiple_final_candidates" in checks["format_failures"]
    assert not runtime._candidate_acceptable(candidate)


@pytest.mark.parametrize("final", ["计算结果还需要讨论。", r"\boxed{结果见上文}"])
def test_prose_without_a_usable_quantitative_answer_is_not_accepted(final):
    runtime, _ = check(draft(final))
    assert not runtime._candidate_acceptable(draft(final))


def test_accepting_equivalent_answer_format_does_not_override_a_false_calculation():
    candidate = draft(r"值为 $\boxed{\frac{2}{5}}$，即 $\boxed{0.4}$。", steps="$2+3=6$。")
    runtime, checks = check(candidate)
    assert checks["format_failures"] == []
    assert checks["hard_failures"]
    assert not runtime._candidate_acceptable(candidate)


def test_equivalence_check_respects_its_budget():
    from reasoning_agent.custom2.staged_answer_extractor import final_answer_format_failures

    assert final_answer_format_failures(draft(r"\boxed{1/2}=\boxed{0.5}"), "computation", timeout=0) == [
        "multiple_final_candidates",
    ]


@pytest.mark.parametrize("answer_mode", ["choice", "judgment", "fill_blank", "proof"])
def test_text_answer_modes_keep_their_chinese_answer_support(answer_mode):
    from reasoning_agent.custom2.staged_answer_extractor import final_answer_format_failures

    assert final_answer_format_failures(draft(r"\boxed{成立}"), answer_mode) == []

# ABOUTME: Tests for the variant-generation eval's pure grading: Jev request shapes, grades, judge helpers, traces.
# ABOUTME: Uses the real claude_agent_sdk message types so trace shaping is checked against what the SDK emits.

import pytest
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from evals import grading

CITED = ["- Shipped syseng-oncall v1.1.0, raising the eval pass rate from 62% to 94%."]
POOL = CITED + ["- Managed Kubernetes clusters (50+ nodes) for hundreds of developers."]
CLAIM = "Shipped syseng-oncall v1.1.0, raising the eval pass rate from 62% to 94%."


def _answers(
    relation="supports",
    confidence=0.9,
    unstated=0.1,
    delivery=0.1,
    ownership=0.1,
    adoption=0.1,
    voice=0.1,
    trace=True,
):
    answers = {
        "pool": {"unstated": {"noul": unstated}},
        "voice": {rule: {"noul": voice} for rule in grading.VOICE_QUESTIONS},
    }
    if trace:
        answers["trace"] = {
            "relation": {"choice": relation, "confidence": confidence},
            "delivery_overclaim": {"noul": delivery},
            "ownership_overclaim": {"noul": ownership},
            "adoption_overclaim": {"noul": adoption},
        }
    return answers


def test_cited_variant_gets_trace_pool_and_voice_requests_each_with_only_its_state():
    trace, pool, voice = grading.jev_requests(CLAIM, CITED, POOL)

    assert trace.name == "trace" and trace.state == {"claim": CLAIM, "evidence": CITED}
    assert set(trace.questions) == {"relation", "delivery_overclaim", "ownership_overclaim", "adoption_overclaim"}
    assert pool.name == "pool" and pool.state == {"claim": CLAIM, "evidence": POOL}
    assert set(pool.questions) == {"unstated"}
    assert voice.name == "voice" and voice.state == {"claim": CLAIM}
    assert set(voice.questions) == set(grading.VOICE_QUESTIONS)


def test_uncited_variant_skips_the_trace_request():
    assert [r.name for r in grading.jev_requests(CLAIM, [], POOL)] == ["pool", "voice"]


def test_supported_specific_bullet_passes_every_check():
    grade = grading.grade_variant(CLAIM, CITED, "resume_bullet", _answers())

    assert grade["verdict"] == "traced"
    assert grade["fact_clean"] is True
    assert grade["overclaim_free"] is True
    assert grade["cite_ok"] is True
    assert grade["voice"] == 1.0
    assert grade["lint_clean"] is True
    assert grade["unsourced_numbers"] == []
    assert grade["probabilities"]["relation_confidence"] == 0.9
    assert set(grade["probabilities"]) >= set(grading.VOICE_RULES_BY_KIND["resume_bullet"])


def test_number_absent_from_cited_lines_is_not_fact_clean_even_when_jev_says_supported():
    claim = "Shipped syseng-oncall v1.1.0, raising the eval pass rate from 62% to 97%."

    grade = grading.grade_variant(claim, CITED, "resume_bullet", _answers())

    assert grade["unsourced_numbers"] == ["97"]
    assert grade["fact_clean"] is False


def test_uncited_claim_stating_an_unstated_fact_adds_detail_and_cites_nothing():
    grade = grading.grade_variant(CLAIM, [], "resume_bullet", _answers(unstated=0.8, trace=False))

    assert grade["verdict"] == "adds_detail"
    assert grade["fact_clean"] is False
    assert grade["cite_ok"] is False
    assert grade["probabilities"]["relation"] is None
    assert grade["probabilities"]["delivery_overclaim"] is None


def test_any_overclaim_at_the_flag_fails_overclaim_free():
    grade = grading.grade_variant(CLAIM, CITED, "resume_bullet", _answers(ownership=grading.FLAG))

    assert grade["overclaim_free"] is False


def test_contradicting_citation_is_neither_fact_clean_nor_cited_right():
    grade = grading.grade_variant(CLAIM, CITED, "resume_bullet", _answers(relation="contradicts"))

    assert grade["verdict"] == "conflicts"
    assert grade["fact_clean"] is False
    assert grade["cite_ok"] is False


def test_cover_paragraph_is_held_to_its_own_voice_rules():
    answers = _answers()
    answers["voice"]["generic_ai_speak"] = {"noul": 0.9}
    answers["voice"]["weak_verb"] = {"noul": 0.9}

    grade = grading.grade_variant(
        "I built syseng-oncall v1.1.0 and raised its pass rate from 62% to 94%.",
        CITED,
        "cover_paragraph",
        answers,
    )

    assert grade["voice"] == pytest.approx(2 / 3)
    assert "weak_verb" not in grade["probabilities"]


def test_regex_style_rules_come_from_the_existing_linter():
    grade = grading.grade_variant(CLAIM + " It really mattered.", CITED, "resume_bullet", _answers())

    assert grade["lint_clean"] is False
    assert "filler:really" in grade["lint_findings"]


@pytest.mark.parametrize(
    "answers, message",
    [
        (_answers(relation="maybe"), "relation choice"),
        (_answers(confidence=1.5), "relation confidence"),
        (_answers(unstated="high"), "unstated"),
        (_answers(adoption=True), "adoption_overclaim"),
    ],
)
def test_malformed_jev_answer_raises_instead_of_scoring(answers, message):
    with pytest.raises(ValueError, match=message):
        grading.grade_variant(CLAIM, CITED, "resume_bullet", answers)


def test_case_grade_means_variant_checks_and_requires_the_requested_count():
    passing = grading.grade_variant(CLAIM, CITED, "resume_bullet", _answers())
    failing = grading.grade_variant(CLAIM, [], "resume_bullet", _answers(unstated=0.9, trace=False))

    grade = grading.grade_case([passing, failing], n_expected=2)

    assert grade["fact_clean"] == 0.5
    assert grade["cite_ok"] == 0.5
    assert grade["format_ok"] == 1.0
    assert grading.grade_case([passing], n_expected=4)["format_ok"] == 0.0


def test_case_with_no_variants_scores_zero_on_every_metric():
    grade = grading.grade_case([], n_expected=4)

    assert set(grade) == {m["id"] for m in grading.METRICS} - {"judge_win"}
    assert all(value == 0.0 for value in grade.values())


def test_metric_labels_fit_the_report_legend():
    assert all(len(metric["label"]) <= 14 for metric in grading.METRICS)
    assert grading.METRICS[0]["id"] == "fact_clean"


def test_judge_prompt_carries_both_sets_and_marks_an_empty_one():
    prompt = grading.judge_prompt("resume_bullet", "Lead with recovery.", "JD", "GUIDE", ["a1", "a2"], [])

    assert "<set_a>\nDraft 1:\na1\n\nDraft 2:\na2\n</set_a>" in prompt
    assert "<set_b>\n(no drafts)\n</set_b>" in prompt
    assert '<unit kind="resume_bullet">' in prompt and "GUIDE" in prompt and "JD" in prompt


def test_candidate_side_is_deterministic_and_lands_on_both_sides():
    sides = {grading.candidate_is_a(f"case{n}", 0, "v1") for n in range(20)}

    assert sides == {True, False}
    assert grading.candidate_is_a("case1", 0, "v1") == grading.candidate_is_a("case1", 0, "v1")


@pytest.mark.parametrize(
    "winner, candidate_on_a, expected",
    [("A", True, 1.0), ("B", True, 0.0), ("B", False, 1.0), ("A", False, 0.0), ("tie", True, 0.5), ("both_bad", False, 0.5)],
)
def test_judge_win_scores_the_candidate_not_the_side(winner, candidate_on_a, expected):
    assert grading.judge_win(winner, candidate_on_a) == expected


class _UnknownBlock:
    pass


def test_transcript_becomes_report_turns_with_subagent_turns_labelled():
    messages = [
        SystemMessage(subtype="init", data={}),
        AssistantMessage(
            content=[
                ThinkingBlock(thinking="dispatch it", signature="s"),
                ToolUseBlock(id="t1", name="Agent", input={"prompt": "go"}),
            ],
            model="claude-opus-5-5",
        ),
        AssistantMessage(content=[TextBlock(text="## Unit: x")], model="claude-opus-5-5", parent_tool_use_id="t1"),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content=[{"type": "text", "text": "done"}, {"type": "image"}])]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t2", content="plain"), ToolResultBlock(tool_use_id="t3")]),
        UserMessage(content="a string turn"),
        AssistantMessage(content=[_UnknownBlock()], model="claude-opus-5-5"),
    ]

    trace = grading.transcript_to_trace("PROMPT", messages)

    assert trace[0] == {"role": "user", "content": "PROMPT"}
    assert trace[1] == {"role": "assistant", "content": "", "thinking": "dispatch it"}
    assert trace[2] == {"role": "tool_call", "name": "Agent", "content": '{\n  "prompt": "go"\n}'}
    assert trace[3] == {"role": "assistant", "content": "## Unit: x", "name": "subagent:assistant"}
    assert trace[4]["role"] == "tool_result" and trace[4]["content"].startswith("done\n{")
    assert trace[5] == {"role": "tool_result", "content": "plain"}
    assert trace[6] == {"role": "tool_result", "content": ""}
    assert trace[7] == {"role": "user", "content": "a string turn"}
    assert trace[8] == {"role": "assistant", "content": "[_UnknownBlock]"}


def _result(model_usage):
    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
        session_id="s", model_usage=model_usage,
    )


def test_served_models_unions_assistant_turns_and_result_usage():
    messages = [
        AssistantMessage(content=[], model="claude-sonnet-4-6"),
        _result({"claude-haiku-4-5": {}}),
        _result(None),
    ]

    assert grading.served_models(messages) == {"claude-sonnet-4-6", "claude-haiku-4-5"}

# ABOUTME: Offline tests for the variant-generation eval runner: workspaces, resume, failure classes, judging.
# ABOUTME: A fake port, Jev asker, and judge stand in for the paid calls; sources come from the fixture workspace.

import asyncio
import json
import shutil
import urllib.error
from pathlib import Path

import pytest
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    UserMessage,
)

from app.domain import Evidence, Variant
from app.metrics import CallMetrics
from evals import grading
from evals import run_variant_eval as runner

FIXTURE = Path(__file__).parent / "fixtures" / "workspace"
APP = "globex-staff-platform"
MODEL = "claude-sonnet-4-6"
CITATION = "master-resume.md L18"
SUPPORTED = "Owned the billing on-call rotation; cut paging volume 60% by adding idempotency keys."
INTERRUPT = "[Request interrupted by user for tool use]"


def _case(case_id=f"{APP}/resume.bullet_1", kind="resume_bullet"):
    return runner.Case(
        id=case_id, app=APP, unit_id=case_id.split("/")[1], kind=kind,
        description="Surface the on-call work.", source="real", difficulty="real",
    )


@pytest.fixture
def sources(tmp_path):
    apps = tmp_path / "src" / "applications" / APP
    apps.mkdir(parents=True)
    for name in ("jd.txt", "evidence.md"):
        shutil.copyfile(FIXTURE / "applications" / APP / name, apps / name)
    (apps / "outline.json").write_text("{}")
    (apps / "variants.md").write_text("past picks the agent must never see")
    return runner.Sources(
        grimoire=FIXTURE / "grimoire.md",
        master_resume=FIXTURE / "master-resume.md",
        applications=tmp_path / "src" / "applications",
    )


async def _ask(state, questions):
    answers = {}
    for question_id, question in questions.items():
        if question["type"] == "choice":
            answers[question_id] = {"choice": "supports", "confidence": 0.9}
        else:
            answers[question_id] = {"noul": 0.1}
    return answers


async def _judge_says_a(system, prompt):
    return {"winner": "A", "reasoning": "A is sharper.", "model": "claude-opus-5-5",
            "usage": {"input_tokens": 10, "output_tokens": 5}, "cost_usd": 0.01}


def _arm(tmp_path, sources, variant="baseline", ask=_ask, judge=_judge_says_a, timeout_s=5.0):
    return runner.make_arm(variant, MODEL, tmp_path / "flow", sources, [_case()], timeout_s, ask, judge)


class FakePort:
    """Stands in for SdkGenerationPort: canned variants, transcript, and call metrics."""

    instances: list["FakePort"] = []

    def __init__(self, workspace, texts=(SUPPORTED,) * 4, model=MODEL, stop_reason="end_turn",
                 error=None, delay=0.0, interrupted=False, fail_on_call=None):
        self.workspace = workspace
        self.texts = texts
        self.model = model
        self.stop_reason = stop_reason
        self.error = error
        self.delay = delay
        self.interrupted = interrupted
        self.fail_on_call = fail_on_call
        self.calls = 0
        self.closed = False
        self.session_cost = 0.0
        self.last_transcript = []
        self.last_call = None
        FakePort.instances.append(self)

    async def variants(self, slug, unit, n):
        await asyncio.sleep(self.delay)
        self.calls += 1
        if self.error or self.calls == self.fail_on_call:
            raise self.error or RuntimeError("cli died mid-session")
        dispatch = [UserMessage(content=[ToolResultBlock(tool_use_id="t1", content=INTERRUPT)])] if self.interrupted else []
        self.last_transcript = [
            *dispatch,
            AssistantMessage(content=[TextBlock(text="## Unit")], model=self.model),
            ResultMessage(subtype="success", duration_ms=1500, duration_api_ms=1, is_error=False,
                          num_turns=3, session_id="s", stop_reason=self.stop_reason),
        ]
        # The SDK reports total_cost_usd cumulatively over the client session.
        self.session_cost += 0.02
        self.last_call = CallMetrics(cost_usd=self.session_cost, input_tokens=100, output_tokens=50,
                                     cache_read_tokens=80, cache_creation_tokens=20,
                                     duration_ms=1500, num_turns=3)
        return [
            Variant(id=f"{unit.unit_id}#{n}", text=text,
                    evidence_items=(Evidence(id=CITATION, text=CITATION, source=CITATION, grounded=False),))
            for n, text in enumerate(self.texts, 1)
        ]

    async def aclose(self):
        self.closed = True


def _write_cases(flow):
    flow.mkdir(parents=True, exist_ok=True)
    real = {"id": f"{APP}/a", "app": APP, "unit_id": "a", "kind": "resume_bullet", "description": "d", "source": "real"}
    synthetic = {**real, "id": f"{APP}/b", "unit_id": "b", "source": "synthetic", "difficulty": "trap"}
    (flow / "cases.jsonl").write_text(json.dumps(real) + "\n")
    (flow / "synthetic_cases.jsonl").write_text(json.dumps(synthetic) + "\n")


def test_cases_load_from_both_files_and_real_cases_get_the_real_difficulty(tmp_path):
    _write_cases(tmp_path)

    cases = runner.load_cases(tmp_path)

    assert [(c.id, c.difficulty) for c in cases] == [(f"{APP}/a", "real"), (f"{APP}/b", "trap")]
    assert cases[1].tags == ["resume_bullet", "trap", "synthetic", APP]
    assert cases[0].unit.unit_id == "a"


def test_sources_come_from_the_flow_config(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"grimoire": "/g", "master_resume": "/m", "applications": "/a"}))

    assert runner.load_sources(tmp_path) == runner.Sources(Path("/g"), Path("/m"), Path("/a"))


def test_workspace_holds_only_generation_inputs_and_is_rebuilt_fresh(tmp_path, sources):
    dest = tmp_path / "ws"
    (dest / "stale").mkdir(parents=True)

    runner.build_workspace(sources, APP, dest)

    assert sorted(p.name for p in (dest / "applications" / APP).iterdir()) == ["evidence.md", "jd.txt", "outline.json"]
    assert (dest / "grimoire.md").exists() and (dest / "master-resume.md").exists()
    assert not (dest / "stale").exists()


def test_resume_skips_scored_rows_and_model_failures_but_retries_harness_failures(tmp_path):
    assert runner.done_keys(tmp_path) == set()

    runner.append_jsonl(tmp_path / "results.jsonl", {"prompt_id": "x", "rep": 1})
    runner.append_jsonl(tmp_path / "errors.jsonl", {"prompt_id": "y", "rep": 0, "failure_class": "unparseable_output"})
    runner.append_jsonl(tmp_path / "errors.jsonl", {"prompt_id": "z", "rep": 0, "failure_class": "subagent_interrupted"})

    assert runner.done_keys(tmp_path) == {("x", 1), ("y", 0)}
    assert runner.trace_name("app/unit.id", 2) == "app__unit.id_rep2.json"


def test_harness_gate_refuses_until_approved_and_again_after_a_change(tmp_path):
    sha = runner.harness_sha()
    assert sha == runner.harness_sha()

    with pytest.raises(runner.HarnessNotApproved, match="--approve-harness"):
        runner.check_harness(tmp_path, sha)
    runner.approve_harness(tmp_path, sha)
    runner.check_harness(tmp_path, sha)
    with pytest.raises(runner.HarnessNotApproved):
        runner.check_harness(tmp_path, "different")


def _http_error(code):
    return urllib.error.HTTPError("https://jev", code, "status", {}, None)


@pytest.mark.parametrize(
    "error, retryable",
    [(_http_error(429), True), (_http_error(529), True), (_http_error(400), False),
     (urllib.error.URLError("down"), True), (TimeoutError(), True), (ValueError(), False)],
)
def test_only_transient_errors_are_retried(error, retryable):
    assert runner.is_retryable(error) is retryable


def test_backoff_retries_transient_errors_with_growing_jittered_sleeps():
    sleeps, calls = [], []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise _http_error(529)
        return "ok"

    async def sleep(seconds):
        sleeps.append(seconds)

    result = asyncio.run(runner.with_backoff(flaky, sleep=sleep, jitter=lambda: 0.5))

    assert result == ("ok", 2)
    assert sleeps == [1.5, 3.0]


def test_backoff_raises_permanent_errors_at_once_and_transient_ones_when_exhausted():
    async def sleep(seconds):
        pass

    async def bad_request():
        raise _http_error(400)

    async def overloaded():
        raise _http_error(529)

    with pytest.raises(urllib.error.HTTPError):
        asyncio.run(runner.with_backoff(bad_request, sleep=sleep))
    with pytest.raises(urllib.error.HTTPError):
        asyncio.run(runner.with_backoff(overloaded, attempts=2, sleep=sleep))


def test_variants_are_graded_from_their_resolved_citations(tmp_path, sources):
    arm = _arm(tmp_path, sources)
    lines = arm.lines_by_app[APP]
    variants = [{"text": SUPPORTED, "citation": CITATION}, {"text": SUPPORTED, "citation": "nowhere"}]

    grades, retries = asyncio.run(runner.grade_variants(variants, "resume_bullet", lines, _ask))

    assert retries == 0
    assert grades[0]["cited"] == [lines["master-resume.md L18"]]
    assert grades[0]["cite_ok"] is True
    assert grades[1]["cited"] == [] and grades[1]["cite_ok"] is False


def test_jev_failure_and_malformed_answers_are_grader_errors(tmp_path, sources):
    lines = _arm(tmp_path, sources).lines_by_app[APP]
    variants = [{"text": SUPPORTED, "citation": CITATION}]

    async def broken(state, questions):
        raise _http_error(401)

    async def malformed(state, questions):
        return {question_id: {"noul": 7} for question_id in questions}

    for ask in (broken, malformed):
        with pytest.raises(runner.CaseFailure) as failure:
            asyncio.run(runner.grade_variants(variants, "resume_bullet", lines, ask))
        assert failure.value.failure_class == "grader_error"


def test_served_model_must_match_on_every_assistant_turn():
    turns = [AssistantMessage(content=[], model="claude-sonnet-4-6"),
             AssistantMessage(content=[], model="claude-haiku-4-5")]

    with pytest.raises(runner.CaseFailure, match="served") as failure:
        runner.check_served_model(turns, MODEL)
    assert failure.value.failure_class == "served_model_mismatch"
    with pytest.raises(runner.CaseFailure):
        runner.check_served_model([], MODEL)
    assert runner.check_served_model(turns[:1], MODEL) == {MODEL}
    assert runner.result_message(turns) is None


def test_baseline_row_is_complete_neutral_on_the_judge_and_freezes_its_set(tmp_path, sources):
    arm = _arm(tmp_path, sources)

    row = asyncio.run(runner.run_case(arm, FakePort(None), _case(), rep=0))

    assert row["status"] == "ok" and row["stop_reason"] == "end_turn"
    assert row["grade"]["judge_win"] == 0.5
    assert row["grade"]["fact_clean"] == 1.0 and row["grade"]["format_ok"] == 1.0
    assert row["usage"] == {"input_tokens": 100, "output_tokens": 50,
                            "cache_read_input_tokens": 80, "cache_creation_input_tokens": 20}
    assert row["latency_s"] == 1.5 and row["model"] == MODEL
    assert row["meta"]["served_models"] == [MODEL]
    assert "judge_model" not in row
    ref = json.loads((arm.dir / "ref" / runner.trace_name(_case().id, 0)).read_text())
    assert ref == {"texts": [SUPPORTED] * 4}
    trace = json.loads((arm.dir / "traces" / runner.trace_name(_case().id, 0)).read_text())
    assert trace[0]["role"] == "user" and trace[-1]["content"] == "## Unit"


def test_clipped_generation_is_marked_truncated(tmp_path, sources):
    row = asyncio.run(runner.run_case(_arm(tmp_path, sources), FakePort(None, stop_reason="max_tokens"), _case(), 0))

    assert row["status"] == "truncated"


def _freeze_reference(tmp_path, sources, rep):
    baseline = _arm(tmp_path, sources)
    asyncio.run(runner.run_case(baseline, FakePort(None, texts=("baseline draft",) * 4), _case(), rep))


def test_candidate_is_judged_blind_against_the_frozen_baseline_set(tmp_path, sources):
    _freeze_reference(tmp_path, sources, rep=0)
    prompts = []

    async def judge(system, prompt):
        prompts.append(prompt)
        return await _judge_says_a(system, prompt)

    arm = _arm(tmp_path, sources, variant="v1", judge=judge)
    row = asyncio.run(runner.run_case(arm, FakePort(None), _case(), rep=0))

    on_a = grading.candidate_is_a(_case().id, 0, "v1")
    assert row["grade"]["judge_win"] == (1.0 if on_a else 0.0)
    assert row["judge_model"] == "claude-opus-5-5" and row["judge_usage"]["output_tokens"] == 5
    assert row["meta"]["judge_candidate_side"] == ("A" if on_a else "B")
    assert "baseline draft" in prompts[0] and SUPPORTED in prompts[0]
    assert "baseline" not in prompts[0].replace("baseline draft", "")
    assert not (arm.dir / "ref").exists()


def test_a_rep_without_its_own_reference_falls_back_to_rep_zero(tmp_path, sources):
    _freeze_reference(tmp_path, sources, rep=0)
    arm = _arm(tmp_path, sources, variant="v1")

    row = asyncio.run(runner.run_case(arm, FakePort(None), _case(), rep=2))

    assert row["grade"]["judge_win"] in (0.0, 1.0)


def test_missing_reference_and_judge_failure_are_recorded_failures(tmp_path, sources):
    async def judge_down(system, prompt):
        raise RuntimeError("no structured output")

    with pytest.raises(runner.CaseFailure) as missing:
        asyncio.run(runner.run_case(_arm(tmp_path, sources, variant="v1"), FakePort(None), _case(), 0))
    assert missing.value.failure_class == "missing_reference"

    _freeze_reference(tmp_path, sources, rep=0)
    with pytest.raises(runner.CaseFailure) as judged:
        asyncio.run(runner.run_case(_arm(tmp_path, sources, variant="v1", judge=judge_down), FakePort(None), _case(), 0))
    assert judged.value.failure_class == "grader_error"


def test_generation_with_no_parsable_variants_is_a_failure_not_a_zero_row(tmp_path, sources):
    arm = _arm(tmp_path, sources)

    with pytest.raises(runner.CaseFailure) as failure:
        asyncio.run(runner.run_case(arm, FakePort(None, texts=()), _case(), 0))

    assert failure.value.failure_class == "unparseable_output"
    assert failure.value.extra["usage"]["output_tokens"] == 50
    assert failure.value.extra["sdk_cost_usd"] == pytest.approx(0.02)
    assert (arm.flow / failure.value.extra["trace"]).exists()


def test_an_interrupted_dispatch_is_not_charged_to_the_model_as_bad_format(tmp_path, sources):
    with pytest.raises(runner.CaseFailure) as failure:
        asyncio.run(runner.run_case(_arm(tmp_path, sources), FakePort(None, texts=(), interrupted=True), _case(), 0))

    assert failure.value.failure_class == "subagent_interrupted"


def test_each_row_costs_its_own_call_although_the_sdk_reports_session_totals(tmp_path, sources):
    arm = _arm(tmp_path, sources)
    ports = iter([FakePort(None, fail_on_call=3), FakePort(None)])
    cases = [_case(f"{APP}/a"), _case(f"{APP}/b"), _case(f"{APP}/c"), _case(f"{APP}/d")]

    asyncio.run(runner.run_group(arm, lambda ws: next(ports), tmp_path, cases, 0))

    rows = [json.loads(line) for line in (arm.dir / "results.jsonl").read_text().splitlines()]
    assert [r["prompt_id"].split("/")[1] for r in rows] == ["a", "b", "d"]
    assert [r["meta"]["sdk_cost_usd"] for r in rows] == pytest.approx([0.02, 0.02, 0.02])
    assert [r["meta"]["sdk_cost_cumulative_usd"] for r in rows] == pytest.approx([0.02, 0.04, 0.02])


@pytest.mark.parametrize(
    "port_kwargs, failure_class",
    [({"delay": 1.0}, "timeout"), ({"error": RuntimeError("cli died")}, "harness_error"),
     ({"model": "claude-haiku-4-5"}, "served_model_mismatch")],
)
def test_generation_failures_carry_their_class(tmp_path, sources, port_kwargs, failure_class):
    arm = _arm(tmp_path, sources, timeout_s=0.01)

    with pytest.raises(runner.CaseFailure) as failure:
        asyncio.run(runner.run_case(arm, FakePort(None, **port_kwargs), _case(), 0))

    assert failure.value.failure_class == failure_class


def test_group_records_failures_in_the_sidecar_and_continues_on_a_fresh_port(tmp_path, sources):
    FakePort.instances = []
    arm = _arm(tmp_path, sources)
    ports = iter([FakePort(None, error=RuntimeError("boom")), FakePort(None)])

    asyncio.run(runner.run_group(arm, lambda ws: next(ports), tmp_path, [_case(f"{APP}/x"), _case(f"{APP}/y")], 0))

    errors = [json.loads(line) for line in (arm.dir / "errors.jsonl").read_text().splitlines()]
    assert [(e["prompt_id"], e["failure_class"]) for e in errors] == [(f"{APP}/x", "harness_error")]
    assert runner.done_keys(arm.dir) == {(f"{APP}/y", 0)}
    assert all(port.closed for port in FakePort.instances)


def test_arm_skips_written_cases_and_runs_the_rest_per_app_and_rep(tmp_path, sources):
    arm = _arm(tmp_path, sources)
    runner.append_jsonl(arm.dir / "results.jsonl", {"prompt_id": _case().id, "rep": 0})
    workspaces = []

    def make_port(ws):
        workspaces.append(ws.name)
        return FakePort(ws)

    asyncio.run(runner.run_arm(arm, sources, [_case()], reps=2, concurrency=2, make_port=make_port))

    assert runner.done_keys(arm.dir) == {(_case().id, 0), (_case().id, 1)}
    assert workspaces == [f"{APP}_rep1"]


def test_cli_parses_arm_options_and_selects_cases():
    args = runner.parse_args(["--variant", "v1", "--model", "claude-opus-5-5", "--reps", "3", "--cases", "a,b"])
    cases = [_case(f"{APP}/a"), _case(f"{APP}/b"), _case(f"{APP}/c")]

    assert (args.variant, args.model, args.reps, args.judge_model) == ("v1", "claude-opus-5-5", 3, "claude-opus-5-5")
    assert runner.select_cases(cases, None) == cases
    assert [c.id for c in runner.select_cases(cases, f"{APP}/a, {APP}/c")] == [f"{APP}/a", f"{APP}/c"]
    with pytest.raises(SystemExit, match="unknown"):
        runner.select_cases(cases, "nope")

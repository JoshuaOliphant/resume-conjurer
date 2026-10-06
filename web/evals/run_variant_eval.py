# ABOUTME: Runner for the variant-generation eval: real SdkGenerationPort per arm, Jev and Opus graders.
# ABOUTME: Writes results.jsonl, traces/, errors.jsonl, ref/ under .claude/hillclimb/variant-generation/<variant>/.
"""Run the variant-generation eval for one arm (a model) as one report variant.

    cd web
    uv run python -m evals.run_variant_eval --approve-harness        # yours to run, after review
    uv run python -m evals.run_variant_eval --variant baseline --model claude-sonnet-4-6 --reps 3
    uv run python -m evals.run_variant_eval --variant v1 --model claude-sonnet-5-5 --reps 3

Cases are frozen outline units (``cases.jsonl`` + ``synthetic_cases.jsonl`` in the flow dir).
``config.json`` in the flow dir names the source grimoire, master resume, and applications dir;
each (app, rep) gets a scratch workspace holding only those inputs, so no past variants or final
documents are readable by the agent. Units of one (app, rep) run in order on one port, as in
production, so the variant client's prompt cache stays warm.

Every attempt that produced no scorable output goes to ``errors.jsonl`` with a failure class and
never occupies a ``(case, rep)`` slot in ``results.jsonl``; a rerun picks up exactly those.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import shutil
import sys
import urllib.error
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import AssistantMessage, ResultMessage

from app.adapters.generation_sdk import SdkGenerationPort, build_variant_prompt
from app.adapters.scripts_path import ensure_scripts_on_path
from app.domain import OutlineUnit, UnitKind
from evals import grading

ensure_scripts_on_path()

import citations  # noqa: E402
import verify  # noqa: E402

WEB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WEB_ROOT.parent
FLOW = REPO_ROOT / ".claude" / "hillclimb" / "variant-generation"
CASE_FILES = ("cases.jsonl", "synthetic_cases.jsonl")
N_VARIANTS = 4
JUDGE_MODEL = "claude-opus-5-5"
HARNESS_FILES = (
    WEB_ROOT / "evals" / "run_variant_eval.py",
    WEB_ROOT / "evals" / "grading.py",
    WEB_ROOT / "app" / "adapters" / "generation_sdk.py",
    REPO_ROOT / "plugins" / "conjurer" / "agents" / "variant-generator.md",
    REPO_ROOT / "plugins" / "conjurer" / "skills" / "conjurer" / "SKILL.md",
)
RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}
INTERRUPTED = "[Request interrupted"
MODEL_FAILURES = {"unparseable_output"}

Ask = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]
Judge = Callable[[str, str], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Case:
    id: str
    app: str
    unit_id: str
    kind: UnitKind
    description: str
    source: str
    difficulty: str

    @property
    def unit(self) -> OutlineUnit:
        return OutlineUnit(unit_id=self.unit_id, kind=self.kind, description=self.description)

    @property
    def tags(self) -> list[str]:
        return [self.kind, self.difficulty, self.source, self.app]


@dataclass(frozen=True)
class Sources:
    grimoire: Path
    master_resume: Path
    applications: Path


class CaseFailure(Exception):
    """An attempt that produced no scorable output, with the class it is recorded under."""

    def __init__(self, failure_class: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.failure_class = failure_class
        self.extra = extra


class HarnessNotApproved(Exception):
    """The harness files changed since the user last approved them."""


def load_cases(flow: Path) -> list[Case]:
    cases = []
    for name in CASE_FILES:
        for line in (flow / name).read_text().splitlines():
            row = json.loads(line)
            cases.append(
                Case(
                    id=row["id"], app=row["app"], unit_id=row["unit_id"], kind=row["kind"],
                    description=row["description"], source=row["source"],
                    difficulty=row.get("difficulty", "real"),
                )
            )
    return cases


def load_sources(flow: Path) -> Sources:
    config = json.loads((flow / "config.json").read_text())
    return Sources(
        grimoire=Path(config["grimoire"]),
        master_resume=Path(config["master_resume"]),
        applications=Path(config["applications"]),
    )


def build_workspace(sources: Sources, app: str, dest: Path) -> Path:
    """A fresh workspace with only the generation inputs for one application."""
    if dest.exists():
        shutil.rmtree(dest)
    app_dir = dest / "applications" / app
    app_dir.mkdir(parents=True)
    shutil.copyfile(sources.grimoire, dest / "grimoire.md")
    shutil.copyfile(sources.master_resume, dest / "master-resume.md")
    for name in ("jd.txt", "evidence.md", "outline.json"):
        shutil.copyfile(sources.applications / app / name, app_dir / name)
    return dest


def trace_name(case_id: str, rep: int) -> str:
    return f"{case_id.replace('/', '__')}_rep{rep}.json"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def done_keys(variant_dir: Path) -> set[tuple[str, int]]:
    """Attempts not to run again: scored rows, and failures that are the model's own doing."""
    scored = {(row["prompt_id"], row["rep"]) for row in _jsonl(variant_dir / "results.jsonl")}
    final = {
        (error["prompt_id"], error["rep"])
        for error in _jsonl(variant_dir / "errors.jsonl")
        if error["failure_class"] in MODEL_FAILURES
    }
    return scored | final


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(row) + "\n")


def harness_sha(paths: tuple[Path, ...] = HARNESS_FILES) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(REPO_ROOT)).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def approve_harness(flow: Path, sha: str) -> None:
    (flow / ".harness_approved").write_text(sha + "\n")


def check_harness(flow: Path, sha: str) -> None:
    approved = flow / ".harness_approved"
    if not approved.exists() or approved.read_text().strip() != sha:
        raise HarnessNotApproved(
            "Harness files changed since the last approval. Review the diff, then run:\n"
            "  uv run python -m evals.run_variant_eval --approve-harness"
        )


def is_retryable(error: BaseException) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code in RETRYABLE_STATUS
    return isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError))


async def with_backoff(
    call: Callable[[], Awaitable[Any]],
    attempts: int = 5,
    base_s: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    jitter: Callable[[], float] = random.random,
) -> tuple[Any, int]:
    """Run ``call``, retrying transient errors with jittered exponential backoff.

    Returns the result and the number of retries it took; the last error propagates.
    """
    for attempt in range(attempts - 1):
        try:
            return await call(), attempt
        except Exception as error:
            if not is_retryable(error):
                raise
            await sleep(base_s * 2**attempt * (1 + jitter()))
    return await call(), attempts - 1


def cited_lines(citation: str, lines: dict[str, str]) -> list[str]:
    return [lines[line.id] for line in citations.resolve_citation(citation, lines) if line.grounded]


async def grade_variants(
    variants: list[dict[str, str]], kind: str, lines: dict[str, str], ask: Ask
) -> tuple[list[dict[str, Any]], int]:
    """Grade every variant of a case; all Jev requests run concurrently. Returns grades and retries."""
    pool = list(lines.values())
    plans = []
    for variant in variants:
        cited = cited_lines(variant["citation"], lines)
        plans.append((variant, cited, grading.jev_requests(variant["text"], cited, pool)))

    async def answer(request: grading.JevRequest) -> tuple[dict[str, Any], int]:
        return await with_backoff(lambda: ask(request.state, request.questions))

    flat = [request for _, _, requests in plans for request in requests]
    try:
        replies = await asyncio.gather(*(answer(request) for request in flat))
    except Exception as error:
        raise CaseFailure("grader_error", f"Jev: {error!r}") from error
    retries = sum(r for _, r in replies)
    answers_iter = iter(a for a, _ in replies)
    grades = []
    for variant, cited, requests in plans:
        answers = {request.name: next(answers_iter) for request in requests}
        try:
            grade = grading.grade_variant(variant["text"], cited, kind, answers)
        except (ValueError, KeyError, TypeError) as error:
            raise CaseFailure("grader_error", f"Jev answer: {error!r}") from error
        grades.append({"text": variant["text"], "citation": variant["citation"], "cited": cited, **grade})
    return grades, retries


def usage_of(port: Any) -> dict[str, int]:
    call = port.last_call
    return {
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "cache_read_input_tokens": call.cache_read_tokens,
        "cache_creation_input_tokens": call.cache_creation_tokens,
    }


def result_message(transcript: list[Any]) -> Any:
    results = [m for m in transcript if type(m).__name__ == "ResultMessage"]
    return results[-1] if results else None


def check_served_model(transcript: list[Any], model: str) -> set[str]:
    """Every assistant turn, the subagent's included, must come from the requested model."""
    served = {m.model for m in transcript if type(m).__name__ == "AssistantMessage"}
    if not served or any(not name.startswith(model) for name in served):
        raise CaseFailure("served_model_mismatch", f"asked for {model}, served {sorted(served)}")
    return grading.served_models(transcript)


@dataclass
class Arm:
    variant: str
    model: str
    flow: Path
    timeout_s: float
    ask: Ask
    judge: Judge
    jd_by_app: dict[str, str]
    grimoire: str
    lines_by_app: dict[str, dict[str, str]]

    @property
    def dir(self) -> Path:
        return self.flow / self.variant


async def judge_case(arm: Arm, case: Case, rep: int, texts: list[str]) -> dict[str, Any]:
    """Pairwise judge against the frozen baseline set; the baseline itself is the neutral 0.5."""
    if arm.variant == "baseline":
        return {"judge_win": 0.5}
    refs = arm.flow / "baseline" / "ref"
    ref_path = refs / trace_name(case.id, rep)
    if not ref_path.exists():
        others = sorted(refs.glob(trace_name(case.id, 0).replace("_rep0.json", "_rep*.json")))
        if not others:
            raise CaseFailure("missing_reference", f"no frozen baseline set for {case.id}")
        ref_path = others[0]
    reference = json.loads(ref_path.read_text())["texts"]
    on_a = grading.candidate_is_a(case.id, rep, arm.variant)
    set_a, set_b = (texts, reference) if on_a else (reference, texts)
    prompt = grading.judge_prompt(
        case.kind, case.description, arm.jd_by_app[case.app], arm.grimoire, set_a, set_b
    )
    try:
        verdict, retries = await with_backoff(lambda: arm.judge(grading.JUDGE_SYSTEM, prompt))
    except Exception as error:
        raise CaseFailure("grader_error", f"judge: {error!r}") from error
    return {
        "judge_win": grading.judge_win(verdict["winner"], on_a),
        "judge_winner": verdict["winner"],
        "judge_candidate_side": "A" if on_a else "B",
        "judge_reasoning": verdict["reasoning"],
        "judge_model": verdict["model"],
        "judge_usage": verdict["usage"],
        "judge_cost_usd": verdict["cost_usd"],
        "judge_retries": retries,
    }


def missing_block_class(trace: list[dict[str, Any]]) -> str:
    """Why a generation produced no variant block: an interrupted dispatch, or the model's format."""
    interrupted = any(
        turn["role"] == "tool_result" and turn["content"].startswith(INTERRUPTED) for turn in trace
    )
    return "subagent_interrupted" if interrupted else "unparseable_output"


async def run_case(arm: Arm, port: Any, case: Case, rep: int, prior_cost: float = 0.0) -> dict[str, Any]:
    """Generate and grade one case. ``prior_cost`` is the port's cumulative SDK cost before this call."""
    prompt = build_variant_prompt(case.app, case.unit, N_VARIANTS)
    try:
        variants = await asyncio.wait_for(port.variants(case.app, case.unit, N_VARIANTS), arm.timeout_s)
    except TimeoutError as error:
        raise CaseFailure("timeout", f"generation exceeded {arm.timeout_s}s") from error
    except Exception as error:
        raise CaseFailure("harness_error", f"generation: {error!r}") from error

    spent = {
        "sdk_cost_usd": port.last_call.cost_usd - prior_cost,
        "sdk_cost_cumulative_usd": port.last_call.cost_usd,
        "usage": usage_of(port),
    }
    try:
        return await score_generation(arm, port, case, rep, prompt, variants, spent)
    except CaseFailure as failure:
        failure.extra.update(spent)
        raise


async def score_generation(
    arm: Arm, port: Any, case: Case, rep: int, prompt: str, variants: list[Any], spent: dict[str, Any]
) -> dict[str, Any]:
    transcript = port.last_transcript
    served = check_served_model(transcript, arm.model)
    result = result_message(transcript)
    trace = grading.transcript_to_trace(prompt, transcript)
    trace_path = arm.dir / "traces" / trace_name(case.id, rep)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps(trace, indent=2))
    if not variants:
        raise CaseFailure(
            missing_block_class(trace), "no variant block parsed from the final message",
            trace=str(trace_path.relative_to(arm.flow)),
        )
    texts = [v.text for v in variants]
    parsed = [{"text": v.text, "citation": v.evidence_items[0].id} for v in variants]
    grades, jev_retries = await grade_variants(parsed, case.kind, arm.lines_by_app[case.app], arm.ask)
    judged = await judge_case(arm, case, rep, texts)

    stop_reason = getattr(result, "stop_reason", None)
    if arm.variant == "baseline":
        ref_path = arm.dir / "ref" / trace_name(case.id, rep)
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        ref_path.write_text(json.dumps({"texts": texts}, indent=2))

    judge_fields = {k: judged[k] for k in ("judge_model", "judge_usage") if k in judged}
    return {
        "prompt_id": case.id,
        "rep": rep,
        "prompt": f"{case.description}\n\n---\n{prompt}",
        "tags": case.tags,
        "status": "truncated" if stop_reason == "max_tokens" else "ok",
        "stop_reason": stop_reason,
        "grade": {**grading.grade_case(grades, N_VARIANTS), "judge_win": judged["judge_win"]},
        "model": arm.model,
        "usage": spent["usage"],
        "latency_s": port.last_call.duration_ms / 1000,
        "turns": port.last_call.num_turns,
        **judge_fields,
        "meta": {
            "sdk_cost_usd": spent["sdk_cost_usd"],
            "sdk_cost_cumulative_usd": spent["sdk_cost_cumulative_usd"],
            "served_models": sorted(served),
            "jev_retries": jev_retries,
            "variants": grades,
            **{k: v for k, v in judged.items() if k not in ("judge_win", "judge_model", "judge_usage")},
        },
    }


async def run_group(
    arm: Arm,
    make_port: Callable[[Path], Any],
    workspace: Path,
    cases: list[Case],
    rep: int,
) -> None:
    """Run one (app, rep)'s cases in order on one port; a failed attempt gets a fresh port.

    The SDK reports cost cumulatively per client session, so each row records the difference
    from the port's previous call.
    """
    port = make_port(workspace)
    prior_cost = 0.0
    try:
        for case in cases:
            try:
                row = await run_case(arm, port, case, rep, prior_cost)
            except CaseFailure as failure:
                append_jsonl(
                    arm.dir / "errors.jsonl",
                    {"prompt_id": case.id, "rep": rep, "failure_class": failure.failure_class,
                     "detail": str(failure), "model": arm.model, **failure.extra},
                )
                await port.aclose()
                port = make_port(workspace)
                prior_cost = 0.0
                continue
            prior_cost = row["meta"]["sdk_cost_cumulative_usd"]
            append_jsonl(arm.dir / "results.jsonl", row)
    finally:
        await port.aclose()


async def run_arm(
    arm: Arm,
    sources: Sources,
    cases: list[Case],
    reps: int,
    concurrency: int,
    make_port: Callable[[Path], Any],
) -> None:
    done = done_keys(arm.dir)
    groups: dict[tuple[str, int], list[Case]] = {}
    for rep in range(reps):
        for case in cases:
            if (case.id, rep) not in done:
                groups.setdefault((case.app, rep), []).append(case)
    gate = asyncio.Semaphore(concurrency)

    async def bounded(app: str, rep: int, group: list[Case]) -> None:
        async with gate:
            workspace = build_workspace(sources, app, arm.dir / "workspaces" / f"{app}_rep{rep}")
            await run_group(arm, make_port, workspace, group, rep)

    await asyncio.gather(*(bounded(app, rep, group) for (app, rep), group in groups.items()))


def make_arm(variant: str, model: str, flow: Path, sources: Sources, cases: list[Case],
             timeout_s: float, ask: Ask, judge: Judge) -> Arm:
    master = sources.master_resume.read_text()
    apps = sorted({case.app for case in cases})
    return Arm(
        variant=variant,
        model=model,
        flow=flow,
        timeout_s=timeout_s,
        ask=ask,
        judge=judge,
        jd_by_app={app: (sources.applications / app / "jd.txt").read_text() for app in apps},
        grimoire=sources.grimoire.read_text(),
        lines_by_app={
            app: citations.pool_lines(master, (sources.applications / app / "evidence.md").read_text())
            for app in apps
        },
    )


def jev_asker(api_key: str) -> Ask:  # pragma: no cover - live: calls the paid Jev API
    async def ask(state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(verify.ask_jev, state, questions, api_key, verify.JEV_URL, 60.0)

    return ask


def sdk_judge(model: str) -> Judge:  # pragma: no cover - live: calls Claude through the Agent SDK
    async def judge(system: str, prompt: str) -> dict[str, Any]:
        options = ClaudeAgentOptions(
            model=model,
            system_prompt=system,
            tools=[],
            setting_sources=[],
            # Without this the CLI loads every user-level MCP server's tool schemas, ~158k tokens.
            strict_mcp_config=True,
            output_format={"type": "json_schema", "schema": grading.JUDGE_SCHEMA},
        )
        result = None
        answering: set[str] = set()
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                answering.add(message.model)
            elif isinstance(message, ResultMessage):
                result = message
        if result is None or not isinstance(result.structured_output, dict):
            raise RuntimeError(f"judge returned no structured output: {result!r}")
        if not answering or any(not name.startswith(model) for name in answering):
            raise RuntimeError(f"judge asked for {model}, answered by {sorted(answering)}")
        return {
            **result.structured_output,
            "model": model,
            "usage": result.usage or {},
            "cost_usd": result.total_cost_usd,
            "model_usage": result.model_usage or {},
        }

    return judge


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variant", help="report variant dir: baseline, v1, v2, ...")
    parser.add_argument("--model", help="model under test for this arm")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--cases", help="comma-separated case ids (default: all)")
    parser.add_argument("--timeout-s", type=float, default=600.0)
    parser.add_argument("--concurrency", type=int, default=4, help="(app, rep) groups in flight")
    parser.add_argument("--judge-model", default=JUDGE_MODEL)
    parser.add_argument("--approve-harness", action="store_true", help="record the current harness sha and exit")
    return parser.parse_args(argv)


def select_cases(cases: list[Case], wanted: str | None) -> list[Case]:
    if not wanted:
        return cases
    ids = [part.strip() for part in wanted.split(",") if part.strip()]
    unknown = set(ids) - {case.id for case in cases}
    if unknown:
        raise SystemExit(f"unknown case ids: {sorted(unknown)}")
    return [case for case in cases if case.id in ids]


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - live entry point
    args = parse_args(argv)
    if args.approve_harness:
        approve_harness(FLOW, harness_sha())
        print(f"Approved harness {harness_sha()[:12]}")
        return
    if not (args.variant and args.model):
        raise SystemExit("--variant and --model are required")
    try:
        check_harness(FLOW, harness_sha())
    except HarnessNotApproved as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY is required: Jev grades every variant")
    sources = load_sources(FLOW)
    cases = select_cases(load_cases(FLOW), args.cases)
    arm = make_arm(args.variant, args.model, FLOW, sources, cases, args.timeout_s,
                   jev_asker(api_key), sdk_judge(args.judge_model))
    asyncio.run(run_arm(arm, sources, cases, args.reps, args.concurrency,
                        lambda ws: SdkGenerationPort(ws, model=args.model)))
    rows = [json.loads(line) for line in (arm.dir / "results.jsonl").read_text().splitlines()]
    errors = arm.dir / "errors.jsonl"
    n_errors = len(errors.read_text().splitlines()) if errors.exists() else 0
    print(f"{args.variant} ({args.model}): {len(rows)} rows, {n_errors} failed attempts -> {arm.dir}")


if __name__ == "__main__":
    main()

# ABOUTME: Fast mode's fit gate: scores a fit.json assessment of the JD's must-haves and returns pass or stop.
# ABOUTME: A met or partial requirement only counts when its citation names real evidence lines.
"""Implementation of `python3 fit.py <app_dir> <workspace>`.

Fast mode assesses the job description before any outline or variant work and writes
`applications/<slug>/fit.json`. This script is the only thing that turns that assessment into a
verdict, so the stop rule is fixed here rather than re-argued on every run:

    {"requirements": [
      {"requirement": "Hands-on production LLM agents", "core": true,
       "status": "met", "evidence": "master-resume.md L14; L15"},
      {"requirement": "JAX, PyTorch, or XLA/MLIR", "core": true, "status": "missing", "evidence": ""}
    ]}

`core` marks the work the role exists to do (the title's subject and the central
responsibilities); other must-haves are `core: false`. Preferred or nice-to-have items are left
out entirely. `status` is `met`, `partial`, or `missing`. A `met` or `partial` whose `evidence`
resolves to no line of master-resume.md or evidence.md counts as `missing`: no evidence, no fit.

Coverage is (met + half of partial) over all requirements. The run stops when at least half of
the core requirements are missing, or coverage is below 0.5. Exit codes: 0 pass, 1 stop (a
finding, like leaks.py), 2 a malformed fit.json.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import NamedTuple

from citations import pool_lines, resolve_citation

STATUSES = {"met": 1.0, "partial": 0.5, "missing": 0.0}
MIN_COVERAGE = 0.5
MIN_REQUIREMENTS = 3
MAX_REQUIREMENTS = 12


class Requirement(NamedTuple):
    text: str
    core: bool
    status: str
    ungrounded: bool


class Verdict(NamedTuple):
    passed: bool
    coverage: float
    core_missing: list[Requirement]
    other_missing: list[Requirement]
    ungrounded: list[Requirement]
    core_total: int


def parse_requirements(data: object, lines: dict[str, str]) -> list[Requirement]:
    """Validate fit.json's requirements, demoting met or partial with no grounded citation to missing."""
    raw = data.get("requirements") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not MIN_REQUIREMENTS <= len(raw) <= MAX_REQUIREMENTS:
        raise ValueError(f"fit.json needs a `requirements` list of {MIN_REQUIREMENTS} to {MAX_REQUIREMENTS} must-haves")
    requirements: list[Requirement] = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Requirement {i} is not an object")
        text, core, status = item.get("requirement"), item.get("core"), item.get("status")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Requirement {i} has no `requirement` text")
        if type(core) is not bool:
            raise ValueError(f"Requirement {i} needs `core` true or false")
        if status not in STATUSES:
            raise ValueError(f"Requirement {i} has status {status!r}; use met, partial, or missing")
        ungrounded = False
        if status != "missing":
            evidence = item.get("evidence")
            cited = resolve_citation(evidence, lines) if isinstance(evidence, str) and evidence.strip() else []
            if not any(line.grounded for line in cited):
                status, ungrounded = "missing", True
        requirements.append(Requirement(text.strip(), core, status, ungrounded))
    if not any(r.core for r in requirements):
        raise ValueError("fit.json marks no requirement as core")
    return requirements


def judge(requirements: list[Requirement]) -> Verdict:
    coverage = sum(STATUSES[r.status] for r in requirements) / len(requirements)
    core = [r for r in requirements if r.core]
    core_missing = [r for r in core if r.status == "missing"]
    other_missing = [r for r in requirements if not r.core and r.status == "missing"]
    passed = coverage >= MIN_COVERAGE and 2 * len(core_missing) < len(core)
    ungrounded = [r for r in requirements if r.ungrounded]
    return Verdict(passed, coverage, core_missing, other_missing, ungrounded, len(core))


def render(verdict: Verdict) -> str:
    word = "pass" if verdict.passed else "stop"
    out = [
        f"Fit: {word} (coverage {verdict.coverage:.2f}, "
        f"{len(verdict.core_missing)} of {verdict.core_total} core requirements missing)"
    ]
    out += [f"- core, missing: {r.text}" for r in verdict.core_missing]
    out += [f"- missing: {r.text}" for r in verdict.other_missing]
    out += [f"- no grounded evidence cited, counted missing: {r.text}" for r in verdict.ungrounded]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score fast mode's fit.json and print pass or stop.")
    parser.add_argument("app_dir", type=Path)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args(argv)

    evidence_path = args.app_dir / "evidence.md"
    lines = pool_lines(
        (args.workspace / "master-resume.md").read_text(),
        evidence_path.read_text() if evidence_path.exists() else "",
    )
    try:
        requirements = parse_requirements(json.loads((args.app_dir / "fit.json").read_text()), lines)
    except (ValueError, json.JSONDecodeError) as error:
        print(f"fit.json: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    verdict = judge(requirements)
    print(render(verdict))
    if not verdict.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

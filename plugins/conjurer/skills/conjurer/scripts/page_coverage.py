# ABOUTME: Checks that each must-have the evidence supports also shows on the final resume page.
# ABOUTME: Reads fit.json's requirements and their cited lines, then looks for those lines in resume.md.
"""Implementation of `python3 page_coverage.py <app_dir> <workspace>`.

Per-criterion screeners (Ashby's AI-assisted review, Greenhouse Talent Matching) judge each
requirement against the resume's own text: evidence that exists in the master resume but was
left off the page reads as "does not meet". `fit.py` asks whether the evidence covers the
job's must-haves; this asks whether the stitched `resume.md` still shows that evidence.

A `met` or `partial` requirement in `fit.json` is **shown** when the page holds one of its
grounded cited lines: a master-resume line kept word for word, or a picked variant in
`variants.md` that is on the page and cites that line. When the only lines citing its evidence
are resume picks that were reworded after stitching, the page can't be traced word for word,
so the requirement is **reworded** and left for a person to check. It is **not shown**
otherwise. A `missing` requirement is listed for context; no wording fixes it. The check never
adds or rewords a claim. Cover-letter picks don't count: screeners score the resume.

Exit codes: 0 when every supported requirement is shown, 1 when one is not, 2 when fit.json or
resume.md is absent or malformed.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import NamedTuple

from citations import pool_lines, resolve_citation
from fit import parse_requirements
from parse_check import normalize
from stitch import parse_variants_md

RESUME_PREFIX = "resume."


class Coverage(NamedTuple):
    requirement: str
    status: str  # shown | reworded | not_shown | missing
    evidence: tuple[str, ...]


def _strip_bullet(line: str) -> str:
    stripped = line.strip()
    return stripped[2:] if stripped[:2] in ("- ", "* ") else stripped


def traced_lines(page: str, lines: dict[str, str], variants_md: str | None) -> tuple[set[str], set[str]]:
    """Pool keys the page carries, and keys cited only by resume picks reworded after stitching.

    A key is carried when its line is on the page word for word, or when a picked resume variant
    that cites it is.
    """
    flat = normalize(page)
    shown = {key for key, text in lines.items() if (words := normalize(_strip_bullet(text))) and words in flat}
    reworded: set[str] = set()
    for unit in parse_variants_md(variants_md or ""):
        pick = unit.picked
        if pick is None or not unit.unit_id.startswith(RESUME_PREFIX):
            continue
        cited = {line.id for line in resolve_citation(pick.citation, lines) if line.grounded}
        if normalize(pick.content) in flat:
            shown |= cited
        else:
            reworded |= cited
    return shown, reworded - shown


def assess(fit: object, page: str, lines: dict[str, str], variants_md: str | None) -> list[Coverage]:
    requirements = parse_requirements(fit, lines)
    shown, reworded = traced_lines(page, lines, variants_md)
    results: list[Coverage] = []
    raw = fit["requirements"] if isinstance(fit, dict) else []
    for item, requirement in zip(raw, requirements):
        if requirement.status == "missing":
            results.append(Coverage(requirement.text, "missing", ()))
            continue
        cited = tuple(line.id for line in resolve_citation(item["evidence"], lines) if line.grounded)
        status = "shown" if shown.intersection(cited) else "reworded" if reworded.intersection(cited) else "not_shown"
        results.append(Coverage(requirement.text, status, cited))
    return results


def render(results: list[Coverage]) -> str:
    supported = [r for r in results if r.status != "missing"]
    shown = sum(r.status == "shown" for r in supported)
    out = [f"Coverage: {shown} of {len(supported)} supported requirements show their evidence on the page"]
    out += [f"- not shown: {r.requirement} (evidence: {'; '.join(r.evidence)})" for r in results if r.status == "not_shown"]
    out += [
        f"- reworded after stitching, check by eye: {r.requirement} (evidence: {'; '.join(r.evidence)})"
        for r in results
        if r.status == "reworded"
    ]
    out += [f"- no evidence, not a wording fix: {r.requirement}" for r in results if r.status == "missing"]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Check that supported must-haves show on the stitched resume.")
    parser.add_argument("app_dir", type=Path)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args(argv)

    resume = args.app_dir / "resume.md"
    fit_path = args.app_dir / "fit.json"
    if not resume.exists() or not fit_path.exists():
        print("page_coverage: needs resume.md and fit.json in the application directory", file=sys.stderr)
        raise SystemExit(2)
    evidence = args.app_dir / "evidence.md"
    lines = pool_lines(
        (args.workspace / "master-resume.md").read_text(),
        evidence.read_text() if evidence.exists() else "",
    )
    variants = args.app_dir / "variants.md"
    try:
        results = assess(
            json.loads(fit_path.read_text()),
            resume.read_text(),
            lines,
            variants.read_text() if variants.exists() else None,
        )
    except (ValueError, json.JSONDecodeError) as error:
        print(f"fit.json: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    print(render(results))
    if any(r.status == "not_shown" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

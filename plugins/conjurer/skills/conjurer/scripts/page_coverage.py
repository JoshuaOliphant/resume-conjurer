# ABOUTME: Checks that each must-have the evidence supports also shows on the final resume page.
# ABOUTME: Reads fit.json's requirements and their cited lines, then looks for those lines in resume.md.
"""Implementation of `python3 page_coverage.py <app_dir> <workspace>`.

Per-criterion screeners (Ashby's AI-assisted review, Greenhouse Talent Matching) judge each
requirement against the resume's own text: evidence that exists in the master resume but was
left off the page reads as "does not meet". `fit.py` asks whether the evidence covers the
job's must-haves; this asks whether the stitched `resume.md` still shows that evidence.

A `met` or `partial` requirement in `fit.json` is **shown** when the page holds one of its
grounded cited lines: a master-resume line, or a picked variant in `variants.md` that cites
that line, whose every line is a whole page line word for word. A pick that is no longer on
the page word for word was either reworded or cut after stitching. It counts as reworded when a
page bullet is still close to it (difflib word-sequence ratio, or the share of the pick's words
on that bullet, at least 0.5, both over content words with filler like "the" left out); then the
requirement is **reworded** and left for a person to check. A cut pick traces nothing, and the requirement is **not shown**. A `missing` requirement is listed for context; no wording fixes it. The check never
adds or rewords a claim. Cover-letter picks don't count: screeners score the resume.

Exit codes: 0 when every supported requirement is shown, 1 when one is not, 2 when fit.json or
resume.md is absent or malformed.
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

from citations import pool_lines, resolve_citation
from fit import parse_requirements
from parse_check import normalize
from stitch import parse_variants_md

RESUME_PREFIX = "resume."
REWORDED_SIMILARITY = 0.5
# Filler words left out of similarity, so a short pick can't match an unrelated bullet on "the" and "of".
STOPWORDS = frozenset(
    "a an and as at by for from in into of on or our the their to via with".split()
)


class Coverage(NamedTuple):
    requirement: str
    status: str  # shown | reworded | not_shown | missing
    evidence: tuple[str, ...]


def _strip_bullet(line: str) -> str:
    stripped = line.strip()
    return stripped[2:] if stripped[:2] in ("- ", "* ") else stripped


def _words(text: str) -> list[str]:
    return [word for word in re.findall(r"\w+", text) if word not in STOPWORDS]


def similarity(pick: str, bullet: str) -> float:
    """How close a page bullet is to a pick: the larger of sequence ratio and word containment.

    Both measures count content words only (``STOPWORDS`` are dropped).
    """
    a, b = _words(pick), _words(bullet)
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    contained = len(set(a) & set(b)) / len(set(a)) if a else 0.0
    return max(ratio, contained)


def traced_lines(page: str, lines: dict[str, str], variants_md: str | None) -> tuple[set[str], set[str]]:
    """Pool keys the page carries, and keys cited only by resume picks reworded after stitching.

    A key is carried when its line is a whole page line word for word, or when every line of a
    picked resume variant that cites it is. A pick that is off the page counts as reworded only when
    some page bullet is still close to it; a cut pick traces nothing.
    """
    page_lines = {normalize(_strip_bullet(line)) for line in page.splitlines()} - {""}
    bullets = [normalize(_strip_bullet(line)) for line in page.splitlines() if line.lstrip()[:2] in ("- ", "* ")]
    shown = {key for key, text in lines.items() if normalize(_strip_bullet(text)) in page_lines}
    reworded: set[str] = set()
    for unit in parse_variants_md(variants_md or ""):
        pick = unit.picked
        if pick is None or not unit.unit_id.startswith(RESUME_PREFIX):
            continue
        cited = {line.id for line in resolve_citation(pick.citation, lines) if line.grounded}
        content = normalize(pick.content)
        pick_lines = {normalize(_strip_bullet(line)) for line in pick.content.splitlines()} - {""}
        if pick_lines <= page_lines:
            shown |= cited
        elif any(similarity(content, bullet) >= REWORDED_SIMILARITY for bullet in bullets):
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

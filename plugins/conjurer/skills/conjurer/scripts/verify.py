# ABOUTME: Checks each variant in variants.md against the evidence it cites, using TypeSafe Jev.
# ABOUTME: Writes applications/<slug>/support.json and prints one plain note per flagged variant.
"""Implementation of `python3 verify.py <app_dir> <workspace> [--picks]`.

Each variant gets two Jev readings: how its cited lines relate to it (a Choice), and whether it
states a fact the whole evidence pool does not (a Noul). `verdict_for` turns the readings into a
support verdict. The check is advisory: without TYPESAFE_API_KEY it is skipped, and a failed
request marks that variant `unchecked` instead of failing the run.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import citations
from stitch import Variant, parse_variants_md

JEV_MODEL = "jev-1.13.0"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
PARTLY_MIN_CONF = 0.8
UNSTATED_FLAG = 0.5
CONCURRENCY = 8

VERDICTS = ("traced", "untraced", "adds_detail", "conflicts", "wrong_trace", "not_covered", "unchecked")

NOTES: dict[str, str] = {
    "traced": "",
    "untraced": "",
    "adds_detail": "Adds detail your evidence doesn't state",
    "conflicts": "Conflicts with your evidence",
    "wrong_trace": "Your evidence supports this, but not the line it cites",
    "not_covered": "The cited line doesn't cover this",
    "unchecked": "Couldn't check this line",
}
NOTES_NAMING_NUMBERS = ("adds_detail", "conflicts")

SKIPPED_MESSAGE = "Claim check skipped: set TYPESAFE_API_KEY to check variants against your evidence."

RELATION_QUESTION = {
    "type": "choice",
    "instructions": (
        "How do the evidence lines relate to the claim? Every fact in the claim (numbers, counts,"
        " durations, team sizes, technologies, scope, outcomes) must be stated in the evidence for"
        " it to count as supported. Rewording and emphasis are fine; new facts are not."
    ),
    "criteria": {
        "supports": "Every fact in the claim is stated in the evidence or directly follows from it",
        "partly_supports": (
            "The evidence states the core of the claim, but the claim adds at least one specific"
            " fact the evidence does not state"
        ),
        "contradicts": (
            "The evidence states something incompatible with the claim, such as a different number"
            " or the opposite outcome"
        ),
        "says_nothing": "The evidence does not address what the claim asserts",
    },
}

UNSTATED_QUESTION = {
    "type": "noul",
    "instructions": (
        "Does the claim state any specific fact (a number, count, duration, team size, technology,"
        " scope, or outcome) that the evidence lines do not state?"
    ),
    "criteria": {
        "true": "At least one specific fact in the claim is missing from or different in the evidence",
        "false": (
            "Every specific fact in the claim appears in the evidence; only wording or emphasis differs"
        ),
    },
}

_NUMBER_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_WORD_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15",
    "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100",
}
_WORD_NUMBER_RE = re.compile(r"\b(" + "|".join(_WORD_NUMBERS) + r")\b", re.IGNORECASE)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reading:
    """Jev's answers for one variant; all None when the check could not run."""

    relation: str | None
    relation_confidence: float | None
    unstated: float | None


def verdict_for(reading: Reading, has_trace: bool) -> str:
    """Map one variant's readings to its support verdict."""
    if reading.unstated is None:
        return "unchecked"
    states_unstated_fact = reading.unstated >= UNSTATED_FLAG
    if not has_trace:
        return "adds_detail" if states_unstated_fact else "untraced"
    if reading.relation == "contradicts":
        return "conflicts"
    if reading.relation == "says_nothing":
        return "not_covered" if states_unstated_fact else "wrong_trace"
    confidently_partial = (
        reading.relation == "partly_supports"
        and (reading.relation_confidence or 0.0) >= PARTLY_MIN_CONF
    )
    if confidently_partial or states_unstated_fact:
        return "adds_detail"
    return "traced"


def _numbers_in(text: str) -> list[str]:
    found = [(m.start(), m.group().replace(",", "")) for m in _NUMBER_RE.finditer(text)]
    found += [(m.start(), _WORD_NUMBERS[m.group().lower()]) for m in _WORD_NUMBER_RE.finditer(text)]
    return list(dict.fromkeys(number for _, number in sorted(found)))


def unsourced_numbers(claim: str, cited_text: str) -> list[str]:
    """Numbers in the claim, digits or number words, that the cited text never states."""
    sourced = set(_numbers_in(cited_text))
    return [number for number in _numbers_in(claim) if number not in sourced]


def fingerprint(claim: str, cited: list[str]) -> str:
    """sha256 hex of the claim and its cited lines, joined by newlines."""
    return hashlib.sha256("\n".join([claim, *cited]).encode("utf-8")).hexdigest()


def note_for(verdict: str, numbers: list[str]) -> str:
    """The plain-language line shown for a verdict; empty when the verdict is not flagged."""
    note = NOTES[verdict]
    if numbers and verdict in NOTES_NAMING_NUMBERS:
        return f"{note}: {', '.join(numbers)}"
    return note


def ask_jev(state: dict, questions: dict, api_key: str, url: str = JEV_URL, timeout: float = 5.0) -> dict:
    """POST one System One request and return the response's `answers`."""
    request = urllib.request.Request(
        url,
        data=json.dumps({"model": JEV_MODEL, "state": state, "questions": questions}).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())["answers"]


def _read(claim: str, cited: list[str], pool: list[str], api_key: str, url: str) -> Reading:
    relation = confidence = None
    if cited:
        answer = ask_jev(
            {"claim": claim, "evidence": cited}, {"relation": RELATION_QUESTION}, api_key, url
        )["relation"]
        relation, confidence = answer["choice"], answer["confidence"]
    unstated = ask_jev(
        {"claim": claim, "evidence": pool}, {"unstated": UNSTATED_QUESTION}, api_key, url
    )["unstated"]["noul"]
    return Reading(relation=relation, relation_confidence=confidence, unstated=unstated)


def check_variant(claim: str, cited: list[str], pool: list[str], api_key: str, url: str = JEV_URL) -> dict:
    """One support.json row for a variant; `unchecked` when any request fails."""
    try:
        reading = _read(claim, cited, pool, api_key, url)
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.warning("Claim check failed for %r: %s", claim, error)
        reading = Reading(relation=None, relation_confidence=None, unstated=None)
    return {
        "verdict": verdict_for(reading, has_trace=bool(cited)),
        "relation": reading.relation,
        "relation_confidence": reading.relation_confidence,
        "unstated": reading.unstated,
        "unsourced_numbers": unsourced_numbers(claim, "\n".join(cited)),
        "fingerprint": fingerprint(claim, cited),
    }


def variant_targets(variants_md: str, picks_only: bool = False) -> list[tuple[str, Variant]]:
    """Each variant to check, keyed `<unit_id>#<n>`; only the picked ones with `picks_only`."""
    return [
        (f"{unit.unit_id}#{variant.n}", variant)
        for unit in parse_variants_md(variants_md)
        for variant in unit.variants
        if variant.picked or not picks_only
    ]


def _previous_rows(support_path: Path) -> dict:
    if not support_path.exists():
        return {}
    previous = json.loads(support_path.read_text())
    return previous["variants"] if previous["model"] == JEV_MODEL else {}


def verify_app_dir(
    app_dir: Path, workspace: Path, api_key: str, picks_only: bool = False, url: str = JEV_URL
) -> dict:
    """Check the app's variants (only the picked ones with `picks_only`) and write support.json.

    A picks-only run keeps the rows it did not recheck, so a full run's verdicts survive it.
    """
    lines = citations.pool_lines(
        (workspace / "master-resume.md").read_text(), (app_dir / "evidence.md").read_text()
    )
    pool = list(lines.values())
    targets = variant_targets((app_dir / "variants.md").read_text(), picks_only)

    def check(variant: Variant) -> dict:
        cited = [
            lines[line.id]
            for line in citations.resolve_citation(variant.citation, lines)
            if line.grounded
        ]
        return check_variant(variant.content, cited, pool, api_key, url)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        rows = list(executor.map(check, [variant for _, variant in targets]))

    support_path = app_dir / "support.json"
    variants = _previous_rows(support_path) if picks_only else {}
    variants.update({variant_id: row for (variant_id, _), row in zip(targets, rows)})
    document = {"model": JEV_MODEL, "variants": variants}
    support_path.write_text(json.dumps(document, indent=2) + "\n")
    return document


def main(argv: list[str] | None = None, url: str = JEV_URL) -> None:
    parser = argparse.ArgumentParser(description="Check variants against their cited evidence.")
    parser.add_argument("app_dir", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--picks", action="store_true", help="check only the picked variants")
    args = parser.parse_args(argv)

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        print(SKIPPED_MESSAGE)
        return

    document = verify_app_dir(args.app_dir, args.workspace, api_key, picks_only=args.picks, url=url)
    checked = [
        variant_id
        for variant_id, _ in variant_targets((args.app_dir / "variants.md").read_text(), args.picks)
    ]
    flagged = 0
    for variant_id in checked:
        row = document["variants"][variant_id]
        note = note_for(row["verdict"], row["unsourced_numbers"])
        if note:
            flagged += 1
            print(f"{variant_id}: {note}")
    print(f"Claim check: {flagged} of {len(checked)} variants flagged. Wrote {args.app_dir / 'support.json'}")


if __name__ == "__main__":
    main()

# ABOUTME: Writes an agent's (or anyone's) curation choices into variants.md as `- [x] Pick` lines.
# ABOUTME: Validates every choice against the parsed units so a bad pick fails here, not at stitch.
"""Implementation of `python3 picks.py <app_dir> <curation.json>`.

Fast mode's curator returns its choices as JSON; this script is the only thing that turns them
into checkboxes, so `variants.md` stays the single source of truth for picks. The JSON holds a
`picks` object mapping each unit_id to the number in its chosen `### Variant N` header:

    {"picks": {"cover_letter.opening": 2, "resume.acme.platform.bullet_1": 1}}

Other top-level keys (the curator's rationale) are ignored. A unit the JSON does not name keeps
whatever pick it already has. The script exits 1 when any unit is still unpicked afterwards.
"""

import argparse
import json
import sys
from pathlib import Path

from stitch import PICK_LINE_RE, UNIT_MARKER_RE, VARIANT_HEADER_RE, parse_variants_md


def apply_picks(text: str, picks: dict[str, int]) -> str:
    """Return variants.md text with exactly the chosen variant checked in each named unit."""
    units = {unit.unit_id: {variant.n for variant in unit.variants} for unit in parse_variants_md(text)}
    for unit_id, n in picks.items():
        if unit_id not in units:
            raise ValueError(f"Unknown unit: {unit_id}")
        if type(n) is not int or n not in units[unit_id]:
            raise ValueError(f"Unit {unit_id} has no Variant {n}")

    out: list[str] = []
    unit_id: str | None = None
    variant_n: int | None = None
    for line in text.splitlines():
        unit_match = UNIT_MARKER_RE.search(line)
        header_match = VARIANT_HEADER_RE.match(line)
        if unit_match:
            unit_id, variant_n = unit_match.group(1), None
        elif header_match:
            variant_n = int(header_match.group(1))
        elif unit_id in picks and PICK_LINE_RE.match(line):
            line = f"- [{'x' if variant_n == picks[unit_id] else ' '}] Pick"
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def unpicked_units(text: str) -> list[str]:
    return [unit.unit_id for unit in parse_variants_md(text) if not any(v.picked for v in unit.variants)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mark curation choices as picks in variants.md.")
    parser.add_argument("app_dir", type=Path)
    parser.add_argument("curation", type=Path, help="JSON with a `picks` object: unit_id -> variant number")
    args = parser.parse_args(argv)

    picks = json.loads(args.curation.read_text())["picks"]
    variants_path = args.app_dir / "variants.md"
    updated = apply_picks(variants_path.read_text(), picks)
    variants_path.write_text(updated)

    missing = unpicked_units(updated)
    if missing:
        print(f"Units with no pick: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Marked {len(picks)} picks in {variants_path}")


if __name__ == "__main__":
    main()

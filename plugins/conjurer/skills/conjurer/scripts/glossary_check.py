# ABOUTME: /grimoire glossary checks: confirm the Glossary table parses, and list master-resume lines naming a term.
# ABOUTME: `rows` counts entries; `lines <term>` prints `L<n>\t<line>`; `units` prints the resume unit ids whose bullet names a term.
"""Implementation of `python3 glossary_check.py rows|lines|units <workspace> [<internal term>]`.

`lines` matches the term and its aliases with `glossary.entries_named`, the rule the glossary leak
check uses, so the lines /grimoire offers for a scale fact are exactly the lines it would flag.

`units` lists the eligible resume unit ids whose master-resume bullet names an internal term, with
the terms. A bullet no unit targets is copied into `resume.md` verbatim, so fast mode targets these
units in its outline: rewording a variant is the only way a leaking bullet can leave the resume.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from composer import compose_resume, resume_unit_ids
from glossary import entries_named, parse_glossary


def _rows(workspace: Path) -> None:
    entries, warnings = parse_glossary((workspace / "grimoire.md").read_text())
    print(f"{len(entries)} glossary entries")
    for warning in warnings:
        print(warning, file=sys.stderr)
    if warnings:
        raise SystemExit(1)


def _lines(parser: argparse.ArgumentParser, workspace: Path, internal_term: str) -> None:
    entries, _ = parse_glossary((workspace / "grimoire.md").read_text())
    matching = [entry for entry in entries if entry.internal_term == internal_term]
    if not matching:
        parser.error(f"{internal_term} is not an internal term in the Glossary of {workspace / 'grimoire.md'}")
    lines = (workspace / "master-resume.md").read_text().splitlines()
    for line_no, line in enumerate(lines, start=1):
        if entries_named(line, matching):
            print(f"L{line_no}\t{line}")


def _units(workspace: Path) -> None:
    entries, _ = parse_glossary((workspace / "grimoire.md").read_text())
    master = (workspace / "master-resume.md").read_text()
    master_lines = Counter(master.splitlines())
    for unit_id in resume_unit_ids(master):
        # Compose with a blank pick: the lines that disappear are exactly the bullet this unit replaces.
        replaced = master_lines - Counter(compose_resume(master, [(unit_id, "- ")]).splitlines())
        terms = list(dict.fromkeys(entry.internal_term for line in replaced for entry in entries_named(line, entries)))
        if terms:
            print(f"{unit_id}\t{', '.join(terms)}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Check the grimoire Glossary during /grimoire.")
    commands = parser.add_subparsers(dest="command", required=True)
    rows = commands.add_parser("rows", help="Count the Glossary entries; exit 1 on any malformed row.")
    rows.add_argument("workspace", type=Path)
    lines = commands.add_parser("lines", help="Print each master-resume line naming an internal term.")
    lines.add_argument("workspace", type=Path)
    lines.add_argument("internal_term")
    units = commands.add_parser("units", help="Print each resume unit id whose bullet names an internal term.")
    units.add_argument("workspace", type=Path)
    args = parser.parse_args(argv)

    if args.command == "rows":
        _rows(args.workspace)
    elif args.command == "lines":
        _lines(parser, args.workspace, args.internal_term)
    else:
        _units(args.workspace)


if __name__ == "__main__":
    main()

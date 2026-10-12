# ABOUTME: /grimoire glossary checks: confirm the Glossary table parses, and list master-resume lines naming a term.
# ABOUTME: `rows <workspace>` counts entries and exits 1 on any malformed row; `bullets <workspace> <term>` prints `L<n>\t<line>`.
"""Implementation of `python3 glossary_check.py rows|bullets <workspace> [<internal term>]`.

`bullets` matches the term and its aliases with the glossary leak rule (`glossary.find_leaks`), so
the bullets /grimoire offers for a scale fact are exactly the lines the leak check would flag.
"""

import argparse
import sys
from pathlib import Path

from glossary import find_leaks, parse_glossary


def _rows(workspace: Path) -> None:
    entries, warnings = parse_glossary((workspace / "grimoire.md").read_text())
    print(f"{len(entries)} glossary entries")
    for warning in warnings:
        print(warning, file=sys.stderr)
    if warnings:
        raise SystemExit(1)


def _bullets(parser: argparse.ArgumentParser, workspace: Path, internal_term: str) -> None:
    entries, _ = parse_glossary((workspace / "grimoire.md").read_text())
    matching = [entry for entry in entries if entry.internal_term == internal_term]
    if not matching:
        parser.error(f"{internal_term} is not an internal term in the Glossary of {workspace / 'grimoire.md'}")
    lines = (workspace / "master-resume.md").read_text().splitlines()
    for line_no, line in enumerate(lines, start=1):
        if find_leaks(line, matching):
            print(f"L{line_no}\t{line}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Check the grimoire Glossary during /grimoire.")
    commands = parser.add_subparsers(dest="command", required=True)
    rows = commands.add_parser("rows", help="Count the Glossary entries; exit 1 on any malformed row.")
    rows.add_argument("workspace", type=Path)
    bullets = commands.add_parser("bullets", help="Print each master-resume line naming an internal term.")
    bullets.add_argument("workspace", type=Path)
    bullets.add_argument("internal_term")
    args = parser.parse_args(argv)

    if args.command == "rows":
        _rows(args.workspace)
    else:
        _bullets(parser, args.workspace, args.internal_term)


if __name__ == "__main__":
    main()

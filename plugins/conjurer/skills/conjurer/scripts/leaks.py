# ABOUTME: Curation-time glossary leak check: names every variant in variants.md that uses an internal term.
# ABOUTME: Prints `<unit_id> #<n>\t<internal terms>` per leaking variant and exits 1, else "No glossary leaks.".
"""Implementation of `python3 leaks.py <app_dir> <workspace>`.

Reads the Glossary from `<workspace>/grimoire.md`. Malformed glossary rows are reported on
stderr and skipped; every well-formed row is still checked.
"""

import argparse
import sys
from pathlib import Path

from glossary import find_leaks, parse_glossary
from verify import variant_targets


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Flag variants that use an internal term from the glossary.")
    parser.add_argument("app_dir", type=Path)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args(argv)

    entries, warnings = parse_glossary((args.workspace / "grimoire.md").read_text())
    for warning in warnings:
        print(warning, file=sys.stderr)

    leaking = 0
    for variant_id, variant in variant_targets((args.app_dir / "variants.md").read_text()):
        terms = [entry.internal_term for entry in find_leaks(variant.content, entries)]
        if terms:
            leaking += 1
            unit_id, _, n = variant_id.rpartition("#")
            print(f"{unit_id} #{n}\t{', '.join(terms)}")
    if leaking:
        raise SystemExit(1)
    print("No glossary leaks.")


if __name__ == "__main__":
    main()

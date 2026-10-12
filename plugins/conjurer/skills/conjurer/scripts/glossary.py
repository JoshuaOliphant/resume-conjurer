# ABOUTME: Reads the grimoire's Glossary table and finds glossary leaks in generated text.
# ABOUTME: A leak is an internal term or alias appearing as a whole word, ignoring case, spaces, and hyphens.
"""The Glossary section is a `## Glossary` heading followed by a markdown table with the columns
`Internal term | Aliases | Public description`, aliases comma-separated. The section ends at the
next level-one or level-two heading.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

GLOSSARY_HEADING_RE = re.compile(r"^##\s+Glossary\s*$", re.IGNORECASE)
SECTION_END_RE = re.compile(r"^#{1,2}\s")
SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
WORD_RE = re.compile(r"\w")
COLUMNS = 3


@dataclass(frozen=True)
class GlossaryEntry:
    internal_term: str
    aliases: tuple[str, ...]
    public_description: str


def _cells(line: str) -> list[str]:
    row = line.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") else row
    return [cell.strip() for cell in row.split("|")]


def _row_entry(cells: list[str]) -> GlossaryEntry | str:
    """The entry a table row holds, or the reason the row is malformed."""
    if len(cells) != COLUMNS:
        return f"expected {COLUMNS} columns, found {len(cells)}"
    internal_term, aliases, public_description = cells
    if not internal_term:
        return "missing internal term"
    if not WORD_RE.search(internal_term):
        return "internal term has no letters or digits"
    if not public_description:
        return "missing public description"
    return GlossaryEntry(
        internal_term,
        tuple(alias.strip() for alias in aliases.split(",") if WORD_RE.search(alias)),
        public_description,
    )


def _is_header_or_separator(cells: list[str]) -> bool:
    return cells[0].lower() == "internal term" or all(SEPARATOR_CELL_RE.match(cell) for cell in cells)


def parse_glossary(grimoire: str) -> tuple[list[GlossaryEntry], list[str]]:
    """The glossary's entries, plus a warning naming the grimoire line of each skipped row."""
    entries: list[GlossaryEntry] = []
    warnings: list[str] = []
    in_glossary = False
    for line_no, line in enumerate(grimoire.splitlines(), start=1):
        if GLOSSARY_HEADING_RE.match(line):
            in_glossary = True
            continue
        if not in_glossary:
            continue
        if SECTION_END_RE.match(line):
            break
        if "|" not in line:
            continue
        cells = _cells(line)
        if _is_header_or_separator(cells):
            continue
        entry = _row_entry(cells)
        if isinstance(entry, GlossaryEntry):
            entries.append(entry)
        else:
            warnings.append(f"Glossary line {line_no}: {entry}")
    return entries, warnings


def _form_pattern(form: str) -> str:
    """A form's characters with any run of spaces or hyphens allowed between them."""
    characters = [re.escape(character) for character in form if character not in " -"]
    return r"[\s-]*".join(characters)


def _entry_re(entry: GlossaryEntry) -> re.Pattern[str]:
    forms = "|".join(_form_pattern(form) for form in (entry.internal_term, *entry.aliases))
    return re.compile(rf"(?<!\w)(?:{forms})(?!\w)", re.IGNORECASE)


def find_leaks(text: str, entries: Sequence[GlossaryEntry]) -> list[GlossaryEntry]:
    """The entries whose internal term or an alias occurs in the text as a whole word."""
    return [entry for entry in entries if _entry_re(entry).search(text)]

# ABOUTME: The citation grammar for variant citations, shared by the plugin scripts and the web app.
# ABOUTME: Pools master-resume.md and evidence.md lines, and resolves a variant's citation to them.
"""Resolve a variant's citation string to the evidence lines it names.

A citation holds one or more references separated by `;`, or by `,` when the next reference
names a file or a line. A reference is a file plus a line (`master-resume.md L16`) or a line
range (`L16-18`, `L16-L18`), a bare line that inherits the preceding file (`L17`), or an
`evidence.md - <label>` naming the evidence.md bullet with that lead label, or else every
bullet under the heading with that name. A reference that names no pooled line stays
ungrounded, so nothing downstream presents text the pool does not hold.
"""

import re
from collections.abc import Mapping
from typing import NamedTuple

MASTER_RESUME = "master-resume.md"
EVIDENCE = "evidence.md"

_REFERENCE_RE = re.compile(
    r"^(?:(?P<file>[\w.\-]+\.md)\s*)?"
    r"(?:L(?P<start>\d+)(?:\s*[-–]\s*L?(?P<end>\d+))?|-\s+(?P<label>.+))$"
)
_REFERENCE_SPLIT_RE = re.compile(r"\s*;\s*|\s*,\s*(?=[\w.\-]+\.md\b|L\d)")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(?:(?P<label>[^:]+):)?")
_HEADING_RE = re.compile(r"^#+\s+(?P<heading>.+?)\s*$")


class CitedLine(NamedTuple):
    """One resolved reference: a pool key when grounded, else the raw reference text."""

    id: str
    grounded: bool


def pool_lines(master_resume: str, evidence: str) -> dict[str, str]:
    """Every non-blank line of both sources, keyed `<file> L<n>`, master resume first."""
    lines: dict[str, str] = {}
    for file, text in ((MASTER_RESUME, master_resume), (EVIDENCE, evidence)):
        for n, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                lines[f"{file} L{n}"] = line
    return lines


def _evidence_md_by_label(label: str, lines: Mapping[str, str]) -> list[str]:
    wanted = label.strip().casefold()
    by_bullet: list[str] = []
    by_heading: list[str] = []
    in_heading = False
    for key, text in lines.items():
        if not key.startswith(f"{EVIDENCE} L"):
            continue
        heading = _HEADING_RE.match(text)
        if heading:
            in_heading = heading.group("heading").casefold() == wanted
            continue
        bullet = _BULLET_RE.match(text)
        if bullet is None:
            continue
        if bullet.group("label") and bullet.group("label").strip().casefold() == wanted:
            by_bullet.append(key)
        if in_heading:
            by_heading.append(key)
    return by_bullet or by_heading


def _resolve_reference(reference: re.Match[str], file: str, lines: Mapping[str, str]) -> list[str]:
    if reference.group("label") is not None:
        return _evidence_md_by_label(reference.group("label"), lines) if file == EVIDENCE else []
    start = int(reference.group("start"))
    end = int(reference.group("end") or start)
    return [key for n in range(start, end + 1) if (key := f"{file} L{n}") in lines]


def resolve_citation(citation: str, lines: Mapping[str, str]) -> list[CitedLine]:
    """Resolve every reference in ``citation`` against the pooled ``lines``."""
    cited: list[CitedLine] = []
    file: str | None = None
    for text in _REFERENCE_SPLIT_RE.split(citation.strip()):
        reference = _REFERENCE_RE.match(text)
        if reference and reference.group("file"):
            file = reference.group("file")
        keys = _resolve_reference(reference, file, lines) if reference and file else []
        cited.extend([CitedLine(key, True) for key in keys] or [CitedLine(text, False)])
    return cited


def is_well_formed_citation(citation: str) -> bool:
    """Check reference syntax without asserting that evidence exists or supports a claim."""
    file: str | None = None
    for text in _REFERENCE_SPLIT_RE.split(citation.strip()):
        reference = _REFERENCE_RE.fullmatch(text)
        if reference is None:
            return False
        if reference.group("file"):
            file = reference.group("file")
        if file not in (MASTER_RESUME, EVIDENCE):
            return False
        if reference.group("label") is not None:
            if file != EVIDENCE:
                return False
        else:
            start = int(reference.group("start"))
            end = int(reference.group("end") or start)
            if start < 1 or end < start:
                return False
    return True

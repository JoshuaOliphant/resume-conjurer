# ABOUTME: Prepares reviewed resume text for the plugin composer's master-resume grammar.
# ABOUTME: Exposes source-linked edits and correction needs before any source is saved.

from __future__ import annotations

import re
from dataclasses import dataclass

from app.adapters.scripts_path import ensure_scripts_on_path

ensure_scripts_on_path()

from composer import resume_unit_ids  # noqa: E402

EXPERIENCE_LINE = re.compile(r"^(?:#{1,6}\s+)?Experience\s*$", re.IGNORECASE)
SECTION_LINE = re.compile(r"^#{1,2}\s+(.+?)\s*$")
COMPANY_LINE = re.compile(r"^(?:###\s+|Company:\s*)(.+?)(?:\s*(?:\||—|--)\s*(.+))?$", re.IGNORECASE)
ROLE_LINE = re.compile(r"^(?:\*\*(.+?)\*\*|Role:\s*(.+?))(?:\s*(?:\||—|--)\s*(.+))?$", re.IGNORECASE)
BULLET_LINE = re.compile(r"^(?:[-*•])\s+(.+)$")
STRUCTURE_LABEL = re.compile(r"\b(?:Company|Role):", re.IGNORECASE)
DATE_RANGE = re.compile(
    r"\b(?P<start>(?:19|20)\d{2})\b\s*(?:-|–|—|to|through|until)\s*"
    r"(?P<end>(?:19|20)\d{2}|Present|Current)\b",
    re.IGNORECASE,
)
COMPANY_MARKER = "[enter employer context]"
ROLE_MARKER = "[enter role dates]"


@dataclass(frozen=True)
class NormalizationChange:
    source_line: int
    source: str
    normalized: str


@dataclass(frozen=True)
class NormalizedMaster:
    text: str
    changes: tuple[NormalizationChange, ...]
    corrections: tuple[str, ...]
    targets: tuple[str, ...]
    ready: bool


def _valid_role_dates(period: str) -> bool:
    match = DATE_RANGE.search(period)
    if match is None:
        return False
    end = match.group("end")
    return not end.isdigit() or int(end) >= int(match.group("start"))


def normalize_master_resume(text: str) -> NormalizedMaster:
    lines = text.splitlines()
    normalized: list[str] = []
    changes: list[NormalizationChange] = []
    corrections: list[str] = []
    in_experience = False
    saw_experience = False
    company = ""
    role = ""
    role_bullets = 0
    role_names: set[tuple[str, str]] = set()
    experience_lines: list[str] = []

    for number, source in enumerate(lines, start=1):
        value = source.strip()
        result = source
        labels = STRUCTURE_LABEL.findall(value)
        if in_experience and (len(labels) > 1 or labels and value.startswith(("### ", "**"))):
            corrections.append(f"Line {number}: multiple employer or role labels share one line; correct reading order.")
        if EXPERIENCE_LINE.fullmatch(value):
            result = "## Experience"
            in_experience = True
            saw_experience = True
            company = ""
            role = ""
        elif in_experience and (section := SECTION_LINE.fullmatch(value)):
            result = f"## {section.group(1)}"
            in_experience = False
        elif in_experience and (match := COMPANY_LINE.fullmatch(value)):
            company = match.group(1).strip()
            role = ""
            period = (match.group(2) or "").strip()
            if not period or COMPANY_MARKER in period:
                corrections.append(f"Line {number}: enter employer context from your source or confirm it yourself.")
                if not period:
                    period = COMPANY_MARKER
            result = f"### {company} -- {period}"
        elif in_experience and (match := ROLE_LINE.fullmatch(value)):
            role = (match.group(1) or match.group(2)).strip()
            if not company:
                corrections.append(f"Line {number}: role hierarchy needs an explicit employer heading.")
            key = (company.casefold(), role.casefold())
            if key in role_names:
                corrections.append(f"Line {number}: employer and role are ambiguous; distinguish the repeated role.")
            role_names.add(key)
            period = (match.group(3) or "").strip()
            if ROLE_MARKER in period or not _valid_role_dates(period):
                corrections.append(f"Line {number}: confirm complete role dates from your source or correct them yourself.")
                if not period:
                    period = ROLE_MARKER
            result = f"**{role}** -- {period}"
        elif in_experience and (match := BULLET_LINE.fullmatch(value)):
            result = f"- {match.group(1)}"
            if not role:
                corrections.append(f"Line {number}: bullet hierarchy needs an explicit employer and role.")
            else:
                role_bullets += 1
        elif in_experience and value and not role:
            corrections.append(f"Line {number}: experience hierarchy needs an explicit employer or role heading.")

        normalized.append(result)
        if in_experience:
            experience_lines.append(result)
        if result != source:
            changes.append(NormalizationChange(number, source, result))

    if not saw_experience:
        corrections.append("Add an explicit Experience heading before role history.")
    draft = "\n".join(normalized) + ("\n" if text.endswith("\n") else "")
    try:
        targets = resume_unit_ids(draft)
    except RuntimeError:
        targets = ()
    try:
        role_targets = resume_unit_ids("\n".join(experience_lines)) if saw_experience else ()
    except RuntimeError:
        role_targets = ()
    if role_bullets > len(role_targets):
        corrections.append("Some role bullets have no unambiguous composer target; correct the role hierarchy.")
    if not targets:
        corrections.append("No usable composer bullet slots were found.")
    return NormalizedMaster(draft, tuple(changes), tuple(dict.fromkeys(corrections)), targets, not corrections)

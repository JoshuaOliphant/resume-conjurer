# ABOUTME: Composes a tailored resume by slotting picked bullets into master-resume.md structure.
# ABOUTME: Matches sub-roles and standalone bullet sections; preserves untailored content.
"""Compose a tailored resume by slotting picked bullets into master-resume.md.

Walks master-resume.md and replaces only the bullet at each picked unit ID's
position, keeping other bullets in their original order.

Unit_id format: resume.<company>.<optional_subrole_qualifiers...>.bullet_<n>
  - 'resume.acme.bullet_1' matches the only Acme sub-role
  - 'resume.acme.platform.bullet_1' matches the Platform Team sub-role at Acme
  - Flat unit_ids that match multiple sub-roles use most-recent-start-year as tiebreaker

Standalone H2 bullet sections use resume.<normalized_heading>.bullet_<n>, matched
exactly. Untargeted roles, sections, and prose remain in their original positions.
Unknown or ambiguous targets raise RuntimeError rather than dropping picked content.
"""

import re
from dataclasses import dataclass, field

H3_RE = re.compile(r"^###\s+(.+?)\s+(?:—|--)\s+")
SUBROLE_RE = re.compile(r"^\*\*(.+?)\*\*\s*(?:—|--)\s*(.+?)$")
BULLET_RE = re.compile(r"^-\s")
EXPERIENCE_RE = re.compile(r"^##\s+Experience\s*$")
H2_RE = re.compile(r"^##\s+(.+?)\s*$")
NESTED_HEADING_RE = re.compile(r"^#{3,}\s+")
SECTION_UNIT_RE = re.compile(r"^resume\.([a-z0-9]+(?:_[a-z0-9]+)*)\.bullet_([1-9][0-9]*)$")
RESUME_UNIT_RE = re.compile(r"^resume(?:\.[a-z0-9]+(?:_[a-z0-9]+)*)+\.bullet_([1-9][0-9]*)$")
START_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

STOPWORDS = frozenset(
    {"the", "and", "for", "of", "an", "in", "on", "at", "to", "with",
     "from", "remote", "onsite", "wa", "ca"}
)


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in raw if len(t) >= 2 and t not in STOPWORDS}


@dataclass
class SubRole:
    title_line: str
    tokens: frozenset
    body_lines: list[str] = field(default_factory=list)
    bullet_blocks: list[list[int]] = field(default_factory=list)
    start_year: int = 0


@dataclass
class RoleBlock:
    h3_line: str
    company_tokens: frozenset
    sub_roles: list[SubRole] = field(default_factory=list)


@dataclass
class MasterStructure:
    preamble: list[str]
    experience_header: str
    role_blocks: list[RoleBlock]
    postamble: list[str]


@dataclass
class BulletSection:
    heading: str
    identifier: str
    bullet_blocks: list[list[int]] = field(default_factory=list)


def _identifier(text: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", text.lower()))


def _bullet_sections(lines: list[str]) -> list[BulletSection]:
    sections: list[BulletSection] = []
    current: BulletSection | None = None
    bullet: list[int] | None = None
    lazy = False
    direct = False
    for position, line in enumerate(lines):
        heading = H2_RE.match(line)
        if heading:
            current = BulletSection(heading=line, identifier=_identifier(heading.group(1)))
            sections.append(current)
            direct = True
            bullet = None
            lazy = False
        elif NESTED_HEADING_RE.match(line):
            direct = False
            bullet = None
            lazy = False
        elif direct and current is not None and BULLET_RE.match(line):
            bullet = [position]
            current.bullet_blocks.append(bullet)
            lazy = True
        elif not line.strip():
            lazy = False
        elif bullet is not None and line.startswith((" ", "\t")):
            bullet.append(position)
        elif bullet is not None and lazy:
            bullet.append(position)
        else:
            bullet = None
    return [section for section in sections if section.identifier and section.bullet_blocks]


def _match_section(unit_id: str, sections: list[BulletSection]) -> BulletSection | None:
    match = SECTION_UNIT_RE.fullmatch(unit_id)
    if match is None:
        return None
    candidates = [section for section in sections if section.identifier == match.group(1)]
    if len(candidates) > 1:
        raise RuntimeError(f"Ambiguous section target: {unit_id}")
    if not candidates:
        return None
    if int(match.group(2)) > len(candidates[0].bullet_blocks):
        raise RuntimeError(f"Could not match section bullet ordinal: {unit_id}")
    return candidates[0]


def _compose_sections(
    lines: list[str], sections: list[BulletSection], grouped: dict[int, dict[int, str]]
) -> list[str]:
    replacements: dict[int, list[str]] = {}
    for section in sections:
        for ordinal, bullet in grouped.get(id(section), {}).items():
            block = section.bullet_blocks[ordinal - 1]
            replacements.update({position: [] for position in block})
            replacements[block[0]] = [bullet]
    return [text for position, line in enumerate(lines) for text in replacements.get(position, [line])]


def parse_master_resume(text: str) -> MasterStructure:
    lines = text.splitlines()
    preamble: list[str] = []
    experience_header = ""
    role_blocks: list[RoleBlock] = []
    postamble: list[str] = []

    i = 0
    while i < len(lines):
        if EXPERIENCE_RE.match(lines[i]):
            experience_header = lines[i]
            i += 1
            break
        preamble.append(lines[i])
        i += 1

    if not experience_header:
        raise RuntimeError("Could not find '## Experience' section in master-resume.md")

    current_role: RoleBlock | None = None
    current_sub: SubRole | None = None
    bullet: list[int] | None = None
    lazy = False

    def flush_sub() -> None:
        nonlocal current_sub, bullet, lazy
        if current_sub is not None and current_role is not None:
            while current_sub.body_lines and not current_sub.body_lines[-1].strip():
                current_sub.body_lines.pop()
            current_role.sub_roles.append(current_sub)
            current_sub = None
            bullet = None
            lazy = False

    def flush_role() -> None:
        nonlocal current_role
        flush_sub()
        if current_role is not None:
            role_blocks.append(current_role)
            current_role = None

    while i < len(lines):
        line = lines[i]
        if H2_RE.match(line) and not EXPERIENCE_RE.match(line):
            flush_role()
            postamble = lines[i:]
            break

        h3 = H3_RE.match(line)
        if h3:
            flush_role()
            current_role = RoleBlock(
                h3_line=line,
                company_tokens=frozenset(_tokens(h3.group(1))),
            )
            i += 1
            continue

        sub = SUBROLE_RE.match(line)
        if sub and current_role is not None:
            flush_sub()
            year_match = START_YEAR_RE.search(sub.group(2))
            current_sub = SubRole(
                title_line=line,
                tokens=frozenset(_tokens(sub.group(1)) | current_role.company_tokens),
                start_year=int(year_match.group(0)) if year_match else 0,
            )
            i += 1
            continue

        if current_sub is not None:
            position = len(current_sub.body_lines)
            current_sub.body_lines.append(line)
            if BULLET_RE.match(line):
                bullet = [position]
                current_sub.bullet_blocks.append(bullet)
                lazy = True
            elif not line.strip():
                lazy = False
            elif bullet is not None and line.startswith((" ", "\t")):
                bullet.append(position)
            elif bullet is not None and lazy:
                bullet.append(position)
            else:
                bullet = None
            i += 1
            continue

        i += 1

    flush_role()
    return MasterStructure(
        preamble=preamble,
        experience_header=experience_header,
        role_blocks=role_blocks,
        postamble=postamble,
    )


def unit_id_tokens(unit_id: str) -> set[str]:
    """resume.acme.platform.bullet_1 -> {'acme', 'platform'}."""
    parts = unit_id.split(".")
    middle = parts[1:-1] if len(parts) > 2 else []
    tokens: set[str] = set()
    for part in middle:
        tokens.update(_tokens(part.replace("_", " ")))
    return tokens


def _subrole_candidates(unit_id: str, role_blocks: list[RoleBlock]) -> list[SubRole]:
    needed = unit_id_tokens(unit_id)
    if not needed:
        return []
    return [
        sr for rb in role_blocks for sr in rb.sub_roles if needed.issubset(sr.tokens)
    ]


def match_subrole(unit_id: str, role_blocks: list[RoleBlock]) -> SubRole | None:
    candidates = _subrole_candidates(unit_id, role_blocks)
    if not candidates:
        return None
    return max(candidates, key=lambda sr: sr.start_year)


def resume_unit_ids(master_text: str) -> tuple[str, ...]:
    """Canonical existing bullet targets, in document order, excluding ambiguous targets."""
    master = parse_master_resume(master_text)
    before = _bullet_sections(master.preamble)
    after = _bullet_sections(master.postamble)
    sections = before + after

    def section_ids(section: BulletSection) -> list[str]:
        prefix = f"resume.{section.identifier}"
        if sum(candidate.identifier == section.identifier for candidate in sections) != 1:
            return []
        if _subrole_candidates(f"{prefix}.bullet_1", master.role_blocks):
            return []
        return [f"{prefix}.bullet_{n}" for n in range(1, len(section.bullet_blocks) + 1)]

    targets = [unit_id for section in before for unit_id in section_ids(section)]
    for role in master.role_blocks:
        company = H3_RE.match(role.h3_line).group(1)
        for subrole in role.sub_roles:
            title = SUBROLE_RE.match(subrole.title_line).group(1)
            prefix = f"resume.{_identifier(company)}.{_identifier(title)}"
            if len(_subrole_candidates(f"{prefix}.bullet_1", master.role_blocks)) != 1:
                continue
            targets.extend(f"{prefix}.bullet_{n}" for n in range(1, len(subrole.bullet_blocks) + 1))
    targets.extend(unit_id for section in after for unit_id in section_ids(section))
    return tuple(targets)


def compose_resume(master_text: str, resume_picks: list[tuple[str, str]]) -> str:
    """Compose tailored resume by replacing matched role or section bullets with picks.

    resume_picks: list of (unit_id, content). Content may include
    leading '- ' or not; we normalize.

    Raises RuntimeError for invalid, duplicate, missing, or ambiguous targets.
    """
    master = parse_master_resume(master_text)
    before = _bullet_sections(master.preamble)
    after = _bullet_sections(master.postamble)

    grouped: dict[int, dict[int, str]] = {}
    unmatched: list[str] = []

    for unit_id, content in resume_picks:
        match = RESUME_UNIT_RE.fullmatch(unit_id)
        if match is None:
            raise RuntimeError(f"Invalid resume bullet unit ID: {unit_id}")
        ordinal = int(match.group(1))
        sr = match_subrole(unit_id, master.role_blocks)
        section = _match_section(unit_id, before + after)
        if sr is not None and section is not None:
            raise RuntimeError(f"Ambiguous role and section target: {unit_id}")
        target = section if section is not None else sr
        if target is None:
            unmatched.append(unit_id)
            continue
        bullet_count = len(target.bullet_blocks)
        if ordinal > bullet_count:
            raise RuntimeError(f"Could not match bullet ordinal: {unit_id}")
        target_picks = grouped.setdefault(id(target), {})
        if ordinal in target_picks:
            raise RuntimeError(f"Duplicate bullet position: {unit_id}")
        bullet = content.strip()
        if not bullet.startswith("- "):
            bullet = f"- {bullet.lstrip('-').strip()}"
        target_picks[ordinal] = bullet

    if unmatched:
        available = "\n".join(
            f"  - {sr.title_line}\n    tokens: {sorted(sr.tokens)}"
            for rb in master.role_blocks
            for sr in rb.sub_roles
        )
        unmatched_lines = "\n".join(
            f"  - {uid} (tokens: {sorted(unit_id_tokens(uid))})" for uid in unmatched
        )
        raise RuntimeError(
            f"Could not match {len(unmatched)} pick(s) to any sub-role or bullet section:\n"
            f"{unmatched_lines}\n"
            f"Available sub-roles:\n{available}"
        )

    out: list[str] = []
    out.extend(_compose_sections(master.preamble, before, grouped))
    out.append(master.experience_header)
    out.append("")

    for rb in master.role_blocks:
        out.append(rb.h3_line)
        for sr in rb.sub_roles:
            out.append("")
            out.append(sr.title_line)
            replacements = {
                position: []
                for ordinal in grouped.get(id(sr), {})
                for position in sr.bullet_blocks[ordinal - 1]
            }
            for ordinal, bullet_text in grouped.get(id(sr), {}).items():
                replacements[sr.bullet_blocks[ordinal - 1][0]] = [bullet_text]
            out.extend(
                text for position, line in enumerate(sr.body_lines)
                for text in replacements.get(position, [line])
            )
        out.append("")

    out.extend(_compose_sections(master.postamble, after, grouped))

    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    return text

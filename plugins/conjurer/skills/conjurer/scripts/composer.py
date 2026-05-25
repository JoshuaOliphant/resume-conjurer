# ABOUTME: Composes a tailored resume by slotting picked bullets into master-resume.md structure.
# ABOUTME: Matches unit_ids to sub-roles by token overlap; preserves untailored roles unchanged.

import re
from collections import defaultdict
from dataclasses import dataclass, field

H3_RE = re.compile(r"^###\s+(.+?)\s+(?:—|--)\s+")
SUBROLE_RE = re.compile(r"^\*\*(.+?)\*\*\s*(?:—|--)\s*(.+?)$")
BULLET_RE = re.compile(r"^-\s")
EXPERIENCE_RE = re.compile(r"^##\s+Experience\s*$")
H2_RE = re.compile(r"^##\s+")
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
    bullet_lines: list[str] = field(default_factory=list)
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

    def flush_sub() -> None:
        nonlocal current_sub
        if current_sub is not None and current_role is not None:
            current_role.sub_roles.append(current_sub)
            current_sub = None

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

        if BULLET_RE.match(line) and current_sub is not None:
            current_sub.bullet_lines.append(line)
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
    """resume.nordstrom.kubernetes.bullet_1 -> {'nordstrom', 'kubernetes'}."""
    parts = unit_id.split(".")
    middle = parts[1:-1] if len(parts) > 2 else []
    tokens: set[str] = set()
    for part in middle:
        tokens.update(_tokens(part.replace("_", " ")))
    return tokens


def match_subrole(unit_id: str, role_blocks: list[RoleBlock]) -> SubRole | None:
    needed = unit_id_tokens(unit_id)
    if not needed:
        return None
    candidates = [
        sr for rb in role_blocks for sr in rb.sub_roles if needed.issubset(sr.tokens)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda sr: sr.start_year)


def compose_resume(master_text: str, resume_picks: list[tuple[str, str]]) -> str:
    """Compose tailored resume by replacing matched sub-role bullets with picks.

    resume_picks: ordered list of (unit_id, content). Content may include
    leading '- ' or not; we normalize.

    Raises RuntimeError if any pick fails to match a sub-role.
    """
    master = parse_master_resume(master_text)

    grouped: dict[int, list[str]] = defaultdict(list)
    unmatched: list[str] = []

    for unit_id, content in resume_picks:
        sr = match_subrole(unit_id, master.role_blocks)
        if sr is None:
            unmatched.append(unit_id)
            continue
        bullet = content.strip()
        if not bullet.startswith("- "):
            bullet = f"- {bullet.lstrip('-').strip()}"
        grouped[id(sr)].append(bullet)

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
            f"Could not match {len(unmatched)} pick(s) to any sub-role:\n"
            f"{unmatched_lines}\n"
            f"Available sub-roles:\n{available}"
        )

    out: list[str] = []
    out.extend(master.preamble)
    out.append(master.experience_header)
    out.append("")

    for rb in master.role_blocks:
        out.append(rb.h3_line)
        for sr in rb.sub_roles:
            out.append("")
            out.append(sr.title_line)
            if id(sr) in grouped:
                out.extend(grouped[id(sr)])
            else:
                out.extend(sr.bullet_lines)
        out.append("")

    out.extend(master.postamble)

    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    return text

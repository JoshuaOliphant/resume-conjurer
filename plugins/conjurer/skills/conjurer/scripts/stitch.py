# ABOUTME: Parses variants.md picks and assembles cover_letter.md + resume.md.
# ABOUTME: Cover units join into prose; resume units compose into the master-resume structure.

import re
from dataclasses import dataclass, field
from pathlib import Path

from composer import compose_resume

UNIT_MARKER_RE = re.compile(r"<!--\s*conjurer:unit\s+id=([\w.\-]+)\s*-->")
VARIANT_HEADER_RE = re.compile(r"^###\s+Variant\s+\d+\b", re.MULTILINE)
PICK_LINE_RE = re.compile(r"^-\s+\[(\s|x|X)\]\s+Pick\s*$", re.MULTILINE)
AXIS_LINE_RE = re.compile(r"^\*Axis:.*?\*\s*$", re.MULTILINE)

COVER_LETTER_PREFIX = "cover_letter"
RESUME_PREFIX = "resume"


@dataclass
class Variant:
    content: str
    picked: bool


@dataclass
class Unit:
    unit_id: str
    variants: list[Variant] = field(default_factory=list)

    @property
    def picked(self) -> Variant | None:
        picks = [v for v in self.variants if v.picked]
        if len(picks) > 1:
            raise ValueError(f"Unit {self.unit_id} has {len(picks)} picks; expected exactly one")
        return picks[0] if picks else None


def parse_variants_md(text: str) -> list[Unit]:
    """Walk variants.md and return ordered list of Units.

    A variant's content runs from its `### Variant N` header to its `- [ ] Pick` line.
    Once the Pick line is seen, the variant is finalized and subsequent lines are
    ignored until the next variant header or unit marker.
    """
    units: list[Unit] = []
    current_unit: Unit | None = None
    in_variant = False
    current_lines: list[str] = []

    def finalize() -> None:
        nonlocal in_variant, current_lines
        if not in_variant or current_unit is None:
            in_variant = False
            current_lines = []
            return
        raw = "\n".join(current_lines).strip()
        pick_match = PICK_LINE_RE.search(raw)
        picked = bool(pick_match and pick_match.group(1).lower() == "x")
        content = PICK_LINE_RE.sub("", raw)
        content = AXIS_LINE_RE.sub("", content).strip()
        current_unit.variants.append(Variant(content=content, picked=picked))
        in_variant = False
        current_lines = []

    for line in text.splitlines():
        unit_match = UNIT_MARKER_RE.search(line)
        if unit_match:
            finalize()
            current_unit = Unit(unit_id=unit_match.group(1))
            units.append(current_unit)
            continue

        if VARIANT_HEADER_RE.match(line):
            finalize()
            in_variant = True
            continue

        if in_variant:
            current_lines.append(line)
            if PICK_LINE_RE.match(line):
                finalize()

    finalize()
    return units


def collect_picks(units: list[Unit]) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (cover_picks, resume_picks).

    cover_picks is a list of paragraph contents in document order.
    resume_picks is a list of (unit_id, content) tuples so the composer can
    match each pick to its sub-role.
    """
    cover_picks: list[str] = []
    resume_picks: list[tuple[str, str]] = []
    missing: list[str] = []
    multi: list[str] = []
    for unit in units:
        try:
            picked = unit.picked
        except ValueError as e:
            multi.append(str(e))
            continue
        if picked is None:
            missing.append(unit.unit_id)
            continue
        if unit.unit_id.startswith(COVER_LETTER_PREFIX):
            cover_picks.append(picked.content)
        elif unit.unit_id.startswith(RESUME_PREFIX):
            resume_picks.append((unit.unit_id, picked.content))
    errors = []
    if missing:
        errors.append(f"Units with no pick: {', '.join(missing)}")
    if multi:
        errors.append("Units with multiple picks:\n  " + "\n  ".join(multi))
    if errors:
        raise ValueError("\n".join(errors))
    return cover_picks, resume_picks


def stitch_app_dir(app_dir: Path, master_resume_path: Path, overwrite: bool = False) -> tuple[Path, Path]:
    """Read variants.md, write cover_letter.md and resume.md. Returns the paths written."""
    variants_path = app_dir / "variants.md"
    if not variants_path.exists():
        raise FileNotFoundError(f"{variants_path} not found. Run `conjure variants` first.")

    cover_path = app_dir / "cover_letter.md"
    resume_path = app_dir / "resume.md"
    existing = [p for p in (cover_path, resume_path) if p.exists()]
    if existing and not overwrite:
        names = ", ".join(p.name for p in existing)
        raise RuntimeError(
            f"{names} already exist(s) in {app_dir}. "
            f"Pass --overwrite to regenerate from current picks."
        )

    units = parse_variants_md(variants_path.read_text())
    if not units:
        raise ValueError(f"No conjurer units found in {variants_path}")
    cover_picks, resume_picks = collect_picks(units)
    cover_text = "\n\n".join(cover_picks) + "\n"
    resume_text = compose_resume(master_resume_path.read_text(), resume_picks)
    cover_path.write_text(cover_text)
    resume_path.write_text(resume_text)
    return cover_path, resume_path


def main() -> None:
    import sys
    if len(sys.argv) != 3:
        print("usage: python3 stitch.py <app_dir> <master_resume_path>", file=sys.stderr)
        raise SystemExit(2)
    cover, resume = stitch_app_dir(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Wrote {cover}")
    print(f"Wrote {resume}")


if __name__ == "__main__":
    main()

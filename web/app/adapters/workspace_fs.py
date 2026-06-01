# ABOUTME: Filesystem WorkspaceRepository — reads/writes one application's workspace files.
# ABOUTME: Round-trips outline.json and variants.md and hydrates the domain Application.

"""Filesystem-backed :class:`WorkspaceRepository`.

One workspace directory holds ``grimoire.md``, ``master-resume.md``, and an
``applications/<slug>/`` folder with ``jd.txt``, ``evidence.md``, and the
generated ``outline.json`` / ``variants.md``. This adapter is the only place that
knows that layout; the workspace root is injected so a future multi-user resolver
can scope a slug to a different root without touching these methods.

``variants.md`` is the canonical store for variants AND picks. Unlike
``stitch.py``'s parser, the parser here keeps the ``### Variant N: <citation>``
citation so we can resolve each variant's evidence trace back into the domain.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app.domain import (
    Application,
    Evidence,
    FRAMES,
    Frame,
    Outline,
    OutlineUnit,
    Unit,
    UnitKind,
    Variant,
    WorkspaceInputs,
    label_for_unit_id,
)

# variants.md grammar. The unit marker and pick line mirror stitch.py exactly so
# the two stay in lockstep; the variant header adds capturing groups for the
# variant number and its citation (which stitch.py discards).
UNIT_MARKER_RE = re.compile(r"<!--\s*conjurer:unit\s+id=([\w.\-]+)\s*-->")
VARIANT_HEADER_RE = re.compile(r"^###\s+Variant\s+(\d+):\s*(.*?)\s*$")
PICK_LINE_RE = re.compile(r"^-\s+\[(\s|x|X)\]\s+Pick\s*$")
AXIS_LINE_RE = re.compile(r"^\*Axis:.*?\*\s*$", re.MULTILINE)

COVER_LETTER_PREFIX = "cover_letter."
RESUME_PREFIX = "resume."

_L_CITATION_RE = re.compile(r"^master-resume\.md L\d+$")


def _kind_for(unit_id: str) -> UnitKind:
    """Infer a unit's kind from its id prefix."""
    if unit_id.startswith(COVER_LETTER_PREFIX):
        return "cover_paragraph"
    return "resume_bullet"


def _jd_excerpt(jd: str, sentences: int = 2) -> str:
    """First ~2 sentences of the JD, collapsed to a single line."""
    body = " ".join(jd.split())
    parts = re.split(r"(?<=[.!?])\s+", body)
    return " ".join(parts[:sentences]).strip()


class _ParsedVariant:
    """A variant as read from variants.md, before domain resolution."""

    def __init__(self, n: int, citation: str, text: str, picked: bool) -> None:
        self.n = n
        self.citation = citation
        self.text = text
        self.picked = picked


class _ParsedUnit:
    def __init__(self, unit_id: str) -> None:
        self.unit_id = unit_id
        self.variants: list[_ParsedVariant] = []


def _parse_variants_md(text: str) -> list[_ParsedUnit]:
    """Walk variants.md, keeping each variant's number and citation.

    A variant's content runs from its ``### Variant N: <citation>`` header to its
    ``- [ ] Pick`` line; the Axis line and Pick line are stripped from the text.
    """
    units: list[_ParsedUnit] = []
    current_unit: _ParsedUnit | None = None
    current_header: re.Match[str] | None = None
    current_lines: list[str] = []

    def finalize() -> None:
        nonlocal current_header, current_lines
        if current_header is None or current_unit is None:
            current_header = None
            current_lines = []
            return
        raw = "\n".join(current_lines).strip()
        pick_match = None
        for line in current_lines:
            m = PICK_LINE_RE.match(line)
            if m:
                pick_match = m
        picked = bool(pick_match and pick_match.group(1).lower() == "x")
        content = "\n".join(
            line for line in raw.splitlines() if not PICK_LINE_RE.match(line)
        )
        content = AXIS_LINE_RE.sub("", content).strip()
        current_unit.variants.append(
            _ParsedVariant(
                n=int(current_header.group(1)),
                citation=current_header.group(2).strip(),
                text=content,
                picked=picked,
            )
        )
        current_header = None
        current_lines = []

    for line in text.splitlines():
        unit_match = UNIT_MARKER_RE.search(line)
        if unit_match:
            finalize()
            current_unit = _ParsedUnit(unit_match.group(1))
            units.append(current_unit)
            continue

        header_match = VARIANT_HEADER_RE.match(line)
        if header_match:
            finalize()
            current_header = header_match
            continue

        if current_header is not None:
            current_lines.append(line)
            if PICK_LINE_RE.match(line):
                finalize()

    finalize()
    return units


class FsWorkspaceRepository:
    """Loads and persists one application's files against a workspace root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _app_dir(self, slug: str) -> Path:
        return self.root / "applications" / slug

    # --- inputs ------------------------------------------------------------

    def load_inputs(self, slug: str) -> WorkspaceInputs:
        app_dir = self._app_dir(slug)
        master_resume = (self.root / "master-resume.md").read_text()
        grimoire = (self.root / "grimoire.md").read_text()
        jd = (app_dir / "jd.txt").read_text()
        evidence = (app_dir / "evidence.md").read_text()

        evidence_pool: dict[str, Evidence] = {}
        for n, line in enumerate(master_resume.splitlines(), start=1):
            if not line.strip():
                continue
            ev_id = f"master-resume.md L{n}"
            evidence_pool[ev_id] = Evidence(id=ev_id, text=line, source=ev_id)

        return WorkspaceInputs(
            grimoire=grimoire,
            master_resume=master_resume,
            jd=jd,
            evidence=evidence,
            evidence_pool=evidence_pool,
        )

    # --- outline -----------------------------------------------------------

    def save_outline(self, slug: str, outline: Outline) -> None:
        data = {
            "strategic_frame": outline.strategic_frame,
            "frame_rationale": outline.frame_rationale,
            "company": outline.company,
            "role_title": outline.role_title,
            "cover_letter_units": [
                {"unit_id": u.unit_id, "description": u.description}
                for u in outline.cover_letter_units
            ],
            "resume_units": [
                {"unit_id": u.unit_id, "description": u.description}
                for u in outline.resume_units
            ],
        }
        path = self._app_dir(slug) / "outline.json"
        path.write_text(json.dumps(data, indent=2) + "\n")

    def load_outline(self, slug: str) -> Outline | None:
        path = self._app_dir(slug) / "outline.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())

        def _units(key: str) -> tuple[OutlineUnit, ...]:
            return tuple(
                OutlineUnit(
                    unit_id=u["unit_id"],
                    kind=_kind_for(u["unit_id"]),
                    description=u["description"],
                )
                for u in data[key]
            )

        return Outline(
            strategic_frame=data["strategic_frame"],
            frame_rationale=data["frame_rationale"],
            company=data["company"],
            role_title=data["role_title"],
            cover_letter_units=_units("cover_letter_units"),
            resume_units=_units("resume_units"),
        )

    # --- variants ----------------------------------------------------------

    def save_variants(self, slug: str, units: list[Unit]) -> None:
        lines: list[str] = ["# Conjurer Variants", ""]
        for unit in units:
            lines.append(f"## Unit: {unit.id}")
            lines.append(f"<!-- conjurer:unit id={unit.id} -->")
            lines.append("")
            for n, variant in enumerate(unit.variants, start=1):
                items = variant.evidence_items
                citation = items[0].id if items else "master-resume.md"
                lines.append(f"### Variant {n}: {citation}")
                lines.append("")
                lines.append(variant.text)
                lines.append("")
                lines.append("*Axis: variant distinction*")
                lines.append("")
                lines.append("- [ ] Pick")
                lines.append("")
        path = self._app_dir(slug) / "variants.md"
        path.write_text("\n".join(lines))

    def set_pick(self, slug: str, unit_id: str, variant_id: str) -> None:
        target_n = int(variant_id.rsplit("#", 1)[1])
        path = self._app_dir(slug) / "variants.md"
        out_lines: list[str] = []
        in_target_unit = False
        current_variant_n: int | None = None
        for line in path.read_text().splitlines():
            unit_match = UNIT_MARKER_RE.search(line)
            if unit_match:
                in_target_unit = unit_match.group(1) == unit_id
                current_variant_n = None
                out_lines.append(line)
                continue
            header_match = VARIANT_HEADER_RE.match(line)
            if header_match:
                current_variant_n = int(header_match.group(1))
                out_lines.append(line)
                continue
            if in_target_unit and PICK_LINE_RE.match(line):
                checked = "x" if current_variant_n == target_n else " "
                out_lines.append(f"- [{checked}] Pick")
                continue
            out_lines.append(line)
        path.write_text("\n".join(out_lines))

    def get_picks(self, slug: str) -> dict[str, str]:
        path = self._app_dir(slug) / "variants.md"
        picks: dict[str, str] = {}
        for unit in _parse_variants_md(path.read_text()):
            for variant in unit.variants:
                if variant.picked:
                    picks[unit.unit_id] = f"{unit.unit_id}#{variant.n}"
        return picks

    # --- hydration ---------------------------------------------------------

    def _resolve_citation(
        self, citation: str, pool: dict[str, Evidence], cache: dict[str, Evidence]
    ) -> Evidence:
        if citation in cache:
            return cache[citation]
        if _L_CITATION_RE.match(citation) and citation in pool:
            ev = pool[citation]
        else:
            ev = Evidence(id=citation, text=citation, source=citation)
        cache[citation] = ev
        return ev

    def load_application(self, slug: str) -> Application:
        outline = self.load_outline(slug)
        if outline is None:
            raise FileNotFoundError(f"No outline.json for {slug!r}; run generation first.")
        inputs = self.load_inputs(slug)
        pool = inputs.evidence_pool

        contexts = {u.unit_id: u.description for u in outline.units}
        order = {u.unit_id: i for i, u in enumerate(outline.units)}

        parsed = _parse_variants_md((self._app_dir(slug) / "variants.md").read_text())
        resolved: dict[str, Evidence] = {}

        units: list[Unit] = []
        for punit in parsed:
            context = contexts.get(punit.unit_id, "")
            variants = [
                Variant(
                    id=f"{punit.unit_id}#{pv.n}",
                    text=pv.text,
                    evidence_items=(self._resolve_citation(pv.citation, pool, resolved),),
                )
                for pv in punit.variants
            ]
            units.append(
                Unit(
                    id=punit.unit_id,
                    kind=_kind_for(punit.unit_id),
                    label=label_for_unit_id(punit.unit_id),
                    context=context,
                    variants=variants,
                )
            )

        units.sort(key=lambda u: order.get(u.id, len(order)))

        return Application(
            slug=slug,
            company=outline.company,
            role=outline.role_title,
            jd_excerpt=_jd_excerpt(inputs.jd),
            frame=Frame(name=FRAMES[outline.strategic_frame], rationale=outline.frame_rationale),
            units=units,
            evidence=dict(resolved),
        )


def default_repository() -> FsWorkspaceRepository:
    """Resolve the workspace root in one place: env ``CONJURER_WORKSPACE`` or the fixture."""
    env = os.environ.get("CONJURER_WORKSPACE")
    if env:
        return FsWorkspaceRepository(Path(env))
    fallback = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "workspace"
    return FsWorkspaceRepository(fallback)

# ABOUTME: Filesystem WorkspaceRepository — reads/writes one application's workspace files.
# ABOUTME: Round-trips outline.json, variants.md, and support.json and hydrates the domain Application.

"""Filesystem-backed :class:`WorkspaceRepository`.

One workspace directory holds ``grimoire.md``, ``master-resume.md``, and an
``applications/<slug>/`` folder with ``jd.txt``, ``evidence.md``, and the
generated ``outline.json`` / ``variants.md``. This adapter is the only place that
knows that layout; the workspace root is injected so a future multi-user resolver
can scope a slug to a different root without touching these methods.

``variants.md`` is the canonical store for variants AND picks. The parser here
keeps each variant's ``### Variant N: <citation>`` number and citation so we can
resolve its evidence trace back into the domain.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from app.adapters.scripts_path import ensure_scripts_on_path
from app.domain import (
    Application,
    Evidence,
    Frame,
    Outline,
    OutlineUnit,
    Support,
    Unit,
    UnitKind,
    Variant,
    WorkspaceInputs,
    label_for_unit_id,
    validate_slug,
)
from app.metrics import RunMetrics

ensure_scripts_on_path()

import citations  # noqa: E402
import verify  # noqa: E402

# variants.md grammar. The unit marker and pick line mirror stitch.py exactly so
# the two stay in lockstep.
UNIT_MARKER_RE = re.compile(r"<!--\s*conjurer:unit\s+id=([\w.\-]+)\s*-->")
VARIANT_HEADER_RE = re.compile(r"^###\s+Variant\s+(\d+):\s*(.*?)\s*$")
PICK_LINE_RE = re.compile(r"^-\s+\[(\s|x|X)\]\s+Pick\s*$")
AXIS_LINE_RE = re.compile(r"^\*Axis:.*?\*\s*$", re.MULTILINE)

COVER_LETTER_PREFIX = "cover_letter."
RESUME_PREFIX = "resume."

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


def _ungrounded(citation: str) -> Evidence:
    """A citation that resolves to no pooled line: shown as a citation, never as a quote."""
    return Evidence(id=citation, text=citation, source=citation, grounded=False)


def resolve_citation(citation: str, pool: Mapping[str, Evidence]) -> tuple[Evidence, ...]:
    """Resolve every reference in a variant's citation to its pooled evidence lines."""
    return tuple(
        pool[line.id] if line.grounded else _ungrounded(line.id)
        for line in citations.resolve_citation(citation, {key: ev.text for key, ev in pool.items()})
    )


def _claim_fingerprint(text: str, items: tuple[Evidence, ...]) -> str:
    """The support.json fingerprint of a variant: its text and the pooled lines it cites."""
    return verify.fingerprint(text, [item.text for item in items if item.grounded])


def _support_row(support: Support, fingerprint: str) -> dict:
    return {
        "verdict": support.verdict,
        "relation": support.relation,
        "relation_confidence": support.relation_confidence,
        "unstated": support.unstated,
        "unsourced_numbers": list(support.unsourced_numbers),
        "fingerprint": fingerprint,
    }


def _support_from_row(row: dict) -> Support:
    note = verify.note_for(row["verdict"], row["unsourced_numbers"])
    return Support(
        verdict=row["verdict"],
        note=note or None,
        unsourced_numbers=tuple(row["unsourced_numbers"]),
        relation=row["relation"],
        relation_confidence=row["relation_confidence"],
        unstated=row["unstated"],
        fingerprint=row["fingerprint"],
    )


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
        validate_slug(slug)
        return self.root / "applications" / slug

    # --- inputs ------------------------------------------------------------

    def load_inputs(self, slug: str) -> WorkspaceInputs:
        app_dir = self._app_dir(slug)
        master_resume = (self.root / "master-resume.md").read_text()
        grimoire = (self.root / "grimoire.md").read_text()
        jd = (app_dir / "jd.txt").read_text()
        evidence = (app_dir / "evidence.md").read_text()

        evidence_pool = {
            key: Evidence(id=key, text=line, source=key)
            for key, line in citations.pool_lines(master_resume, evidence).items()
        }

        return WorkspaceInputs(
            grimoire=grimoire,
            master_resume=master_resume,
            jd=jd,
            evidence=evidence,
            evidence_pool=evidence_pool,
        )

    def save_jd(self, slug: str, jd: str) -> None:
        app_dir = self._app_dir(slug)
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / "jd.txt").write_text(jd if jd.endswith("\n") else jd + "\n")

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
                citation = "; ".join(item.id for item in items) if items else citations.MASTER_RESUME
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

    # --- metrics -----------------------------------------------------------

    def save_metrics(self, slug: str, metrics: RunMetrics) -> None:
        path = self._app_dir(slug) / "metrics.json"
        path.write_text(json.dumps(metrics.to_dict(), indent=2) + "\n")

    def load_metrics(self, slug: str) -> RunMetrics | None:
        path = self._app_dir(slug) / "metrics.json"
        if not path.exists():
            return None
        return RunMetrics.from_dict(json.loads(path.read_text()))

    # --- support -----------------------------------------------------------

    def save_support(self, slug: str, support: dict[str, Support]) -> None:
        """Write support.json, fingerprinting each verdict against the variant in variants.md.

        A verdict for a variant that variants.md does not hold gets an empty fingerprint, so it
        never attaches on load.
        """
        pool = self.load_inputs(slug).evidence_pool
        parsed = _parse_variants_md((self._app_dir(slug) / "variants.md").read_text())
        fingerprints = {
            f"{punit.unit_id}#{pv.n}": _claim_fingerprint(pv.text, resolve_citation(pv.citation, pool))
            for punit in parsed
            for pv in punit.variants
        }
        document = {
            "model": verify.JEV_MODEL,
            "variants": {
                variant_id: _support_row(s, fingerprints.get(variant_id, ""))
                for variant_id, s in support.items()
            },
        }
        path = self._app_dir(slug) / "support.json"
        path.write_text(json.dumps(document, indent=2) + "\n")

    def load_support(self, slug: str) -> dict[str, Support]:
        path = self._app_dir(slug) / "support.json"
        if not path.exists():
            return {}
        rows = json.loads(path.read_text())["variants"]
        return {variant_id: _support_from_row(row) for variant_id, row in rows.items()}

    # --- hydration ---------------------------------------------------------

    def load_application(self, slug: str) -> Application:
        outline = self.load_outline(slug)
        if outline is None:
            raise FileNotFoundError(f"No outline.json for {slug!r}; run generation first.")
        inputs = self.load_inputs(slug)
        pool = inputs.evidence_pool

        contexts = {u.unit_id: u.description for u in outline.units}
        order = {u.unit_id: i for i, u in enumerate(outline.units)}

        parsed = _parse_variants_md((self._app_dir(slug) / "variants.md").read_text())
        support = self.load_support(slug)
        cited: dict[str, Evidence] = {}

        units: list[Unit] = []
        for punit in parsed:
            context = contexts.get(punit.unit_id, "")
            variants = []
            for pv in punit.variants:
                items = resolve_citation(pv.citation, pool)
                cited.update((item.id, item) for item in items)
                variant = Variant(id=f"{punit.unit_id}#{pv.n}", text=pv.text, evidence_items=items)
                verdict = support.get(variant.id)
                if verdict is not None and verdict.fingerprint == _claim_fingerprint(pv.text, items):
                    variant = replace(variant, support=verdict)
                variants.append(variant)
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
            frame=Frame(name=outline.frame_name, rationale=outline.frame_rationale),
            units=units,
            evidence=cited,
        )

# ABOUTME: Filesystem WorkspaceRepository — reads/writes one application's workspace files.
# ABOUTME: Round-trips outline.json, variants.md, and support.json and hydrates the domain Application.

"""Filesystem-backed :class:`WorkspaceRepository`.

One workspace directory holds ``grimoire.md``, ``master-resume.md``, and an
``applications/<slug>/`` folder with ``jd.txt``, ``evidence.md``, and the
generated ``outline.json`` / ``variants.md``. This adapter is the only place that
knows that layout; the workspace root is injected so a future multi-user resolver
can scope a slug to a different root without touching these methods.

``variants.md`` is the canonical store for variants AND picks. The stitch parser
keeps each variant's number and citation so we can resolve its evidence trace.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, replace
from pathlib import Path

from app.adapters.scripts_path import ensure_scripts_on_path
from app.domain import (
    ALL_FLAGGED_NOTE,
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
from app.generation_status import (
    GenerationStatusConflict,
    UnitGenerationStatus,
    decode_unit_statuses,
)
from app.metrics import RunMetrics

ensure_scripts_on_path()

import citations  # noqa: E402
import verify  # noqa: E402
from stitch import (  # noqa: E402
    PICK_LINE_RE,
    UNIT_MARKER_RE,
    VARIANT_HEADER_RE,
    parse_variants_md,
)

logger = logging.getLogger(__name__)

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


def cited_lines(items: Iterable[Evidence], pool: Mapping[str, Evidence]) -> list[str]:
    """The text of every pooled line a variant's evidence items cite."""
    return [line.text for item in items for line in resolve_citation(item.id, pool) if line.grounded]


def _claim_fingerprint(text: str, items: Iterable[Evidence], pool: Mapping[str, Evidence]) -> str:
    """The support.json fingerprint of a variant: its text and the pooled lines it cites."""
    return verify.fingerprint(text, cited_lines(items, pool))


def _all_flagged(variants: list[Variant]) -> bool:
    """True when the unit has variants and the claim check flagged every one of them."""
    return bool(variants) and all(v.support is not None and v.support.flagged for v in variants)


def _support_row(support: Support, fingerprint: str) -> dict:
    return {
        "verdict": support.verdict,
        "relation": support.relation,
        "relation_confidence": support.relation_confidence,
        "unstated": support.unstated,
        "unsourced_numbers": list(support.unsourced_numbers),
        "fingerprint": fingerprint,
    }


def support_from_row(row: dict) -> Support:
    """A support.json row as the domain's ``Support``, its note derived from the verdict."""
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
        try:
            evidence = (app_dir / "evidence.md").read_text()
        except FileNotFoundError:
            evidence = ""

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
        self._write_atomic(path, json.dumps(data, indent=2) + "\n")

    def begin_generation(self, slug: str, outline: Outline) -> None:
        path = self._app_dir(slug) / "outline.json"
        previous = path.read_text() if path.exists() else None
        try:
            self.save_outline(slug, outline)
            self.save_variants(slug, [])
        except OSError:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                self._write_atomic(path, previous)
            raise

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
        self._write_atomic(path, "\n".join(lines))

    def load_generation_status(self, slug: str) -> dict[str, UnitGenerationStatus] | None:
        path = self._app_dir(slug) / "generation.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("Invalid generation progress.")
        binding = data.get("outline")
        if not isinstance(binding, str) or not re.fullmatch(r"[0-9a-f]{64}", binding):
            raise ValueError("Invalid generation progress outline binding.")
        outline_bytes = path.with_name("outline.json").read_bytes()
        if binding != hashlib.sha256(outline_bytes).hexdigest():
            raise GenerationStatusConflict("Generation progress belongs to a different outline.")
        statuses = decode_unit_statuses(data.get("units"))
        outline = json.loads(outline_bytes)
        expected = {unit["unit_id"] for key in ("cover_letter_units", "resume_units") for unit in outline[key]}
        if set(statuses) != expected:
            raise ValueError("Generation progress does not cover the outline units.")
        return statuses

    def save_generation_status(self, slug: str, statuses: dict[str, UnitGenerationStatus]) -> None:
        path = self._app_dir(slug) / "generation.json"
        document = {"outline": hashlib.sha256(path.with_name("outline.json").read_bytes()).hexdigest(), "units": {key: asdict(value) for key, value in statuses.items()}}
        self._write_atomic(path, json.dumps(document, indent=2) + "\n")

    def save_unit_variants(self, slug: str, unit: Unit) -> None:
        path = self._app_dir(slug) / "variants.md"
        text = path.read_text() if path.exists() else "# Conjurer Variants\n\n"
        block = [f"## Unit: {unit.id}", f"<!-- conjurer:unit id={unit.id} -->", ""]
        for n, variant in enumerate(unit.variants, 1):
            citation = "; ".join(item.id for item in variant.evidence_items)
            block.extend([f"### Variant {n}: {citation}", "", variant.text, "", "*Axis: variant distinction*", "", "- [ ] Pick", ""])
        replacement = "\n".join(block) + "\n"
        pattern = re.compile(r"^## Unit: " + re.escape(unit.id) + r"[ \t]*\n.*?(?=^## Unit: |\Z)", re.M | re.S)
        text = pattern.sub(lambda _: replacement, text) if pattern.search(text) else text.rstrip() + "\n\n" + replacement
        self._write_atomic(path, text)

    def _write_atomic(self, path: Path, text: str) -> None:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            staged = Path(stream.name)
            try:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(staged, path)
            finally:
                staged.unlink(missing_ok=True)

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
        for unit in parse_variants_md(path.read_text() if path.exists() else ""):
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

    def save_support(
        self, slug: str, support: dict[str, Support], units: list[Unit], pool: Mapping[str, Evidence]
    ) -> None:
        """Write verdicts against the evidence snapshot used for their checks."""
        fingerprints = {
            variant.id: _claim_fingerprint(variant.text, variant.evidence_items, pool)
            for unit in units
            for variant in unit.variants
        }
        document = {
            "model": verify.JEV_MODEL,
            "variants": {
                variant_id: _support_row(s, s.fingerprint or fingerprints.get(variant_id, ""))
                for variant_id, s in support.items()
            },
        }
        path = self._app_dir(slug) / "support.json"
        path.write_text(json.dumps(document, indent=2) + "\n")

    def load_support(self, slug: str) -> dict[str, Support]:
        path = self._app_dir(slug) / "support.json"
        try:
            if not path.exists():
                return {}
            rows = json.loads(path.read_text())["variants"]
            return {variant_id: support_from_row(row) for variant_id, row in rows.items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            # Verdicts are advisory: a damaged support.json must not block curation.
            logger.warning("unreadable support.json for slug=%s: %r", slug, exc)
            return {}

    # --- hydration ---------------------------------------------------------

    def load_application(self, slug: str) -> Application:
        outline = self.load_outline(slug)
        if outline is None:
            raise FileNotFoundError(f"No outline.json for {slug!r}; run generation first.")
        inputs = self.load_inputs(slug)
        pool = inputs.evidence_pool

        contexts = {u.unit_id: u.description for u in outline.units}
        order = {u.unit_id: i for i, u in enumerate(outline.units)}

        variant_path = self._app_dir(slug) / "variants.md"
        parsed = parse_variants_md(variant_path.read_text() if variant_path.exists() else "")
        try:
            progress = self.load_generation_status(slug)
        except GenerationStatusConflict:
            progress = {}
            parsed = []
        except (OSError, ValueError):
            logger.warning("unreadable generation progress for slug=%s", slug)
            progress = None
        if progress is not None:
            parsed = [unit for unit in parsed if unit.unit_id in contexts and progress.get(unit.unit_id, UnitGenerationStatus(unit.unit_id)).state not in ("pending", "failed")]
        support = self.load_support(slug)
        cited: dict[str, Evidence] = {}

        units: list[Unit] = []
        for punit in parsed:
            context = contexts.get(punit.unit_id, "")
            variants = []
            for pv in punit.variants:
                items = resolve_citation(pv.citation, pool)
                cited.update((item.id, item) for item in items)
                variant = Variant(id=f"{punit.unit_id}#{pv.n}", text=pv.content, evidence_items=items)
                verdict = support.get(variant.id)
                if verdict is not None and verdict.fingerprint == _claim_fingerprint(pv.content, items, pool):
                    variant = replace(variant, support=verdict)
                variants.append(variant)
            units.append(
                Unit(
                    id=punit.unit_id,
                    kind=_kind_for(punit.unit_id),
                    label=label_for_unit_id(punit.unit_id),
                    context=context,
                    variants=variants,
                    grounding_note=ALL_FLAGGED_NOTE if _all_flagged(variants) else None,
                )
            )

        present = {unit.id for unit in units}
        for ou in outline.units:
            if ou.unit_id not in present:
                units.append(Unit(id=ou.unit_id, kind=ou.kind, label=label_for_unit_id(ou.unit_id), context=ou.description, variants=[]))
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

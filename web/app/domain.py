# ABOUTME: The Conjurer domain model — evidence, variants, units, frame, application, lint.
# ABOUTME: Pure types shared by every adapter (fake fixtures and the live SDK backend) and the UI.
"""Domain model for the Conjurer pipeline.

These are pure data types with no I/O and no global state. Both the fake fixtures
(``app.data``) and the live workspace/generation adapters build *these* objects, so
the templates and routes never know which backend produced them.

The trust mechanic — a variant may only cite evidence that exists in the application's
pool — is enforced by whatever builds a ``Variant`` (the adapter), not by this module.
A ``Variant`` therefore carries its evidence already resolved, so ``variant.evidence()``
needs no global lookup and the template can render only traces that were put there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

UnitKind = Literal["resume_bullet", "cover_paragraph"]

# The four strategic frames, keyed by the value the outline stores in `strategic_frame`.
FRAMES: dict[str, str] = {
    "scale": "Scale",
    "friction": "Friction removed",
    "conviction": "Conviction",
    "multiplier": "Force multiplier",
}


def label_for_unit_id(unit_id: str) -> str:
    """A short human label for a unit: the id's last segment, spaced and title-cased."""
    suffix = unit_id.rsplit(".", 1)[-1]
    return suffix.replace("_", " ").strip().title()


@dataclass(frozen=True)
class Evidence:
    """One line from the master resume or evidence pool that a variant can cite."""

    id: str
    text: str
    source: str  # where in the master resume / evidence this line lives


@dataclass(frozen=True)
class Variant:
    """One generated phrasing of a unit, carrying its already-resolved evidence trace."""

    id: str
    text: str
    evidence_items: tuple[Evidence, ...] = ()

    def evidence(self) -> list[Evidence]:
        # Method (not the raw field) so templates keep calling ``v.evidence()``.
        return list(self.evidence_items)


@dataclass
class Unit:
    """A single bullet or paragraph being tailored, with its competing variants."""

    id: str
    kind: UnitKind
    label: str  # short role of this unit, e.g. "Opening bullet"
    context: str  # why this unit matters for this JD
    variants: list[Variant]
    # When the JD asks for something the master resume only thinly supports, we say so
    # plainly rather than inventing. None means well-grounded.
    grounding_note: str | None = None

    @property
    def kind_label(self) -> str:
        return "Cover letter" if self.kind == "cover_paragraph" else "Résumé bullet"

    @property
    def tag_class(self) -> str:
        return "tag--cover" if self.kind == "cover_paragraph" else "tag--bullet"

    @property
    def variant_ids(self) -> set[str]:
        return {v.id for v in self.variants}


@dataclass(frozen=True)
class Frame:
    """The chosen strategic frame for an application: a display name and its rationale."""

    name: str
    rationale: str


@dataclass
class Application:
    """One tailored application: the JD context, chosen frame, units, and evidence pool."""

    slug: str
    company: str
    role: str
    jd_excerpt: str
    frame: Frame
    units: list[Unit]
    # The full evidence pool this application's variants may cite, keyed by id.
    evidence: dict[str, Evidence] = field(default_factory=dict)


@dataclass(frozen=True)
class LintCheck:
    """One grimoire style check run against the stitched documents."""

    label: str
    detail: str
    passed: bool


# --- Outline (the generation step before variants) -------------------------
# Mirrors applications/<slug>/outline.json (see plugins/conjurer .../references/pipeline.md):
# one strategic frame plus the unit skeleton, in document order, with no variants yet.


@dataclass(frozen=True)
class OutlineUnit:
    """One unit in the outline skeleton: its id, kind, and what it must accomplish."""

    unit_id: str
    kind: UnitKind
    description: str


@dataclass(frozen=True)
class Outline:
    """The strategic outline: chosen frame plus the cover-letter and resume unit skeletons."""

    strategic_frame: str  # one of FRAMES keys: scale | friction | conviction | multiplier
    frame_rationale: str
    company: str
    role_title: str
    cover_letter_units: tuple[OutlineUnit, ...]
    resume_units: tuple[OutlineUnit, ...]

    @property
    def frame_name(self) -> str:
        return FRAMES.get(self.strategic_frame, self.strategic_frame)

    @property
    def units(self) -> tuple[OutlineUnit, ...]:
        # Document order: cover letter first, then resume bullets (matches the UI rail).
        return self.cover_letter_units + self.resume_units


@dataclass(frozen=True)
class WorkspaceInputs:
    """The raw source material a generation step reads for one application."""

    grimoire: str
    master_resume: str
    jd: str
    evidence: str
    evidence_pool: dict[str, Evidence]

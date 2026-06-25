# ABOUTME: The Conjurer domain model — the frozen dataclasses the core and ports speak in.
# ABOUTME: Pure types only; no fixtures, no I/O, no provider coupling. Adapters hydrate these.
"""Domain model for the Conjurer pipeline.

These are the types the application core (entry -> outline -> curate -> review ->
export) is written against, independent of where the data comes from. A provider
adapter (the mock fixtures today, a live Agent SDK backend later) is responsible
for building these objects; the routes and templates only ever see the model.

The trust mechanic lives in the shape of the model: a `Variant` carries its
resolved `Evidence`, so by construction every trace shown on screen exists in the
pool the provider validated against. Resolving an unknown evidence id is a
provider-layer error, not something the templates have to guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

UnitKind = Literal["resume_bullet", "cover_paragraph"]


@dataclass(frozen=True)
class Evidence:
    """A line lifted from the master resume that a variant can cite."""

    id: str
    text: str
    source: str  # where in the master resume this line lives


@dataclass(frozen=True)
class Variant:
    """One grounded rephrasing of a unit, carrying the evidence it draws from.

    `evidence` is already resolved to `Evidence` objects, so every trace is valid
    by construction. The provider that builds the variant owns the id -> Evidence
    resolution and rejects citations outside its pool.
    """

    id: str
    text: str
    evidence: tuple[Evidence, ...] = ()


@dataclass
class Unit:
    """A single bullet or paragraph to tailor, with its candidate variants."""

    id: str
    kind: UnitKind
    label: str  # short role of this unit, e.g. "Opening bullet"
    context: str  # why this unit matters for this JD
    variants: list[Variant]
    # When the JD asks for something the master resume only thinly supports, we
    # say so plainly rather than inventing. None means well-grounded.
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

    def variant(self, variant_id: str | None) -> Variant:
        """Resolve a chosen variant id, falling back to the first variant.

        An unselected (or unknown) unit renders its first variant — the documented
        review-screen fallback. Callers that must reject unknown ids should check
        `variant_id in unit.variant_ids` first.
        """
        return next((v for v in self.variants if v.id == variant_id), self.variants[0])


@dataclass(frozen=True)
class Frame:
    """The single strategic frame the outline step chose for this application."""

    name: str
    rationale: str


@dataclass
class Application:
    """One tailored application: a JD, the chosen frame, and the units to curate."""

    slug: str
    company: str
    role: str
    jd_excerpt: str
    frame: Frame
    units: list[Unit]

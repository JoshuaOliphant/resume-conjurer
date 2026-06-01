# ABOUTME: The hexagonal ports — the interfaces the application core depends on.
# ABOUTME: Generation (the agent), composition (deterministic scripts), and the workspace repository.
"""Ports for the Conjurer backend (hexagonal architecture).

The FastAPI app and the run orchestrator depend only on these Protocols, never on a
concrete adapter. This is what lets the live SDK generation adapter and a deterministic
fake be swapped freely, and what keeps the agent's non-determinism quarantined behind a
typed contract.

- ``GenerationPort`` — the agent: turns source material into an outline and into variants.
  The one genuinely non-deterministic port; implemented live by the Claude Agent SDK
  adapter and offline by a fixture-backed fake.
- ``CompositionPort`` — the deterministic conjurer scripts (stitch / lint / export),
  which operate purely on the workspace directory.
- ``WorkspaceRepository`` — persistence and loading of one application's files
  (inputs, outline.json, variants.md and its picks), and hydration into the domain model.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain import (
    Application,
    LintCheck,
    Outline,
    OutlineUnit,
    Unit,
    Variant,
    WorkspaceInputs,
)
from app.metrics import CallMetrics, RunMetrics


@runtime_checkable
class GenerationPort(Protocol):
    """The agent. Produces the outline and the per-unit variants for an application.

    Implementations read the application's source material themselves (the live adapter
    via the agent's Read tool against the workspace ``cwd``). Generation is pure data:
    persistence is the repository's job, so these methods return domain objects and write
    nothing.

    ``last_call`` carries the metrics (cost/tokens/cache/timing) of the most recent
    ``outline``/``variants`` call, or None before any call has run. The RunManager reads it
    after each call to aggregate a run's cost and cache effectiveness.
    """

    last_call: CallMetrics | None

    async def outline(self, slug: str) -> Outline:
        """Choose one strategic frame and design the unit skeleton for ``slug``."""
        ...

    async def variants(self, slug: str, unit: OutlineUnit, n: int = 4) -> list[Variant]:
        """Generate ``n`` grounded, evidence-cited variants for one outline unit."""
        ...

    async def aclose(self) -> None:
        """Release any held resources (e.g. a persistent SDK client). No-op if none."""
        ...


@runtime_checkable
class CompositionPort(Protocol):
    """The deterministic conjurer scripts. Operate on the workspace application directory.

    ``lint`` depends on ``stitch`` having run, because the linter reads the stitched
    ``cover_letter.md`` / ``resume.md`` from disk.
    """

    def stitch(self, slug: str) -> None:
        """Assemble cover_letter.md and resume.md from the picked variants."""
        ...

    def lint(self, slug: str) -> list[LintCheck]:
        """Run the grimoire style checks against the stitched documents."""
        ...

    def export(self, slug: str, formats: tuple[str, ...] = ("pdf", "docx")) -> dict[str, str]:
        """Export the stitched documents; map each target to 'written' or 'skipped: ...'."""
        ...


@runtime_checkable
class WorkspaceRepository(Protocol):
    """Loads and persists one application's files; hydrates the domain model.

    A single fixed workspace today (one grimoire + master-resume + applications/), but the
    slug parameter on every method is the seam: a future multi-user resolver scopes which
    workspace a slug resolves to without changing these signatures.
    """

    def load_inputs(self, slug: str) -> WorkspaceInputs:
        """Read grimoire, master resume, JD, evidence, and build the evidence pool."""
        ...

    def save_jd(self, slug: str, jd: str) -> None:
        """Persist the pasted job description to applications/<slug>/jd.txt before generating."""
        ...

    def save_outline(self, slug: str, outline: Outline) -> None:
        """Persist the outline to applications/<slug>/outline.json."""
        ...

    def load_outline(self, slug: str) -> Outline | None:
        """Load the persisted outline, or None if generation has not produced it yet."""
        ...

    def save_variants(self, slug: str, units: list[Unit]) -> None:
        """Write applications/<slug>/variants.md from the generated units."""
        ...

    def set_pick(self, slug: str, unit_id: str, variant_id: str) -> None:
        """Mark exactly one '- [x] Pick' for unit_id in variants.md (the stitch contract)."""
        ...

    def get_picks(self, slug: str) -> dict[str, str]:
        """Return the current unit_id -> picked variant_id mapping from variants.md."""
        ...

    def load_application(self, slug: str) -> Application:
        """Hydrate the full Application (frame, units, variants, evidence) from the workspace."""
        ...

    def save_metrics(self, slug: str, metrics: RunMetrics) -> None:
        """Persist a run's metrics to applications/<slug>/metrics.json."""
        ...

    def load_metrics(self, slug: str) -> RunMetrics | None:
        """Load the persisted run metrics, or None if none have been written yet."""
        ...

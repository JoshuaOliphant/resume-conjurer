# ABOUTME: Offline GenerationPort — a deterministic fake over the data.py fixtures.
# ABOUTME: Lets the run orchestrator and route tests exercise the full flow without the API.
"""A fixture-backed GenerationPort.

Produces the same domain objects the live SDK adapter does, derived from the bundled
fixtures, so tests can drive the outline -> variants -> save -> load flow with no network.
It synthesizes convention-compliant unit_ids (cover_letter.* / resume.*) so its output
round-trips through the real workspace repository (which infers a unit's kind from that
prefix).
"""

from __future__ import annotations

from app.data import get_application
from app.domain import Application, FRAMES, Outline, OutlineUnit, Variant
from app.metrics import CallMetrics


class FakeGenerationPort:
    """GenerationPort backed by the static fixtures."""

    def __init__(self, application: Application | None = None) -> None:
        self._app = application or get_application()
        # Metrics of the most recent call; None until the first outline()/variants() runs.
        self.last_call: CallMetrics | None = None
        self._calls = 0
        self._outline_units: list[OutlineUnit] = []
        self._fixture_by_id: dict[str, list[Variant]] = {}
        cover_n = resume_n = 0
        for unit in self._app.units:
            if unit.kind == "cover_paragraph":
                cover_n += 1
                unit_id = f"cover_letter.{'opening' if cover_n == 1 else f'p{cover_n}'}"
            else:
                resume_n += 1
                unit_id = f"resume.fixture.bullet_{resume_n}"
            self._outline_units.append(
                OutlineUnit(unit_id=unit_id, kind=unit.kind, description=unit.context)
            )
            self._fixture_by_id[unit_id] = unit.variants

    def _record_call(self) -> None:
        """Synthesize deterministic metrics for one call: cold first, warm thereafter.

        The first call creates cache but reads none (a cold prompt cache); every call after
        reads from the warm cache with only a little new creation, so the aggregated
        cache_hit_pct and variant_cache_hit_pct compute to non-trivial values offline.
        """
        cold = self._calls == 0
        self._calls += 1
        self.last_call = CallMetrics(
            cost_usd=0.01,
            input_tokens=200,
            output_tokens=120,
            cache_read_tokens=0 if cold else 8000,
            cache_creation_tokens=12000 if cold else 200,
            duration_ms=900,
            duration_api_ms=700,
            num_turns=1,
        )

    async def outline(self, slug: str) -> Outline:
        self._record_call()
        frame_key = next(
            (k for k, name in FRAMES.items() if name == self._app.frame.name), "scale"
        )
        cover = tuple(u for u in self._outline_units if u.kind == "cover_paragraph")
        resume = tuple(u for u in self._outline_units if u.kind == "resume_bullet")
        return Outline(
            strategic_frame=frame_key,
            frame_rationale=self._app.frame.rationale,
            company=self._app.company,
            role_title=self._app.role,
            cover_letter_units=cover,
            resume_units=resume,
        )

    async def variants(self, slug: str, unit: OutlineUnit, n: int = 4) -> list[Variant]:
        self._record_call()
        source = self._fixture_by_id.get(unit.unit_id, [])
        return [
            Variant(id=f"{unit.unit_id}#{k}", text=v.text, evidence_items=v.evidence_items)
            for k, v in enumerate(source[:n], start=1)
        ]

    async def aclose(self) -> None:
        # The fake holds no resources; present so callers can close any GenerationPort.
        return None

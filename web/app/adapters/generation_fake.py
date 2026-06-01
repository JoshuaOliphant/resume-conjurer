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


class FakeGenerationPort:
    """GenerationPort backed by the static fixtures."""

    def __init__(self, application: Application | None = None) -> None:
        self._app = application or get_application()
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

    async def outline(self, slug: str) -> Outline:
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
        source = self._fixture_by_id.get(unit.unit_id, [])
        return [
            Variant(id=f"{unit.unit_id}#{k}", text=v.text, evidence_items=v.evidence_items)
            for k, v in enumerate(source[:n], start=1)
        ]

    async def aclose(self) -> None:
        # The fake holds no resources; present so callers can close any GenerationPort.
        return None

# ABOUTME: Offline VerificationPort adapters: a fake that answers from a script, and a no-op.
# ABOUTME: The no-op backs the live config until the Jev claim check is wired into the web app.

from __future__ import annotations

from collections.abc import Mapping

from app.domain import Evidence, Support, Unit


class FakeVerificationPort:
    """Returns the scripted verdict for each of a unit's variants, or raises the scripted error."""

    def __init__(
        self, verdicts: dict[str, Support] | None = None, error: Exception | None = None
    ) -> None:
        self._verdicts = verdicts or {}
        self._error = error

    async def verify(self, unit: Unit, pool: Mapping[str, Evidence]) -> dict[str, Support]:
        if self._error is not None:
            raise self._error
        return {
            variant_id: support
            for variant_id, support in self._verdicts.items()
            if variant_id in unit.variant_ids
        }

    async def aclose(self) -> None:
        return None


class NoVerificationPort:
    """Checks nothing, so no variant carries a verdict."""

    async def verify(self, unit: Unit, pool: Mapping[str, Evidence]) -> dict[str, Support]:
        return {}

    async def aclose(self) -> None:
        return None

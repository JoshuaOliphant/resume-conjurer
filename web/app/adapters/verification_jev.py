# ABOUTME: Live VerificationPort — checks each variant's claim against its cited evidence with Jev.
# ABOUTME: Reuses the plugin's stdlib verify.check_variant in worker threads, a bounded number at once.

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Protocol

from app.adapters.scripts_path import ensure_scripts_on_path
from app.adapters.workspace_fs import cited_lines, support_from_row
from app.domain import Evidence, Support, Unit, Variant

ensure_scripts_on_path()

import verify  # noqa: E402
from glossary import GlossaryEntry  # noqa: E402


class CheckVariant(Protocol):
    def __call__(
        self,
        claim: str,
        cited: list[str],
        pool: list[str],
        api_key: str,
        *,
        glossary: Sequence[GlossaryEntry],
    ) -> dict:
        """One support.json row for the claim, judged against its cited lines and the pool."""
        ...


class JevVerificationPort:
    """Asks Jev how each variant's cited lines bear on its claim, at most ``concurrency`` at once."""

    def __init__(
        self,
        api_key: str,
        concurrency: int = verify.CONCURRENCY,
        check: CheckVariant = verify.check_variant,
    ) -> None:
        self._api_key = api_key
        self._semaphore = asyncio.Semaphore(concurrency)
        self._check = check

    async def _verify_variant(
        self,
        variant: Variant,
        pool: Mapping[str, Evidence],
        pool_lines: list[str],
        glossary: Sequence[GlossaryEntry],
    ) -> Support:
        cited = cited_lines(variant.evidence_items, pool)
        async with self._semaphore:
            row = await asyncio.to_thread(
                self._check, variant.text, cited, pool_lines, self._api_key, glossary=glossary
            )
        return support_from_row(row)

    async def verify(
        self, unit: Unit, pool: Mapping[str, Evidence], glossary: Sequence[GlossaryEntry]
    ) -> dict[str, Support]:
        pool_lines = [evidence.text for evidence in pool.values()]
        supports = await asyncio.gather(
            *(self._verify_variant(variant, pool, pool_lines, glossary) for variant in unit.variants)
        )
        return {variant.id: support for variant, support in zip(unit.variants, supports)}

    async def aclose(self) -> None:
        return None

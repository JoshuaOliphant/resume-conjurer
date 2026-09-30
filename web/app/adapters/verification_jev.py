# ABOUTME: Live VerificationPort — checks each variant's claim against its cited evidence with Jev.
# ABOUTME: Reuses the plugin's stdlib verify.check_variant in worker threads, a bounded number at once.

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

from app.adapters.scripts_path import ensure_scripts_on_path
from app.adapters.workspace_fs import resolve_citation
from app.domain import Evidence, Support, Unit, Variant

ensure_scripts_on_path()

import verify  # noqa: E402

CheckVariant = Callable[[str, list[str], list[str], str], dict]


def support_from_row(row: dict) -> Support:
    """A support.json row from ``verify.check_variant`` as the domain's ``Support``."""
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


def _cited_lines(variant: Variant, pool: Mapping[str, Evidence]) -> list[str]:
    return [
        line.text
        for item in variant.evidence_items
        for line in resolve_citation(item.id, pool)
        if line.grounded
    ]


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
        self, variant: Variant, pool: Mapping[str, Evidence], pool_lines: list[str]
    ) -> Support:
        cited = _cited_lines(variant, pool)
        async with self._semaphore:
            row = await asyncio.to_thread(
                self._check, variant.text, cited, pool_lines, self._api_key
            )
        return support_from_row(row)

    async def verify(self, unit: Unit, pool: Mapping[str, Evidence]) -> dict[str, Support]:
        pool_lines = [evidence.text for evidence in pool.values()]
        supports = await asyncio.gather(
            *(self._verify_variant(variant, pool, pool_lines) for variant in unit.variants)
        )
        return {variant.id: support for variant, support in zip(unit.variants, supports)}

    async def aclose(self) -> None:
        return None

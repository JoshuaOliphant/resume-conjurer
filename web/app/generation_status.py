# ABOUTME: Unit generation states and validation for complete variant sets.
# ABOUTME: Keeps progress and validity independent of persistence and SDK messages.
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.domain import Variant


@dataclass
class UnitGenerationStatus:
    unit_id: str
    state: Literal["pending", "generating", "succeeded", "failed"] = "pending"
    error: str | None = None


def validate_unit_variants(variants: list[Variant], expected: int = 4) -> None:
    if len(variants) != expected:
        raise ValueError("Generation did not return four variants.")
    for variant in variants:
        if not variant.text.strip():
            raise ValueError("Generation returned an empty variant.")
        if not variant.evidence_items or any(
            not item.grounded and not re.fullmatch(r"(?:master-resume|evidence)\.md L[1-9]\d*(?:-L?[1-9]\d*)?(?:;\s*(?:master-resume|evidence)\.md L[1-9]\d*(?:-L?[1-9]\d*)?)*", item.id)
            for item in variant.evidence_items
        ):
            raise ValueError("Generation returned malformed citation references.")


class GenerationStatusConflict(ValueError):
    pass


def decode_unit_statuses(value: object) -> dict[str, UnitGenerationStatus]:
    if not isinstance(value, dict):
        raise ValueError("Invalid generation progress.")
    statuses = {}
    for unit_id, item in value.items():
        if not isinstance(unit_id, str) or not isinstance(item, dict):
            raise ValueError("Invalid generation progress.")
        state = item.get("state")
        error = item.get("error")
        if item.get("unit_id") != unit_id or state not in ("pending", "generating", "succeeded", "failed") or (error is not None and not isinstance(error, str)):
            raise ValueError("Invalid generation progress.")
        statuses[unit_id] = UnitGenerationStatus(unit_id, state, error)
    return statuses

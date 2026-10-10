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

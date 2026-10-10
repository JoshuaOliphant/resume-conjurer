# ABOUTME: Completeness and citation-syntax checks for generated variant sets.
# ABOUTME: Tests the pure validation boundary with domain values.
from dataclasses import replace

import pytest

from app.domain import Evidence, Variant
from app.generation_status import validate_unit_variants


@pytest.mark.parametrize("count,text,citation", [
    (0, "Built a service", "master-resume.md L16"),
    (3, "Built a service", "master-resume.md L16"),
    (5, "Built a service", "master-resume.md L16"),
    (4, " ", "master-resume.md L16"),
    (4, "Built a service", "An impressive angle"),
])
def test_incomplete_results_are_rejected(count, text, citation):
    variants = [Variant(str(n), text, (Evidence(citation, "", citation, False),)) for n in range(count)]
    with pytest.raises(ValueError):
        validate_unit_variants(variants)


def test_supported_and_unverified_references_are_not_semantically_graded():
    citation = "master-resume.md L16-18; evidence.md L5"
    variant = Variant("u#1", "Built a service", (Evidence(citation, "", citation, False),))
    validate_unit_variants([replace(variant, id=f"u#{n}") for n in range(1, 5)])
    with pytest.raises(ValueError):
        validate_unit_variants([replace(variant, evidence_items=())] * 4)

# ABOUTME: Tests for the Jev VerificationPort: row mapping, citation resolution, and the concurrency bound.
# ABOUTME: Offline tests inject a fake check callable; the `live` test asks the real Jev API.

import asyncio
import os
import threading
import time
from pathlib import Path

import pytest

from app.adapters.verification_jev import JevVerificationPort
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.domain import Evidence, Unit, Variant

FIXTURE = Path(__file__).parent / "fixtures" / "workspace"
SLUG = "globex-staff-platform"
POOL = FsWorkspaceRepository(FIXTURE).load_inputs(SLUG).evidence_pool
PAGING_LINE = (
    "- Owned the billing on-call rotation; cut paging volume 60% by adding idempotency keys"
    " and a dead-letter replay tool."
)


def _variant(variant_id: str, text: str, citation: str) -> Variant:
    # Generated variants carry their raw citation as ungrounded evidence (generation_sdk).
    return Variant(
        id=variant_id,
        text=text,
        evidence_items=(Evidence(id=citation, text=citation, source=citation, grounded=False),),
    )


def _unit(*variants: Variant) -> Unit:
    return Unit(
        id="resume.northwind.billing.bullet_3",
        kind="resume_bullet",
        label="Bullet 3",
        context="Surface the on-call work.",
        variants=list(variants),
    )


def _row(verdict: str, unsourced: list[str], fingerprint: str = "f" * 64) -> dict:
    return {
        "verdict": verdict,
        "relation": "contradicts",
        "relation_confidence": 0.6,
        "unstated": 0.97,
        "unsourced_numbers": unsourced,
        "fingerprint": fingerprint,
    }


def test_verify_checks_each_variant_against_its_resolved_cited_lines():
    calls = []

    def check(claim, cited, pool, api_key):
        calls.append((claim, cited, pool, api_key))
        return _row("conflicts" if cited else "untraced", [])

    unit = _unit(
        _variant("v1", "Cut paging volume 80%.", "master-resume.md L18"),
        _variant("v2", "Ran a billing guild.", "master-resume.md L999"),
    )
    verdicts = asyncio.run(JevVerificationPort("ts-key", check=check).verify(unit, POOL))

    assert {vid: s.verdict for vid, s in verdicts.items()} == {"v1": "conflicts", "v2": "untraced"}
    pool_lines = [evidence.text for evidence in POOL.values()]
    assert sorted(calls) == [
        ("Cut paging volume 80%.", [PAGING_LINE], pool_lines, "ts-key"),
        ("Ran a billing guild.", [], pool_lines, "ts-key"),
    ]


@pytest.mark.parametrize(
    ("options", "variants", "bound"),
    [({}, 12, 8), ({"concurrency": 2}, 6, 2)],
    ids=["default-bound-is-eight", "explicit-bound"],
)
def test_verify_runs_at_most_concurrency_checks_at_once(options: dict, variants: int, bound: int):
    lock = threading.Lock()
    in_flight = 0
    peak = 0

    def check(claim, cited, pool, api_key):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        return _row("traced", [])

    unit = _unit(
        *(_variant(f"v{i}", "Led the migration.", "master-resume.md L16") for i in range(variants))
    )
    verdicts = asyncio.run(JevVerificationPort("ts-key", check=check, **options).verify(unit, POOL))

    assert len(verdicts) == variants
    assert peak == bound


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="no TYPESAFE_API_KEY")
def test_live_jev_flags_a_planted_fabricated_number():
    unit = _unit(
        _variant(
            "planted-80",
            "Owned the billing on-call rotation; cut paging volume 80% by adding idempotency keys"
            " and a dead-letter replay tool.",
            "master-resume.md L18",
        )
    )
    port = JevVerificationPort(os.environ["TYPESAFE_API_KEY"])
    verdicts = asyncio.run(port.verify(unit, POOL))
    planted = verdicts["planted-80"]
    assert planted.verdict in {"conflicts", "adds_detail"}, planted
    assert planted.unsourced_numbers == ("80",)

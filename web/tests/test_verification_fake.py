# ABOUTME: Tests for the offline VerificationPort adapters: the scripted fake and the no-op.
# ABOUTME: The fake answers only for the unit it is asked about and can be told to fail.

import asyncio

import pytest

from app.adapters.verification_fake import FakeVerificationPort, NoVerificationPort
from app.data import EVIDENCE, get_application
from app.domain import Support

UNIT = get_application().units[0]
FLAGGED = Support(verdict="adds_detail", note="Adds detail your evidence doesn't state: 12")
TRACED = Support(verdict="traced")


def test_fake_returns_the_scripted_verdicts_for_the_units_variants_only():
    verifier = FakeVerificationPort(
        {"cover-open-1": FLAGGED, "cover-open-2": TRACED, "bullet-migration-1": FLAGGED}
    )
    verdicts = asyncio.run(verifier.verify(UNIT, EVIDENCE))
    assert verdicts == {"cover-open-1": FLAGGED, "cover-open-2": TRACED}


def test_fake_without_a_script_has_no_verdicts():
    assert asyncio.run(FakeVerificationPort().verify(UNIT, EVIDENCE)) == {}


def test_fake_raises_the_scripted_error():
    verifier = FakeVerificationPort({"cover-open-1": FLAGGED}, error=TimeoutError("jev timed out"))
    with pytest.raises(TimeoutError, match="jev timed out"):
        asyncio.run(verifier.verify(UNIT, EVIDENCE))


def test_no_verification_port_returns_no_verdicts():
    assert asyncio.run(NoVerificationPort().verify(UNIT, EVIDENCE)) == {}


@pytest.mark.parametrize(
    "verifier",
    [pytest.param(FakeVerificationPort(), id="fake"), pytest.param(NoVerificationPort(), id="no-op")],
)
def test_aclose_holds_nothing_to_release(verifier):
    assert asyncio.run(verifier.aclose()) is None

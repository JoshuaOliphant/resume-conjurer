# ABOUTME: Tests for resume composition — slotting picked bullets into master-resume structure.
# ABOUTME: Verifies sub-role matching, untailored-role preservation, and unmatched-pick errors.
import composer
import pytest

MASTER = """# Master Resume

## Experience

### Acme Corp — Senior Engineer

**Platform Team** — 2021 to present
- Old platform bullet one.
- Old platform bullet two.

**Billing Team** — 2019 to 2021
- Old billing bullet.

## Education
- Some School
"""


def test_compose_replaces_matched_subrole_bullets():
    out = composer.compose_resume(MASTER, [("resume.acme.platform.bullet_1", "New platform bullet.")])
    assert "New platform bullet." in out
    assert "Old platform bullet one." not in out
    assert "Old billing bullet." in out  # untailored role preserved
    assert "## Education" in out  # postamble preserved


def test_unmatched_pick_raises():
    with pytest.raises(RuntimeError):
        composer.compose_resume(MASTER, [("resume.nonexistent.bullet_1", "x")])


def test_missing_experience_section_raises():
    with pytest.raises(RuntimeError):
        composer.parse_master_resume("# Resume\n\nNo experience header here.\n")


MASTER_TWO_SUBROLES = """# Master Resume

## Experience

### Acme Corp — Engineer

**Newer Team** — 2022 to present
- Old newer bullet.

**Older Team** — 2018 to 2022
- Old older bullet.

## Education
- Some School
"""


def test_tiebreaker_picks_higher_start_year_subrole():
    # resume.acme.bullet_1 has tokens {'acme'}, which matches both sub-roles because
    # both inherit company tokens. The tiebreaker should route to the newer sub-role.
    out = composer.compose_resume(
        MASTER_TWO_SUBROLES, [("resume.acme.bullet_1", "Tiebreaker bullet.")]
    )
    assert "Tiebreaker bullet." in out
    assert "Old newer bullet." not in out  # newer sub-role bullets replaced
    assert "Old older bullet." in out     # older sub-role untouched


def test_two_picks_for_same_subrole_both_appear():
    out = composer.compose_resume(
        MASTER,
        [
            ("resume.acme.platform.bullet_1", "New platform bullet A."),
            ("resume.acme.platform.bullet_2", "New platform bullet B."),
        ],
    )
    assert "New platform bullet A." in out
    assert "New platform bullet B." in out
    assert "Old platform bullet one." not in out


def test_flat_company_unit_id_matches_via_company_token():
    # resume.acme.bullet_1 tokens are {'acme'} — no sub-role qualifier.
    # Should still match the Acme Platform Team sub-role via company token inheritance.
    out = composer.compose_resume(MASTER, [("resume.acme.bullet_1", "Company-token bullet.")])
    assert "Company-token bullet." in out

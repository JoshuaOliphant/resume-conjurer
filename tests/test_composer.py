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

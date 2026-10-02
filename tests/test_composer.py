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
    assert "- New platform bullet.\n- Old platform bullet two." in out
    assert "Old platform bullet one." not in out
    assert "Old billing bullet." in out  # untailored role preserved
    assert "## Education" in out  # postamble preserved


def test_partial_pick_preserves_remaining_bullets_without_postamble():
    master = MASTER.split("## Education")[0]
    out = composer.compose_resume(master, [("resume.acme.platform.bullet_1", "Replacement.")])
    assert "- Replacement.\n- Old platform bullet two." in out
    assert out.endswith("- Old billing bullet.\n")


def test_partial_pick_preserves_untouched_role_bullet_continuations():
    master = MASTER.replace(
        "- Old platform bullet one.\n- Old platform bullet two.",
        "- Old platform bullet one.\n  Wrapped first line.\nand continues without indentation.\n"
        "- Old platform bullet two.\n  Wrapped second line.\nand continues too.",
    )
    out = composer.compose_resume(master, [("resume.acme.platform.bullet_1", "Replacement.")])
    assert "Wrapped first line." not in out
    assert "and continues without indentation." not in out
    assert "- Replacement.\n- Old platform bullet two.\n  Wrapped second line.\nand continues too." in out


def test_role_prose_stays_between_replaced_and_untouched_bullets():
    master = MASTER.replace(
        "- Old platform bullet one.\n- Old platform bullet two.",
        "- Old platform bullet one.\n\nRole context.\n  Further context.\n- Old platform bullet two.",
    )
    out = composer.compose_resume(master, [("resume.acme.platform.bullet_1", "Replacement.")])
    assert "- Replacement.\n\nRole context.\n  Further context.\n- Old platform bullet two." in out


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


def test_subrole_picks_follow_master_bullet_order():
    out = composer.compose_resume(MASTER, [
        ("resume.acme.platform.bullet_2", "Second replacement."),
        ("resume.acme.platform.bullet_1", "First replacement."),
    ])
    assert "- First replacement.\n- Second replacement." in out


@pytest.mark.parametrize("unit_id", [
    "resume.acme.platform.bullet_0", "resume.acme.platform.bullet_x",
    "resume.acme.platform.bullet_3", "resume.acme.platform.bullet_01",
    "resume.acme.platform.bullet_1x", "resume.acme.platform.bullet_1٢",
])
def test_subrole_rejects_invalid_bullet_positions(unit_id):
    with pytest.raises(RuntimeError, match="Could not match|Invalid"):
        composer.compose_resume(MASTER, [(unit_id, "Replacement.")])


@pytest.mark.parametrize("unit_id", [
    "resume.acme.platform.bullet_1", "resume.leadership.bullet_1",
])
def test_duplicate_bullet_positions_raise(unit_id):
    with pytest.raises(RuntimeError, match="Duplicate"):
        composer.compose_resume(MASTER_WITH_SECTIONS, [(unit_id, "First."), (unit_id, "Second.")])


def test_duplicate_aliases_for_same_subrole_position_raise():
    with pytest.raises(RuntimeError, match="Duplicate"):
        composer.compose_resume(MASTER, [
            ("resume.acme.platform.bullet_1", "First."),
            ("resume.acme_corp.platform_team.bullet_1", "Second."),
        ])


def test_flat_company_unit_id_matches_via_company_token():
    # resume.acme.bullet_1 tokens are {'acme'} — no sub-role qualifier.
    # Should still match the Acme Platform Team sub-role via company token inheritance.
    out = composer.compose_resume(MASTER, [("resume.acme.bullet_1", "Company-token bullet.")])
    assert "Company-token bullet." in out


MASTER_WITH_SECTIONS = MASTER.replace(
    "## Experience", "## Highlights\n\nA short introduction.\n- Original highlight.\n\n## Experience"
).replace(
    "## Education", "## Leadership\n\nLeadership context.\n- Original mentorship.\n- Original coaching.\n\nClosing context.\n\n## Education"
)


def test_compose_targets_standalone_sections_and_preserves_other_content():
    out = composer.compose_resume(
        MASTER_WITH_SECTIONS,
        [
            ("resume.highlights.bullet_1", "Chosen highlight."),
            ("resume.acme.platform.bullet_1", "Chosen platform bullet."),
            ("resume.leadership.bullet_2", "Chosen coaching."),
            ("resume.leadership.bullet_1", "- Chosen mentorship."),
        ],
    )
    assert "A short introduction.\n- Chosen highlight." in out
    assert "Original highlight." not in out
    assert "Old platform bullet one." not in out
    assert "- Chosen platform bullet.\n- Old platform bullet two." in out
    assert "Old billing bullet." in out
    assert "## Leadership\n\nLeadership context.\n- Chosen mentorship.\n- Chosen coaching.\n\nClosing context." in out
    assert "Original mentorship." not in out
    assert out.index("## Highlights") < out.index("## Experience") < out.index("## Leadership") < out.index("## Education")
    assert out.endswith("## Education\n- Some School\n")


def test_untargeted_standalone_sections_preserve_their_original_text():
    out = composer.compose_resume(MASTER_WITH_SECTIONS, [])
    assert out.split("## Leadership", 1)[1] == MASTER_WITH_SECTIONS.split("## Leadership", 1)[1]
    assert out.split("## Experience", 1)[0] == MASTER_WITH_SECTIONS.split("## Experience", 1)[0]


@pytest.mark.parametrize("unit_id", [
    "resume.leadership.extra.bullet_1", "resume.leadership.bullet_0",
    "resume.leadership.bullet_3", "resume.lead.bullet_1", "resume.summary.bullet_1",
])
def test_standalone_section_rejects_invalid_or_inexact_targets(unit_id):
    with pytest.raises(RuntimeError, match="Could not match|Invalid"):
        composer.compose_resume(MASTER_WITH_SECTIONS, [(unit_id, "Chosen bullet.")])


def test_duplicate_normalized_section_headings_are_ambiguous():
    master = MASTER_WITH_SECTIONS + "\n## LEADERSHIP\n- Another leadership bullet.\n"
    with pytest.raises(RuntimeError, match="Ambiguous section target"):
        composer.compose_resume(master, [("resume.leadership.bullet_1", "Chosen bullet.")])
    assert all("leadership" not in unit_id for unit_id in composer.resume_unit_ids(master))


def test_role_and_standalone_section_collision_is_ambiguous():
    master = MASTER_WITH_SECTIONS.replace("Acme Corp", "Leadership")
    with pytest.raises(RuntimeError, match="Ambiguous role and section target"):
        composer.compose_resume(master, [("resume.leadership.bullet_1", "Chosen bullet.")])
    assert "resume.leadership.bullet_1" not in composer.resume_unit_ids(master)
    assert "resume.leadership.platform_team.bullet_1" in composer.resume_unit_ids(master)


def test_nested_and_empty_sections_are_not_standalone_bullet_targets():
    master = MASTER + "\n## Summary\nProse only.\n\n## Projects\n### Detail\n- Nested bullet.\n\n## ???\n- Unnamed bullet.\n"
    assert composer.resume_unit_ids(master) == (
        "resume.acme_corp.platform_team.bullet_1", "resume.acme_corp.platform_team.bullet_2",
        "resume.acme_corp.billing_team.bullet_1", "resume.education.bullet_1",
    )
    with pytest.raises(RuntimeError, match="Could not match"):
        composer.compose_resume(master, [("resume.projects.bullet_1", "Chosen bullet.")])
    assert "- Nested bullet." in composer.compose_resume(master, [])


def test_resume_unit_ids_are_existing_bullets_in_document_order():
    assert composer.resume_unit_ids(MASTER_WITH_SECTIONS) == (
        "resume.highlights.bullet_1",
        "resume.acme_corp.platform_team.bullet_1", "resume.acme_corp.platform_team.bullet_2",
        "resume.acme_corp.billing_team.bullet_1",
        "resume.leadership.bullet_1", "resume.leadership.bullet_2",
        "resume.education.bullet_1",
    )


def test_resume_unit_ids_exclude_ambiguous_subroles():
    master = MASTER_TWO_SUBROLES.replace("Older Team", "Newer Team")
    assert composer.resume_unit_ids(master) == ("resume.education.bullet_1",)


def test_subrole_without_identity_tokens_does_not_match():
    assert composer.match_subrole("resume.bullet_1", composer.parse_master_resume(MASTER).role_blocks) is None


def test_section_heading_normalization_is_exact():
    master = MASTER_WITH_SECTIONS.replace("## Leadership", "## Leadership & Coaching")
    out = composer.compose_resume(master, [("resume.leadership_coaching.bullet_1", "Chosen leadership.")])
    assert "## Leadership & Coaching\n\nLeadership context.\n- Chosen leadership." in out
    with pytest.raises(RuntimeError, match="Could not match"):
        composer.compose_resume(master, [("resume.coaching_leadership.bullet_1", "Chosen leadership.")])


def test_standalone_section_replacement_preserves_other_bullet_continuations_and_nested_content():
    master = MASTER + """
## Leadership

Independent introduction.
- Original mentorship.
  A wrapped continuation.
and continues without indentation.

  - A nested achievement.
    Its continuation.
- Original coaching.
and continues too.

Independent closing paragraph.

### Community
- Unrelated subsection bullet.
"""
    out = composer.compose_resume(master, [("resume.leadership.bullet_2", "Chosen coaching.")])
    assert "- Chosen coaching." in out
    assert "- Original mentorship.\n  A wrapped continuation.\nand continues without indentation.\n\n  - A nested achievement.\n    Its continuation." in out
    assert "Original coaching." not in out
    assert "Independent introduction." in out
    assert "Independent closing paragraph." in out
    assert "### Community\n- Unrelated subsection bullet." in out
    assert composer.resume_unit_ids(master)[-2:] == (
        "resume.leadership.bullet_1", "resume.leadership.bullet_2",
    )
    assert composer.compose_resume(master, []).split("## Leadership", 1)[1] == master.split("## Leadership", 1)[1]
    first_replaced = composer.compose_resume(master, [("resume.leadership.bullet_1", "Chosen mentorship.")])
    assert "Original mentorship." not in first_replaced
    assert "A wrapped continuation." not in first_replaced
    assert "and continues without indentation." not in first_replaced
    assert "A nested achievement." not in first_replaced
    assert "- Chosen mentorship.\n\n- Original coaching.\nand continues too." in first_replaced

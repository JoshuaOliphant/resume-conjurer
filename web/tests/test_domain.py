# ABOUTME: Unit tests for the pure domain types (the outline helpers in particular).
# ABOUTME: Route/adapter tests cover the rest; these pin the otherwise-uncalled properties.

import pytest

from app.domain import (
    FRAMES,
    Application,
    Evidence,
    Frame,
    Outline,
    OutlineUnit,
    Unit,
    Variant,
    validate_slug,
)


def _outline(frame: str) -> Outline:
    cover = (OutlineUnit("cover_letter.opening", "cover_paragraph", "Open with the scale story"),)
    resume = (OutlineUnit("resume.acme.bullet_1", "resume_bullet", "Lead migration bullet"),)
    return Outline(
        strategic_frame=frame,
        frame_rationale="why this frame",
        company="Acme",
        role_title="Staff Engineer",
        cover_letter_units=cover,
        resume_units=resume,
    )


def test_frame_name_maps_known_key_to_display_name():
    assert _outline("scale").frame_name == FRAMES["scale"] == "Scale"


def test_frame_name_falls_back_to_the_raw_key_when_unknown():
    # The fallback keeps an unexpected frame visible rather than blank.
    assert _outline("bespoke").frame_name == "bespoke"


def test_units_are_cover_letter_then_resume_in_document_order():
    o = _outline("multiplier")
    assert o.units == o.cover_letter_units + o.resume_units
    assert [u.unit_id for u in o.units] == ["cover_letter.opening", "resume.acme.bullet_1"]


# --- validate_slug -----------------------------------------------------------


@pytest.mark.parametrize("slug", ["acme-staff-role", "acme_staff_role", "a", "a1-b2"])
def test_validate_slug_accepts_safe_segments(slug: str):
    validate_slug(slug)  # does not raise


@pytest.mark.parametrize(
    "slug", ["../etc", "a/b", "-leading-hyphen", "", ".", "a" * 100, "UPPER"]
)
def test_validate_slug_rejects_unsafe_segments(slug: str):
    with pytest.raises(ValueError, match="Invalid slug"):
        validate_slug(slug)


# --- Application grounding invariant -----------------------------------------


def _evidence(grounded: bool) -> Evidence:
    return Evidence(id="e1", text="a real quote", source="master-resume.md L1", grounded=grounded)


def _application_with(evidence_items: tuple[Evidence, ...], pool: dict[str, Evidence]) -> Application:
    unit = Unit(
        id="resume.acme.bullet_1",
        kind="resume_bullet",
        label="Bullet",
        context="why it matters",
        variants=[Variant(id="resume.acme.bullet_1#1", text="the bullet text", evidence_items=evidence_items)],
    )
    return Application(
        slug="acme-staff-role",
        company="Acme",
        role="Staff Engineer",
        jd_excerpt="excerpt",
        frame=Frame(name="Scale", rationale="why"),
        units=[unit],
        evidence=pool,
    )


def test_application_accepts_a_grounded_variant_that_matches_the_pool():
    ev = _evidence(grounded=True)
    _application_with((ev,), {ev.id: ev})  # does not raise


def test_application_accepts_an_ungrounded_self_citation_unconditionally():
    # Self-citation fallbacks (grounded=False) don't need to be in the pool at all —
    # the invariant only protects claims presented as verified quotes.
    ev = _evidence(grounded=False)
    _application_with((ev,), {})  # does not raise


def test_application_rejects_a_grounded_variant_absent_from_the_pool():
    ev = _evidence(grounded=True)
    with pytest.raises(ValueError, match="does not match this application's evidence pool"):
        _application_with((ev,), {})


def test_application_rejects_a_grounded_variant_whose_pool_entry_text_differs():
    # Same id, different text: a variant claiming a quote that isn't actually what the
    # pool says is exactly the fabrication this invariant exists to catch.
    ev = _evidence(grounded=True)
    tampered_pool_entry = Evidence(id=ev.id, text="a fabricated quote", source=ev.source)
    with pytest.raises(ValueError, match="does not match this application's evidence pool"):
        _application_with((ev,), {ev.id: tampered_pool_entry})

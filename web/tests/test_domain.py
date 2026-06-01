# ABOUTME: Unit tests for the pure domain types (the outline helpers in particular).
# ABOUTME: Route/adapter tests cover the rest; these pin the otherwise-uncalled properties.

from app.domain import FRAMES, Outline, OutlineUnit


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

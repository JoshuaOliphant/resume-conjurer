# ABOUTME: Tests for the grimoire-checklist linter (regex style checks).
# ABOUTME: Verifies each rule fires and clean text passes.
from pathlib import Path

import lint


def test_em_dash_flagged():
    findings = lint.lint_text("I built a thing — and shipped it.", source=Path("x.md"))
    assert any(f.rule == "em_dash" for f in findings)


def test_filler_word_flagged():
    findings = lint.lint_text("I just shipped it.", source=Path("x.md"))
    assert any(f.rule.startswith("filler:") for f in findings)


def test_first_person_plural_flagged():
    findings = lint.lint_text("We built the platform.", source=Path("x.md"))
    assert any(f.rule == "first_person_plural" for f in findings)


def test_cover_letter_length_flagged():
    text = " ".join(["word"] * 400)
    findings = lint.lint_text(text, source=Path("x.md"), is_cover_letter=True)
    assert any(f.rule == "length" for f in findings)


def test_clean_text_passes():
    findings = lint.lint_text("I architected the migration. I led the team.", source=Path("x.md"))
    assert findings == []


def test_correlative_construction_flagged():
    findings = lint.lint_text("not just fast, it's reliable", source=Path("x.md"))
    assert any(f.rule == "correlative_construction" for f in findings)


def test_ai_generic_opener_flagged():
    findings = lint.lint_text("I am writing to express my interest in this role.", source=Path("x.md"))
    assert any(f.rule == "ai_generic_opener" for f in findings)


def test_self_deprecation_flagged():
    findings = lint.lint_text("I built a small tool to automate the process.", source=Path("x.md"))
    assert any(f.rule == "self_deprecation" for f in findings)


def test_disclaimer_hedge_flagged():
    findings = lint.lint_text("I could be wrong, but this works reliably.", source=Path("x.md"))
    assert any(f.rule == "disclaimer_hedge" for f in findings)


def test_buzzword_flagged():
    findings = lint.lint_text("I am a rockstar engineer who drives synergy.", source=Path("x.md"))
    assert any(f.rule.startswith("buzzword:") for f in findings)


def test_lint_app_dir_routes_cover_letter_and_resume(tmp_path):
    # Write a cover letter over 350 words to trigger the length rule.
    cover_words = " ".join(["achievement"] * 360)
    (tmp_path / "cover_letter.md").write_text(cover_words)
    # Resume is clean and short — no length rule should fire for it.
    (tmp_path / "resume.md").write_text("I led the migration effort.")
    findings = lint.lint_app_dir(tmp_path)
    length_findings = [f for f in findings if f.rule == "length"]
    assert length_findings, "Expected a length finding from cover_letter.md"
    assert all(f.file.name == "cover_letter.md" for f in length_findings), (
        "Length rule should only fire for cover_letter.md, not resume.md"
    )

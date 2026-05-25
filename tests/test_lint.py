# ABOUTME: Tests for the grimoire-checklist linter (regex style checks).
# ABOUTME: Verifies each rule fires and clean text passes.
import lint


def test_em_dash_flagged():
    findings = lint.lint_text("I built a thing — and shipped it.", source=__import__("pathlib").Path("x.md"))
    assert any(f.rule == "em_dash" for f in findings)


def test_filler_word_flagged():
    findings = lint.lint_text("I just shipped it.", source=__import__("pathlib").Path("x.md"))
    assert any(f.rule.startswith("filler:") for f in findings)


def test_first_person_plural_flagged():
    findings = lint.lint_text("We built the platform.", source=__import__("pathlib").Path("x.md"))
    assert any(f.rule == "first_person_plural" for f in findings)


def test_cover_letter_length_flagged():
    text = " ".join(["word"] * 400)
    findings = lint.lint_text(text, source=__import__("pathlib").Path("x.md"), is_cover_letter=True)
    assert any(f.rule == "length" for f in findings)


def test_clean_text_passes():
    findings = lint.lint_text("I architected the migration. I led the team.", source=__import__("pathlib").Path("x.md"))
    assert findings == []

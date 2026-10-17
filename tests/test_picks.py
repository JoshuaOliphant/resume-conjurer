# ABOUTME: Tests for writing curation choices from JSON into variants.md pick checkboxes.
# ABOUTME: Covers validation of unit ids and variant numbers, partial curation, and the CLI exit codes.
import json

import pytest

import picks
import stitch

VARIANTS_MD = """# Conjurer Variants

## Unit: cover_letter.opening
<!-- conjurer:unit id=cover_letter.opening -->
*opening paragraph*

### Variant 1: master-resume.md L3

Acme's platform team is doing what I do every day.

- [ ] Pick

### Variant 2: master-resume.md L3

I have spent five years on platform reliability.

- [ ] Pick

## Unit: resume.acme.platform.bullet_1
<!-- conjurer:unit id=resume.acme.platform.bullet_1 -->
*platform bullet*

### Variant 1: master-resume.md L8

- Architected the platform migration.

- [x] Pick

### Variant 2: master-resume.md L8

- Led the platform migration.

- [ ] Pick
"""


def picked(text: str) -> dict[str, int]:
    return {u.unit_id: v.n for u in stitch.parse_variants_md(text) for v in u.variants if v.picked}


def test_apply_picks_checks_exactly_the_chosen_variant():
    text = picks.apply_picks(VARIANTS_MD, {"cover_letter.opening": 2, "resume.acme.platform.bullet_1": 2})
    assert picked(text) == {"cover_letter.opening": 2, "resume.acme.platform.bullet_1": 2}
    assert text.endswith("- [x] Pick\n")


def test_apply_picks_leaves_unnamed_units_alone():
    text = picks.apply_picks(VARIANTS_MD, {"cover_letter.opening": 1})
    assert picked(text) == {"cover_letter.opening": 1, "resume.acme.platform.bullet_1": 1}


def test_apply_picks_keeps_a_missing_trailing_newline_missing():
    assert not picks.apply_picks(VARIANTS_MD.rstrip("\n"), {}).endswith("\n")


def test_apply_picks_rejects_unknown_unit():
    with pytest.raises(ValueError, match="Unknown unit: resume.globex.bullet_1"):
        picks.apply_picks(VARIANTS_MD, {"resume.globex.bullet_1": 1})


@pytest.mark.parametrize("n", [3, "1", True])
def test_apply_picks_rejects_a_variant_the_unit_does_not_have(n):
    with pytest.raises(ValueError, match="has no Variant"):
        picks.apply_picks(VARIANTS_MD, {"cover_letter.opening": n})


def test_pick_lines_before_any_unit_are_untouched():
    text = "- [ ] Pick\n" + VARIANTS_MD
    assert picks.apply_picks(text, {"cover_letter.opening": 1}).startswith("- [ ] Pick\n")


def write_app(tmp_path, choices: dict) -> tuple:
    app = tmp_path / "app"
    app.mkdir()
    (app / "variants.md").write_text(VARIANTS_MD)
    curation = tmp_path / "curation.json"
    curation.write_text(json.dumps({"picks": choices, "rationale": {"cover_letter.opening": "why"}}))
    return app, curation


def test_main_writes_picks_and_reports(tmp_path, capsys):
    app, curation = write_app(tmp_path, {"cover_letter.opening": 2, "resume.acme.platform.bullet_1": 1})
    picks.main([str(app), str(curation)])
    assert picked((app / "variants.md").read_text()) == {
        "cover_letter.opening": 2,
        "resume.acme.platform.bullet_1": 1,
    }
    assert "Marked 2 picks" in capsys.readouterr().out


def test_main_exits_1_naming_units_still_unpicked(tmp_path, capsys):
    app, curation = write_app(tmp_path, {"resume.acme.platform.bullet_1": 2})
    with pytest.raises(SystemExit) as exc:
        picks.main([str(app), str(curation)])
    assert exc.value.code == 1
    assert "Units with no pick: cover_letter.opening" in capsys.readouterr().err

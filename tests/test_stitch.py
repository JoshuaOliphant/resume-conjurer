# ABOUTME: Tests for stitching picked variants into cover_letter.md and resume.md.
# ABOUTME: Verifies variants.md parsing, pick collection, and final-doc assembly.
import stitch
import pytest

VARIANTS_MD = """# Conjurer Variants

## Unit: cover_letter.opening
<!-- conjurer:unit id=cover_letter.opening -->
*opening paragraph*

### Variant 1: master-resume.md L3

Acme's platform team is doing what I do every day.

*Axis: company-anchored*

- [x] Pick

### Variant 2: master-resume.md L3

I have spent five years on platform reliability.

*Axis: experience-anchored*

- [ ] Pick

## Unit: resume.acme.platform.bullet_1
<!-- conjurer:unit id=resume.acme.platform.bullet_1 -->
*platform bullet*

### Variant 1: master-resume.md L8

- Architected the platform migration.

*Axis: ownership*

- [x] Pick
"""

MASTER = """# Master Resume

## Experience

### Acme Corp — Senior Engineer

**Platform Team** — 2021 to present
- Old bullet.
"""


def test_parse_and_collect(tmp_path):
    units = stitch.parse_variants_md(VARIANTS_MD)
    assert [u.unit_id for u in units] == ["cover_letter.opening", "resume.acme.platform.bullet_1"]
    cover, resume = stitch.collect_picks(units)
    assert cover == ["Acme's platform team is doing what I do every day."]
    assert resume == [("resume.acme.platform.bullet_1", "- Architected the platform migration.")]


def test_stitch_app_dir_writes_docs(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "variants.md").write_text(VARIANTS_MD)
    master = tmp_path / "master-resume.md"
    master.write_text(MASTER)
    cover_path, resume_path = stitch.stitch_app_dir(app, master_resume_path=master)
    assert "Acme's platform team" in cover_path.read_text()
    assert "Architected the platform migration." in resume_path.read_text()


def test_missing_pick_raises(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    no_pick = VARIANTS_MD.replace("- [x] Pick", "- [ ] Pick")
    (app / "variants.md").write_text(no_pick)
    master = tmp_path / "master-resume.md"
    master.write_text(MASTER)
    with pytest.raises(ValueError):
        stitch.stitch_app_dir(app, master_resume_path=master)


def test_overwrite_guard_raises_when_output_exists(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "variants.md").write_text(VARIANTS_MD)
    master = tmp_path / "master-resume.md"
    master.write_text(MASTER)
    # First stitch succeeds and writes cover_letter.md.
    stitch.stitch_app_dir(app, master_resume_path=master)
    # Second stitch without overwrite=True must raise.
    with pytest.raises(RuntimeError):
        stitch.stitch_app_dir(app, master_resume_path=master, overwrite=False)


def test_multiple_picks_in_one_unit_raises(tmp_path):
    two_picks = VARIANTS_MD.replace(
        "- [ ] Pick\n\n## Unit: resume.acme.platform.bullet_1",
        "- [x] Pick\n\n## Unit: resume.acme.platform.bullet_1",
    )
    app = tmp_path / "app"
    app.mkdir()
    (app / "variants.md").write_text(two_picks)
    master = tmp_path / "master-resume.md"
    master.write_text(MASTER)
    with pytest.raises(ValueError):
        stitch.stitch_app_dir(app, master_resume_path=master)


def test_missing_variants_md_raises(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    master = tmp_path / "master-resume.md"
    master.write_text(MASTER)
    with pytest.raises(FileNotFoundError):
        stitch.stitch_app_dir(app, master_resume_path=master)


def test_variants_md_with_no_unit_markers_raises(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "variants.md").write_text("# Just a heading\n\nNo units here.\n")
    master = tmp_path / "master-resume.md"
    master.write_text(MASTER)
    with pytest.raises(ValueError):
        stitch.stitch_app_dir(app, master_resume_path=master)


def test_nonexistent_master_resume_raises_with_path(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "variants.md").write_text(VARIANTS_MD)
    missing = tmp_path / "does-not-exist.md"
    with pytest.raises(FileNotFoundError, match=str(missing)):
        stitch.stitch_app_dir(app, master_resume_path=missing)

# ABOUTME: Tests for the curation-time glossary leak check over an application's variants.md.
# ABOUTME: Drives leaks.main against a temporary workspace with a real grimoire and variants file.
import pytest

import leaks

GRIMOIRE = """# Grimoire

## Glossary

| Internal term | Aliases | Public description |
|---|---|---|
| MailAPI | Mail API, mail-api | transactional email API |
| sn-superpowers | | internal developer platform |
| Hermes | | |
"""

VARIANTS_MD = """# Conjurer Variants

## Unit: cover_letter.opening
<!-- conjurer:unit id=cover_letter.opening -->
*opening paragraph*

### Variant 1: master-resume.md L8

I led the transactional email API through its busiest year.

- [ ] Pick

### Variant 2: master-resume.md L8

I led the mail-api through its busiest year.

- [ ] Pick

## Unit: resume.northwind.billing.bullet_1
<!-- conjurer:unit id=resume.northwind.billing.bullet_1 -->
*bullet*

### Variant 1: master-resume.md L9

- Moved MailAPI onto sn-superpowers.

- [ ] Pick
"""


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "grimoire.md").write_text(GRIMOIRE)
    app_dir = tmp_path / "applications" / "globex-staff-platform"
    app_dir.mkdir(parents=True)
    (app_dir / "variants.md").write_text(VARIANTS_MD)
    return tmp_path, app_dir


def test_main_prints_each_leaking_variant_with_its_internal_terms(workspace, capsys):
    root, app_dir = workspace

    with pytest.raises(SystemExit, match="1"):
        leaks.main([str(app_dir), str(root)])

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "cover_letter.opening #2\tMailAPI",
        "resume.northwind.billing.bullet_1 #1\tMailAPI, sn-superpowers",
    ]
    assert captured.err == "Glossary line 9: missing public description\n"


def test_main_without_leaks_says_so_and_exits_cleanly(workspace, capsys):
    root, app_dir = workspace
    (root / "grimoire.md").write_text("# Grimoire\n\n## Voice\n\nPlain.\n")

    leaks.main([str(app_dir), str(root)])

    assert capsys.readouterr() == ("No glossary leaks.\n", "")

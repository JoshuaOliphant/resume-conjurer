# ABOUTME: Tests for the /grimoire glossary checks: the Glossary table parses, and which bullets name a term.
# ABOUTME: Drives glossary_check.main against a temporary workspace with a real grimoire and master resume.
import pytest

import glossary_check

GRIMOIRE = """# Grimoire

## Glossary

| Internal term | Aliases | Public description |
|---|---|---|
| MailAPI | Mail API, mail-api | transactional email API |
| syseng-oncall | | AI on-call assistant |
"""

MASTER_RESUME = """# Sam Example

## Experience

### Initech — Senior Software Engineer

**Messaging Platform** — 2021 to present
- Built MailAPI, the transactional email service, on Kafka and Kubernetes.
- Migrated 14 product teams onto the mail-api client library.
- Created syseng-oncall, cutting mean time to acknowledge by half.
- Wrote the MailAPIClient wrapper.
"""


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "grimoire.md").write_text(GRIMOIRE)
    (tmp_path / "master-resume.md").write_text(MASTER_RESUME)
    return tmp_path


def test_rows_counts_the_glossary_entries_of_a_clean_table(workspace, capsys):
    glossary_check.main(["rows", str(workspace)])

    assert capsys.readouterr() == ("2 glossary entries\n", "")


def test_rows_fails_on_a_malformed_row_and_names_its_line(workspace, capsys):
    (workspace / "grimoire.md").write_text(GRIMOIRE + "| Hermes | | |\n")

    with pytest.raises(SystemExit, match="1"):
        glossary_check.main(["rows", str(workspace)])

    assert capsys.readouterr() == (
        "2 glossary entries\n",
        "Glossary line 9: missing public description\n",
    )


def test_bullets_prints_each_resume_line_naming_the_term_or_an_alias(workspace, capsys):
    glossary_check.main(["bullets", str(workspace), "MailAPI"])

    assert capsys.readouterr() == (
        "L8\t- Built MailAPI, the transactional email service, on Kafka and Kubernetes.\n"
        "L9\t- Migrated 14 product teams onto the mail-api client library.\n",
        "",
    )


def test_bullets_rejects_a_term_missing_from_the_glossary(workspace, capsys):
    with pytest.raises(SystemExit, match="2"):
        glossary_check.main(["bullets", str(workspace), "Ledgerline"])

    assert "Ledgerline is not an internal term in the Glossary" in capsys.readouterr().err

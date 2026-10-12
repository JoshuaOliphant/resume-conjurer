# ABOUTME: Tests for the grimoire glossary: parsing its table and finding glossary leaks in text.
# ABOUTME: Covers well-formed and malformed rows, section bounds, and whole-word term matching.
import pytest

from glossary import GlossaryEntry, entries_named, evidence_rows, parse_glossary

GRIMOIRE = """# Grimoire

## Voice

MailAPI is fine to say in this section; it is not the glossary.

## Glossary

Each internal term maps to what an outside reader understands.

| Internal term | Aliases | Public description |
|---|---|---|
| MailAPI | Mail API, mail-api | transactional email API |
| sn-superpowers | | internal developer platform |
| | Hermes | message relay |
| Mailscan | Mail Scan | inbound mail scanning service |
| Kraken | kraken-ops |  |
| Orphan | only two cells |

## Anti-Patterns

| Internal term | Aliases | Public description |
|---|---|---|
| NotGlossary | | outside the section |
"""

MAILAPI = GlossaryEntry("MailAPI", ("Mail API", "mail-api"), "transactional email API")
SUPERPOWERS = GlossaryEntry("sn-superpowers", (), "internal developer platform")
MAILSCAN = GlossaryEntry("Mailscan", ("Mail Scan",), "inbound mail scanning service")

ENTRIES, WARNINGS = parse_glossary(GRIMOIRE)


def test_parse_glossary_yields_internal_term_aliases_and_public_description() -> None:
    assert ENTRIES[0] == MAILAPI


def test_parse_glossary_loads_every_well_formed_row_of_the_section_only() -> None:
    assert ENTRIES == [MAILAPI, SUPERPOWERS, MAILSCAN]


def test_parse_glossary_warns_with_the_line_number_of_each_malformed_row() -> None:
    assert WARNINGS == [
        "Glossary line 15: missing internal term",
        "Glossary line 17: missing public description",
        "Glossary line 18: expected 3 columns, found 2",
    ]


@pytest.mark.parametrize(
    "grimoire",
    [
        pytest.param("# Grimoire\n\n## Voice\n\nPlain.\n", id="no-glossary-section"),
        pytest.param("## Glossary\n\nNothing mapped yet.\n", id="section-without-table"),
        pytest.param("## Glossary\n\n| Internal term | Aliases | Public description |\n|---|---|---|\n", id="header-only"),
    ],
)
def test_parse_glossary_without_rows_returns_nothing(grimoire: str) -> None:
    assert parse_glossary(grimoire) == ([], [])


def test_parse_glossary_reads_rows_without_outer_pipes_and_with_a_lowercase_heading() -> None:
    grimoire = "## glossary\nInternal term | Aliases | Public description\n:--|:-:|--:\nMailAPI | Mail API, mail-api | transactional email API\n"
    assert parse_glossary(grimoire) == ([MAILAPI], [])


def test_parse_glossary_reads_a_separator_only_alias_as_no_alias() -> None:
    entries, warnings = parse_glossary("## Glossary\n| sn-superpowers | - , — | internal developer platform |\n")
    assert (entries, warnings) == ([SUPERPOWERS], [])
    assert entries_named("I led a clean project.", entries) == []


def test_parse_glossary_warns_on_an_internal_term_with_no_letters_or_digits() -> None:
    assert parse_glossary("## Glossary\n| - | | message relay |\n") == (
        [],
        ["Glossary line 2: internal term has no letters or digits"],
    )


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Shipped MailAPI to every tenant.", id="internal-term"),
        pytest.param("Shipped mailapi to every tenant.", id="lowercase"),
        pytest.param("Shipped the Mail API to every tenant.", id="spaced-alias"),
        pytest.param("Shipped mail-api to every tenant.", id="hyphenated-alias"),
        pytest.param("Shipped MAIL - API.", id="extra-separators"),
        pytest.param("(MailAPI)", id="punctuation-bounded"),
    ],
)
def test_entries_named_reports_the_internal_term_for_every_form(text: str) -> None:
    assert entries_named(text, [MAILAPI]) == [MAILAPI]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Built the Mailscanner pipeline.", id="term-inside-longer-word"),
        pytest.param("Built the preMailscan step.", id="term-after-word-characters"),
        pytest.param("Built the mail scanner.", id="alias-inside-longer-word"),
        pytest.param("Built a transactional email API.", id="public-description-only"),
    ],
)
def test_entries_named_respects_word_boundaries(text: str) -> None:
    assert entries_named(text, [MAILAPI, MAILSCAN]) == []


def test_entries_named_lists_each_entry_once_in_glossary_order() -> None:
    text = "Moved mail-api and MailAPI onto sn-superpowers, then Mailscan onto MailAPI."
    assert entries_named(text, [MAILAPI, SUPERPOWERS, MAILSCAN]) == [MAILAPI, SUPERPOWERS, MAILSCAN]


def test_evidence_rows_state_each_used_term_as_its_public_description_in_glossary_order() -> None:
    cited = ["- Moved Mailscan onto the new cluster.", "- Ran the mail-api on-call rotation."]
    assert evidence_rows(cited, [MAILAPI, SUPERPOWERS, MAILSCAN]) == [
        "MailAPI is a transactional email API",
        "Mailscan is a inbound mail scanning service",
    ]


@pytest.mark.parametrize(
    ("cited", "entries"),
    [
        pytest.param(["- Built a transactional email API."], [MAILAPI], id="no-internal-term"),
        pytest.param(["- Moved MailAPI onto the new cluster."], [], id="no-glossary"),
        pytest.param([], [MAILAPI], id="no-cited-lines"),
    ],
)
def test_evidence_rows_are_empty_when_the_cited_lines_use_no_glossary_term(cited, entries) -> None:
    assert evidence_rows(cited, entries) == []

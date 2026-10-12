# ABOUTME: Tests for the citation grammar shared by the plugin scripts and the web app.
# ABOUTME: Covers pooling master-resume.md and evidence.md lines and resolving citation strings.
import pytest

from citations import CitedLine, is_well_formed_citation, pool_lines, resolve_citation

MASTER_RESUME = """# Jordan Rivera

## Experience

### Northwind

**Billing Platform** 2021 to present
- Led the billing migration.
- Rolled the backbone out across three regions.
- Owned the billing on-call rotation.
"""

EVIDENCE = """# Evidence

## Project receipts

- Billing migration: invoice generation ~40s to under 2s.
- On-call: paging volume cut 60%.
- Kubernetes appears only in the service template.
## Other
- Cost: spend reduced 35%.
See the billing retrospective for context.
"""

LINES = pool_lines(MASTER_RESUME, EVIDENCE)


def test_pool_lines_keys_non_blank_lines_by_file_and_line_number() -> None:
    assert LINES["master-resume.md L1"] == "# Jordan Rivera"
    assert LINES["master-resume.md L8"] == "- Led the billing migration."
    assert LINES["evidence.md L5"] == "- Billing migration: invoice generation ~40s to under 2s."
    assert "master-resume.md L2" not in LINES
    assert list(LINES)[:2] == ["master-resume.md L1", "master-resume.md L3"]
    assert list(LINES)[-1] == "evidence.md L10"


@pytest.mark.parametrize(
    ("citation", "expected_ids"),
    [
        ("master-resume.md L8", ["master-resume.md L8"]),
        ("master-resume.md L8; master-resume.md L9", ["master-resume.md L8", "master-resume.md L9"]),
        ("master-resume.md L8, L9", ["master-resume.md L8", "master-resume.md L9"]),
        ("master-resume.md L8-L9", ["master-resume.md L8", "master-resume.md L9"]),
        ("master-resume.md L6–8", ["master-resume.md L7", "master-resume.md L8"]),
        ("evidence.md L6", ["evidence.md L6"]),
        ("evidence.md - billing migration", ["evidence.md L5"]),
        ("evidence.md - On-call", ["evidence.md L6"]),
        ("evidence.md - Project receipts", ["evidence.md L5", "evidence.md L6", "evidence.md L7"]),
        ("evidence.md - Other", ["evidence.md L9"]),
        ("master-resume.md L8; evidence.md - cost", ["master-resume.md L8", "evidence.md L9"]),
        ("master-resume.md L8, evidence.md - cost", ["master-resume.md L8", "evidence.md L9"]),
    ],
    ids=[
        "single-line",
        "semicolon-list",
        "shorthand-line-list",
        "range-with-L",
        "en-dash-range-skips-blank-line",
        "evidence-line",
        "evidence-bullet-label",
        "evidence-label-case-insensitive",
        "evidence-heading-expands-to-its-bullets",
        "evidence-heading-skips-prose-lines",
        "mixed-files",
        "comma-before-file",
    ],
)
def test_resolve_citation_grounds_every_pooled_line(citation: str, expected_ids: list[str]) -> None:
    assert resolve_citation(citation, LINES) == [CitedLine(id, True) for id in expected_ids]
    assert is_well_formed_citation(citation)


@pytest.mark.parametrize(
    ("citation", "well_formed"),
    [
        ("master-resume.md", False),
        ("master-resume.md L999", True),
        ("master-resume.md L9-8", False),
        ("evidence.md - hobbies", True),
        ("master-resume.md - billing", False),
        ("notes.md L3", False),
        ("", False),
    ],
    ids=[
        "no-line",
        "missing-line",
        "reversed-range",
        "unknown-label",
        "label-outside-evidence-md",
        "unknown-file",
        "empty",
    ],
)
def test_resolve_citation_keeps_unresolvable_reference_ungrounded(citation: str, well_formed: bool) -> None:
    assert resolve_citation(citation, LINES) == [CitedLine(citation, False)]
    assert is_well_formed_citation(citation) == well_formed


def test_resolve_citation_grounds_what_it_can_in_a_partial_list() -> None:
    assert resolve_citation("master-resume.md L8; notes.md", LINES) == [
        CitedLine("master-resume.md L8", True),
        CitedLine("notes.md", False),
    ]


def test_bare_line_without_a_preceding_file_stays_ungrounded() -> None:
    assert resolve_citation("L8", LINES) == [CitedLine("L8", False)]
    assert not is_well_formed_citation("L8")
    assert not is_well_formed_citation("master-resume.md L0")

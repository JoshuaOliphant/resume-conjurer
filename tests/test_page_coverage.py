# ABOUTME: Tests the page coverage check: fit.json requirements traced through to the stitched resume.md.
# ABOUTME: Covers verbatim master lines, picked variants, reworded picks, missing requirements, and the CLI.
import json

import pytest

import page_coverage

MASTER = """# Jane Doe

## Experience
- Built a Kafka pipeline for billing.
- Ran the on-call rotation for payments.
- Wrote the deploy standards the team adopted.
"""

VARIANTS = """# Conjurer Variants

## Unit: resume.acme.bullet_2
<!-- conjurer:unit id=resume.acme.bullet_2 -->

### Variant 1: master-resume.md L5

- Owned on-call for the payments service.

- [x] Pick

## Unit: resume.acme.bullet_3
<!-- conjurer:unit id=resume.acme.bullet_3 -->

### Variant 1: master-resume.md L6

- Set deployment standards for the whole team.

- [x] Pick

## Unit: resume.acme.bullet_9
<!-- conjurer:unit id=resume.acme.bullet_9 -->

### Variant 1: master-resume.md L6

- Never picked.

- [ ] Pick

## Unit: cover_letter.opening
<!-- conjurer:unit id=cover_letter.opening -->

### Variant 1: master-resume.md L4

I built a Kafka pipeline.

- [x] Pick
"""

PAGE = """# Jane Doe

## Experience
- Built a **Kafka** pipeline for billing.
- Owned on-call for the payments service.
- Wrote deploy standards, reworded by hand.
"""


def fit(*requirements):
    return {"requirements": [
        {"requirement": text, "core": core, "status": status, "evidence": evidence}
        for text, core, status, evidence in requirements
    ]}


FIT = fit(
    ("Kafka", True, "met", "master-resume.md L4"),
    ("On-call", True, "partial", "master-resume.md L5"),
    ("Standards", False, "met", "master-resume.md L6"),
    ("Go", False, "missing", ""),
)


def lines():
    return page_coverage.pool_lines(MASTER, "")


def test_assess_traces_verbatim_lines_picks_and_rewordings():
    results = page_coverage.assess(FIT, PAGE, lines(), VARIANTS)
    assert [(r.requirement, r.status, r.evidence) for r in results] == [
        ("Kafka", "shown", ("master-resume.md L4",)),
        ("On-call", "shown", ("master-resume.md L5",)),
        ("Standards", "reworded", ("master-resume.md L6",)),
        ("Go", "missing", ()),
    ]


def test_evidence_left_off_the_page_is_not_shown():
    page = PAGE.replace("- Built a **Kafka** pipeline for billing.\n", "")
    [kafka, *_] = page_coverage.assess(FIT, page, lines(), None)
    assert kafka.status == "not_shown"


def test_cover_letter_picks_do_not_count():
    page = "I built a Kafka pipeline.\n"
    [kafka, *_] = page_coverage.assess(FIT, page, lines(), VARIANTS)
    assert kafka.status == "not_shown"


def test_non_dict_fit_is_rejected():
    with pytest.raises(ValueError, match="needs a `requirements` list"):
        page_coverage.assess([], PAGE, lines(), None)


def test_render():
    text = page_coverage.render(page_coverage.assess(FIT, PAGE.replace("Built a **Kafka**", "Built a"), lines(), VARIANTS))
    assert text.splitlines() == [
        "Coverage: 1 of 3 supported requirements show their evidence on the page",
        "- not shown: Kafka (evidence: master-resume.md L4)",
        "- reworded after stitching, check by eye: Standards (evidence: master-resume.md L6)",
        "- no evidence, not a wording fix: Go",
    ]


def _workspace(tmp_path, page=PAGE, fit_data=FIT, evidence=None, variants=VARIANTS):
    (tmp_path / "master-resume.md").write_text(MASTER)
    app = tmp_path / "applications" / "acme"
    app.mkdir(parents=True)
    if page is not None:
        (app / "resume.md").write_text(page)
    if fit_data is not None:
        (app / "fit.json").write_text(fit_data if isinstance(fit_data, str) else json.dumps(fit_data))
    if evidence is not None:
        (app / "evidence.md").write_text(evidence)
    if variants is not None:
        (app / "variants.md").write_text(variants)
    return app


def test_cli_exits_0_when_everything_supported_is_traced(tmp_path, capsys):
    app = _workspace(tmp_path, evidence="- extra\n")
    page_coverage.main([str(app), str(tmp_path)])
    assert capsys.readouterr().out.startswith("Coverage: 2 of 3")


def test_cli_exits_1_when_evidence_is_not_shown(tmp_path, capsys):
    app = _workspace(tmp_path, page=PAGE.replace("Built a **Kafka**", "Built a"), variants=None)
    with pytest.raises(SystemExit, match="1"):
        page_coverage.main([str(app), str(tmp_path)])
    assert "- not shown: Kafka" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"page": None}, "needs resume.md and fit.json"),
        ({"fit_data": None}, "needs resume.md and fit.json"),
        ({"fit_data": "{not json"}, "fit.json:"),
        ({"fit_data": {"requirements": []}}, "fit.json: fit.json needs"),
    ],
)
def test_cli_exits_2_on_missing_or_malformed_input(tmp_path, capsys, kwargs, message):
    app = _workspace(tmp_path, **kwargs)
    with pytest.raises(SystemExit, match="2"):
        page_coverage.main([str(app), str(tmp_path)])
    assert message in capsys.readouterr().err


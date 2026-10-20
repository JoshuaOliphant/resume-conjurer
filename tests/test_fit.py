# ABOUTME: Tests for fast mode's fit gate over a fit.json assessment of the JD's must-have requirements.
# ABOUTME: Covers the stop rule, demotion of uncited claims to missing, fit.json validation, and CLI exit codes.
import json

import pytest

import fit

MASTER_RESUME = """# Jane Doe

## Experience

- Built LLM agents that triage on-call incidents.
- Ran Kubernetes platforms for hundreds of developers.
- Wrote Python services with test-driven development.
"""

LINES = fit.pool_lines(MASTER_RESUME, "")


def req(text: str, status: str, core: bool = True, evidence: str = "master-resume.md L5") -> dict:
    return {"requirement": text, "core": core, "status": status, "evidence": evidence}


# Shaped like the Cohere run: the role's central work (training software, ML frameworks,
# distributed training) has no evidence; only the platform half is covered.
POOR_FIT = [
    req("Write software for training models", "missing", evidence=""),
    req("JAX, PyTorch, or XLA/MLIR", "missing", evidence=""),
    req("Debug large-scale distributed training", "missing", evidence=""),
    req("Tools that accelerate research and LLM training", "partial"),
    req("Strong Python and test-driven development", "met", core=False, evidence="master-resume.md L7"),
    req("Kubernetes and Ray training infrastructure", "partial", core=False, evidence="master-resume.md L6"),
]

# Shaped like the Docker run: the central work is covered, with staff-level gaps around it.
STRONG_FIT = [
    req("Production LLM agents and AI developer tools", "met"),
    req("Platforms other teams rely on", "met", evidence="master-resume.md L6"),
    req("Technical leadership on production systems", "partial"),
    req("Go, Rust, Java, or Python", "met", core=False, evidence="master-resume.md L7"),
    req("Mentoring experienced engineers", "missing", core=False, evidence=""),
    req("GitOps deployment patterns", "missing", core=False, evidence=""),
]


def verdict_for(items: list[dict]) -> fit.Verdict:
    return fit.judge(fit.parse_requirements({"requirements": items}, LINES))


def test_poor_fit_stops_on_missing_core_requirements():
    verdict = verdict_for(POOR_FIT)
    assert not verdict.passed
    assert [r.text for r in verdict.core_missing] == [
        "Write software for training models",
        "JAX, PyTorch, or XLA/MLIR",
        "Debug large-scale distributed training",
    ]


def test_strong_fit_passes_despite_non_core_gaps():
    verdict = verdict_for(STRONG_FIT)
    assert verdict.passed
    assert verdict.coverage == pytest.approx(3.5 / 6)
    assert [r.text for r in verdict.other_missing] == ["Mentoring experienced engineers", "GitOps deployment patterns"]


def test_low_coverage_stops_even_when_core_is_mostly_covered():
    items = [
        req("Core work", "met"),
        req("Second core ask", "partial"),
        req("Extra one", "missing", core=False, evidence=""),
        req("Extra two", "missing", core=False, evidence=""),
    ]
    verdict = verdict_for(items)
    assert verdict.coverage == pytest.approx(1.5 / 4)
    assert not verdict.passed


def test_half_the_core_missing_stops():
    items = [req("Core one", "met"), req("Core two", "missing", evidence=""), req("Other", "met", core=False)]
    assert not verdict_for(items).passed


def test_claim_without_grounded_evidence_counts_as_missing():
    items = [
        req("Core one", "met"),
        req("Core two", "met", evidence="master-resume.md L99"),
        req("Core three", "partial", evidence=""),
        req("Core four", "met", evidence=None),
    ]
    verdict = verdict_for(items)
    assert [r.text for r in verdict.ungrounded] == ["Core two", "Core three", "Core four"]
    assert not verdict.passed


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "requirements"),
        ({"requirements": "none"}, "requirements"),
        ({"requirements": [req("a", "met")] * 2}, "3 to 12"),
        ({"requirements": [req("a", "met")] * 13}, "3 to 12"),
        ({"requirements": [req("a", "met"), req("b", "met"), "c"]}, "Requirement 3 is not an object"),
        ({"requirements": [req("a", "met"), req("b", "met"), req(" ", "met")]}, "no `requirement` text"),
        ({"requirements": [req("a", "met"), req("b", "met"), {**req("c", "met"), "core": "yes"}]}, "`core`"),
        ({"requirements": [req("a", "met"), req("b", "met"), req("c", "strong")]}, "'strong'"),
        ({"requirements": [req("a", "met", core=False)] * 3}, "no requirement as core"),
    ],
)
def test_parse_requirements_rejects_malformed_fit_json(data, message):
    with pytest.raises(ValueError, match=message):
        fit.parse_requirements(data, LINES)


def test_render_names_every_gap():
    text = fit.render(verdict_for([*POOR_FIT, req("Uncited", "met", core=False, evidence="")]))
    assert text.splitlines() == [
        "Fit: stop (coverage 0.29, 3 of 4 core requirements missing)",
        "- core, missing: Write software for training models",
        "- core, missing: JAX, PyTorch, or XLA/MLIR",
        "- core, missing: Debug large-scale distributed training",
        "- missing: Uncited",
        "- no grounded evidence cited, counted missing: Uncited",
    ]


def write_app(tmp_path, items, evidence: str | None = None):
    workspace = tmp_path / "ws"
    app = workspace / "applications" / "acme-staff"
    app.mkdir(parents=True)
    (workspace / "master-resume.md").write_text(MASTER_RESUME)
    (app / "fit.json").write_text(json.dumps({"requirements": items}) if isinstance(items, list) else items)
    if evidence is not None:
        (app / "evidence.md").write_text(evidence)
    return app, workspace


def test_main_passes_with_exit_0(tmp_path, capsys):
    app, workspace = write_app(tmp_path, STRONG_FIT)
    fit.main([str(app), str(workspace)])
    assert capsys.readouterr().out.startswith("Fit: pass (coverage 0.58, 0 of 3 core requirements missing)")


def test_main_stops_with_exit_1(tmp_path, capsys):
    app, workspace = write_app(tmp_path, POOR_FIT)
    with pytest.raises(SystemExit) as exc:
        fit.main([str(app), str(workspace)])
    assert exc.value.code == 1
    assert capsys.readouterr().out.startswith("Fit: stop")


def test_main_grounds_citations_in_evidence_md(tmp_path, capsys):
    items = [req(f"Core {n}", "met", evidence="evidence.md L3") for n in range(3)]
    app, workspace = write_app(tmp_path, items, evidence="# Evidence\n\n- Shipped an MCP server.\n")
    fit.main([str(app), str(workspace)])
    assert "Fit: pass" in capsys.readouterr().out


@pytest.mark.parametrize("content", ["not json", json.dumps({"requirements": []})])
def test_main_exits_2_on_malformed_fit_json(tmp_path, capsys, content):
    app, workspace = write_app(tmp_path, content)
    with pytest.raises(SystemExit) as exc:
        fit.main([str(app), str(workspace)])
    assert exc.value.code == 2
    assert capsys.readouterr().err.startswith("fit.json: ")

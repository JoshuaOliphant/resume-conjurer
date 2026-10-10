# ABOUTME: Tests for FsWorkspaceRepository — the filesystem workspace adapter.
# ABOUTME: Round-trips outline.json and variants.md against a tmp copy of the fixture workspace.

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import get_args

import jsonschema
import pytest

import citations  # on sys.path once app.adapters.workspace_fs is imported
import verify
from app.adapters.generation_fake import FakeGenerationPort
from app.adapters.verification_fake import NoVerificationPort
from app.adapters.workspace_fs import FsWorkspaceRepository, resolve_citation
from app.domain import (
    Evidence,
    Outline,
    OutlineUnit,
    Support,
    SupportVerdict,
    Unit,
    Variant,
)
from app.metrics import CallMetrics, RunMetrics, StepMetrics
from app.runs import RunManager
from app.schemas import SUPPORT_SCHEMA

SLUG = "globex-staff-platform"
FIXTURE_WORKSPACE = Path(__file__).parent / "fixtures" / "workspace"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A writable copy of the committed fixture workspace."""
    root = tmp_path / "workspace"
    shutil.copytree(FIXTURE_WORKSPACE, root)
    return root


@pytest.fixture
def repo(workspace: Path) -> FsWorkspaceRepository:
    return FsWorkspaceRepository(workspace)


def _sample_outline() -> Outline:
    return Outline(
        strategic_frame="multiplier",
        frame_rationale="Globex is a platform company; lead with leverage over many teams.",
        company="Globex",
        role_title="Staff Platform Engineer",
        cover_letter_units=(
            OutlineUnit(
                unit_id="cover_letter.opening",
                kind="cover_paragraph",
                description="Open on the platform migration as the proof of leverage.",
            ),
            OutlineUnit(
                unit_id="cover_letter.evidence",
                kind="cover_paragraph",
                description="Name the reliability and adoption receipts.",
            ),
        ),
        resume_units=(
            OutlineUnit(
                unit_id="resume.northwind.billing.bullet_1",
                kind="resume_bullet",
                description="Surface the monolith-to-events migration.",
            ),
        ),
    )


# --- load_inputs -----------------------------------------------------------


def test_load_inputs_reads_all_sources(repo: FsWorkspaceRepository) -> None:
    inputs = repo.load_inputs(SLUG)
    assert "calm under load" in inputs.master_resume
    assert "Staff Platform Engineer" in inputs.jd
    assert "Every generated bullet" in inputs.evidence
    assert inputs.grimoire  # grimoire.md was read (non-empty)


def test_load_inputs_indexes_real_line_numbers(repo: FsWorkspaceRepository) -> None:
    inputs = repo.load_inputs(SLUG)
    # Line 16 of the fixture master resume is the billing-migration bullet.
    ev = inputs.evidence_pool["master-resume.md L16"]
    assert "billing platform from a monolith" in ev.text
    assert ev.source == "master-resume.md L16"


def test_load_inputs_skips_blank_lines_but_keeps_numbering(repo: FsWorkspaceRepository) -> None:
    inputs = repo.load_inputs(SLUG)
    # No blank line should ever be indexed.
    assert all(ev.text.strip() for ev in inputs.evidence_pool.values())
    # Line 1 is the "# Jordan Rivera" heading (first non-blank line).
    assert inputs.evidence_pool["master-resume.md L1"].text == "# Jordan Rivera"


def test_load_inputs_indexes_evidence_md_lines(repo: FsWorkspaceRepository) -> None:
    ev = repo.load_inputs(SLUG).evidence_pool["evidence.md L13"]
    assert ev.text.startswith("- On-call: idempotency keys")
    assert ev.source == "evidence.md L13"


# --- resolve_citation ------------------------------------------------------
# The grammar itself is tested in the plugin's tests/test_citations.py; here, the web
# repository's contract: the same lines as the plugin, wrapped as pooled or ungrounded Evidence.


@pytest.mark.parametrize(
    "citation",
    [
        "master-resume.md L16; evidence.md - on-call",
        "master-resume.md L14-16, L17",
        "evidence.md - Project receipts",
        "master-resume.md L16; notes.md",
        "master-resume.md L999",
    ],
    ids=["mixed-files", "range-then-bare-line", "evidence-heading", "partial-list", "missing-line"],
)
def test_resolve_citation_cites_the_same_lines_as_the_plugin_grammar(
    repo: FsWorkspaceRepository, workspace: Path, citation: str
) -> None:
    app_dir = workspace / "applications" / SLUG
    lines = citations.pool_lines(
        (workspace / "master-resume.md").read_text(), (app_dir / "evidence.md").read_text()
    )
    items = resolve_citation(citation, repo.load_inputs(SLUG).evidence_pool)
    assert [(e.id, e.grounded) for e in items] == list(citations.resolve_citation(citation, lines))


def test_resolve_citation_wraps_pooled_and_unresolved_references(repo: FsWorkspaceRepository) -> None:
    pool = repo.load_inputs(SLUG).evidence_pool
    pooled, unresolved = resolve_citation("master-resume.md L16; notes.md", pool)
    assert pooled is pool["master-resume.md L16"]
    assert unresolved == Evidence(id="notes.md", text="notes.md", source="notes.md", grounded=False)


# --- outline round-trip ----------------------------------------------------


def test_load_outline_returns_none_when_absent(repo: FsWorkspaceRepository) -> None:
    assert repo.load_outline(SLUG) is None


def test_outline_round_trip(repo: FsWorkspaceRepository) -> None:
    outline = _sample_outline()
    repo.save_outline(SLUG, outline)
    loaded = repo.load_outline(SLUG)
    assert loaded == outline


def test_save_outline_uses_pipeline_schema_keys(repo: FsWorkspaceRepository, workspace: Path) -> None:
    import json

    repo.save_outline(SLUG, _sample_outline())
    data = json.loads((workspace / "applications" / SLUG / "outline.json").read_text())
    assert set(data) == {
        "strategic_frame",
        "frame_rationale",
        "company",
        "role_title",
        "cover_letter_units",
        "resume_units",
    }
    # Persisted units carry only unit_id + description (kind is inferred on load).
    assert set(data["cover_letter_units"][0]) == {"unit_id", "description"}


def test_load_outline_infers_kind_from_prefix(repo: FsWorkspaceRepository) -> None:
    repo.save_outline(SLUG, _sample_outline())
    loaded = repo.load_outline(SLUG)
    assert loaded is not None
    assert loaded.cover_letter_units[0].kind == "cover_paragraph"
    assert loaded.resume_units[0].kind == "resume_bullet"


def test_load_outline_raises_on_malformed_json(repo: FsWorkspaceRepository, workspace: Path) -> None:
    # A crash mid-write (or a hand-edited file) leaves invalid JSON on disk; that must
    # surface as a real error, not a silently empty/default outline.
    path = workspace / "applications" / SLUG / "outline.json"
    path.write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        repo.load_outline(SLUG)


def test_repository_methods_reject_a_path_traversal_slug(repo: FsWorkspaceRepository) -> None:
    with pytest.raises(ValueError, match="Invalid slug"):
        repo.load_outline("../../etc")
    with pytest.raises(ValueError, match="Invalid slug"):
        repo.save_jd("..", "some jd text")


# --- save_variants / load_application --------------------------------------


def _sample_units(inputs_pool: dict[str, Evidence]) -> list[Unit]:
    mig = inputs_pool["master-resume.md L16"]
    roll = inputs_pool["master-resume.md L17"]
    return [
        Unit(
            id="cover_letter.opening",
            kind="cover_paragraph",
            label="Opening",
            context="Open on the platform migration as the proof of leverage.",
            variants=[
                Variant(id="cover_letter.opening#1", text="I led the migration end to end.", evidence_items=(mig,)),
                Variant(id="cover_letter.opening#2", text="The migration cut invoicing to seconds.", evidence_items=(roll,)),
            ],
        ),
        Unit(
            id="resume.northwind.billing.bullet_1",
            kind="resume_bullet",
            label="Bullet 1",
            context="Surface the monolith-to-events migration.",
            variants=[
                Variant(id="resume.northwind.billing.bullet_1#1", text="- Led the billing migration.", evidence_items=(mig,)),
            ],
        ),
    ]


def test_save_variants_then_load_application_round_trips(repo: FsWorkspaceRepository) -> None:
    repo.save_outline(SLUG, _sample_outline())
    pool = repo.load_inputs(SLUG).evidence_pool
    repo.save_variants(SLUG, _sample_units(pool))

    app = repo.load_application(SLUG)
    assert app.slug == SLUG
    assert app.company == "Globex"
    assert app.role == "Staff Platform Engineer"
    assert app.frame.name == "Force multiplier"
    assert app.frame.rationale.startswith("Globex is a platform company")
    assert "Globex" in app.jd_excerpt or "platform" in app.jd_excerpt

    # Units in outline document order: cover first, then resume.
    assert [u.id for u in app.units] == [
        "cover_letter.opening",
        "cover_letter.evidence",
        "resume.northwind.billing.bullet_1",
    ]
    cover = app.units[0]
    assert cover.kind == "cover_paragraph"
    assert cover.context == "Open on the platform migration as the proof of leverage."
    assert [v.id for v in cover.variants] == [
        "cover_letter.opening#1",
        "cover_letter.opening#2",
    ]
    assert cover.variants[0].text == "I led the migration end to end."


def test_load_application_resolves_l_citation_to_real_line(repo: FsWorkspaceRepository) -> None:
    repo.save_outline(SLUG, _sample_outline())
    pool = repo.load_inputs(SLUG).evidence_pool
    repo.save_variants(SLUG, _sample_units(pool))

    app = repo.load_application(SLUG)
    trace = app.units[0].variants[0].evidence()
    assert len(trace) == 1
    assert trace[0].id == "master-resume.md L16"
    assert "billing platform from a monolith" in trace[0].text
    # A resolved L-citation is grounded: its text is a genuine pooled quote.
    assert trace[0].grounded is True
    # The resolved evidence is the same instance shared in the application pool.
    assert app.evidence[trace[0].id] is trace[0]


def test_load_application_unresolvable_citation_renders_truthfully(repo: FsWorkspaceRepository) -> None:
    repo.save_outline(SLUG, _sample_outline())
    pool = repo.load_inputs(SLUG).evidence_pool
    units = _sample_units(pool)
    # Replace one variant's evidence with a citation to a file outside the evidence pool.
    units[0].variants[0] = Variant(
        id="cover_letter.opening#1",
        text="A grounded paragraph.",
        evidence_items=(Evidence(id="notes.md - side project", text="x", source="y"),),
    )
    repo.save_variants(SLUG, units)

    app = repo.load_application(SLUG)
    trace = app.units[0].variants[0].evidence()
    assert trace[0].id == "notes.md - side project"
    assert trace[0].text == "notes.md - side project"
    assert trace[0].source == "notes.md - side project"
    # An unresolved / free-form citation is NOT grounded: the UI must not present its
    # "text" (which is only the citation string) as a verified quote.
    assert trace[0].grounded is False


def test_load_application_grounds_every_line_of_a_multi_citation(repo: FsWorkspaceRepository) -> None:
    repo.save_outline(SLUG, _sample_outline())
    pool = repo.load_inputs(SLUG).evidence_pool
    units = _sample_units(pool)
    units[0].variants[0] = Variant(
        id="cover_letter.opening#1",
        text="I led the migration and cut paging 60%.",
        evidence_items=(pool["master-resume.md L16"], pool["evidence.md L13"]),
    )
    repo.save_variants(SLUG, units)

    app = repo.load_application(SLUG)
    trace = app.units[0].variants[0].evidence()
    assert [e.id for e in trace] == ["master-resume.md L16", "evidence.md L13"]
    assert all(e.grounded and app.evidence[e.id] is e for e in trace)


def test_save_variants_with_no_evidence_cites_master_resume(repo: FsWorkspaceRepository, workspace: Path) -> None:
    repo.save_outline(SLUG, _sample_outline())
    units = [
        Unit(
            id="cover_letter.opening",
            kind="cover_paragraph",
            label="Opening",
            context="",
            variants=[Variant(id="cover_letter.opening#1", text="No citation here.", evidence_items=())],
        ),
    ]
    repo.save_variants(SLUG, units)
    text = (workspace / "applications" / SLUG / "variants.md").read_text()
    assert "### Variant 1: master-resume.md" in text


def test_save_variants_writes_expected_structure(repo: FsWorkspaceRepository, workspace: Path) -> None:
    repo.save_outline(SLUG, _sample_outline())
    pool = repo.load_inputs(SLUG).evidence_pool
    repo.save_variants(SLUG, _sample_units(pool))
    text = (workspace / "applications" / SLUG / "variants.md").read_text()
    assert text.startswith("# Conjurer Variants")
    assert "## Unit: cover_letter.opening" in text
    assert "<!-- conjurer:unit id=cover_letter.opening -->" in text
    assert "### Variant 1: master-resume.md L16" in text
    assert "*Axis:" in text
    assert "- [ ] Pick" in text


# --- set_pick / get_picks --------------------------------------------------


def test_set_pick_marks_exactly_one_and_get_picks_reflects_it(repo: FsWorkspaceRepository) -> None:
    repo.save_outline(SLUG, _sample_outline())
    pool = repo.load_inputs(SLUG).evidence_pool
    repo.save_variants(SLUG, _sample_units(pool))

    assert repo.get_picks(SLUG) == {}  # nothing picked yet

    repo.set_pick(SLUG, "cover_letter.opening", "cover_letter.opening#2")
    assert repo.get_picks(SLUG) == {"cover_letter.opening": "cover_letter.opening#2"}


def test_set_pick_twice_moves_the_pick(repo: FsWorkspaceRepository) -> None:
    repo.save_outline(SLUG, _sample_outline())
    pool = repo.load_inputs(SLUG).evidence_pool
    repo.save_variants(SLUG, _sample_units(pool))

    repo.set_pick(SLUG, "cover_letter.opening", "cover_letter.opening#1")
    assert repo.get_picks(SLUG) == {"cover_letter.opening": "cover_letter.opening#1"}

    repo.set_pick(SLUG, "cover_letter.opening", "cover_letter.opening#2")
    assert repo.get_picks(SLUG) == {"cover_letter.opening": "cover_letter.opening#2"}


def test_set_pick_does_not_corrupt_other_units(repo: FsWorkspaceRepository) -> None:
    repo.save_outline(SLUG, _sample_outline())
    pool = repo.load_inputs(SLUG).evidence_pool
    repo.save_variants(SLUG, _sample_units(pool))

    repo.set_pick(SLUG, "cover_letter.opening", "cover_letter.opening#1")
    repo.set_pick(SLUG, "resume.northwind.billing.bullet_1", "resume.northwind.billing.bullet_1#1")
    picks = repo.get_picks(SLUG)
    assert picks == {
        "cover_letter.opening": "cover_letter.opening#1",
        "resume.northwind.billing.bullet_1": "resume.northwind.billing.bullet_1#1",
    }


def test_colonless_variant_header_keeps_pick_citation_and_text(
    repo: FsWorkspaceRepository, workspace: Path
) -> None:
    repo.save_outline(SLUG, _sample_outline())
    pool = repo.load_inputs(SLUG).evidence_pool
    repo.save_variants(SLUG, _sample_units(pool))
    path = workspace / "applications" / SLUG / "variants.md"
    text = path.read_text().replace(
        "### Variant 2: master-resume.md L17", "### Variant 2 master-resume.md L17"
    )
    path.write_text(text)

    repo.set_pick(SLUG, "cover_letter.opening", "cover_letter.opening#2")

    assert repo.get_picks(SLUG) == {"cover_letter.opening": "cover_letter.opening#2"}
    variant = repo.load_application(SLUG).units[0].variants[1]
    assert variant.id == "cover_letter.opening#2"
    assert variant.text == "The migration cut invoicing to seconds."
    assert [item.id for item in variant.evidence()] == ["master-resume.md L17"]
    assert variant.evidence()[0].grounded is True


def test_relayed_block_survives_save_then_load_application(repo: FsWorkspaceRepository) -> None:
    # Cross-parser round-trip: the SDK adapter parses a relayed variant-generator block into
    # domain Units, the repository writes them to variants.md, and load_application reads them
    # back — the citation and text must survive both parsers intact.
    from app.adapters.generation_sdk import variants_from_block
    from app.domain import OutlineUnit, Unit, label_for_unit_id

    repo.save_outline(SLUG, _sample_outline())
    unit_ou = OutlineUnit(
        unit_id="resume.northwind.billing.bullet_1",
        kind="resume_bullet",
        description="Surface the monolith-to-events migration.",
    )
    block = (
        "Dispatching the variant-generator now.\n"
        "## Unit: resume.northwind.billing.bullet_1\n"
        "<!-- conjurer:unit id=resume.northwind.billing.bullet_1 -->\n"
        "### Variant 1: master-resume.md L16\n\n"
        "- Architected the billing-platform migration to event-driven services,\n"
        "  cutting invoice latency from 40s to under 2s across three regions.\n\n"
        "*Axis: outcome-led*\n\n"
        "- [ ] Pick\n\n"
        "### Variant 2: master-resume.md L17\n\n"
        "- Led the platform migration onto an event-driven backbone.\n\n"
        "*Axis: ownership-led*\n\n"
        "- [ ] Pick\n"
    )
    parsed_variants = variants_from_block(block, unit_ou)
    units = [
        Unit(
            id=unit_ou.unit_id,
            kind=unit_ou.kind,
            label=label_for_unit_id(unit_ou.unit_id),
            context=unit_ou.description,
            variants=parsed_variants,
        )
    ]
    repo.save_variants(SLUG, units)

    app = repo.load_application(SLUG)
    bullet = next(u for u in app.units if u.id == "resume.northwind.billing.bullet_1")
    assert [v.id for v in bullet.variants] == [
        "resume.northwind.billing.bullet_1#1",
        "resume.northwind.billing.bullet_1#2",
    ]
    # Text survives the round-trip (the Axis/Pick scaffolding is stripped, the body kept).
    assert "Architected the billing-platform migration" in bullet.variants[0].text
    assert "across three regions" in bullet.variants[0].text
    assert "Axis" not in bullet.variants[0].text and "Pick" not in bullet.variants[0].text
    # The L-citation resolves back to the real master-resume line, grounded.
    trace = bullet.variants[0].evidence()
    assert trace[0].id == "master-resume.md L16"
    assert trace[0].grounded is True
    assert "billing platform from a monolith" in trace[0].text


def test_load_application_without_outline_raises(repo: FsWorkspaceRepository) -> None:
    with pytest.raises(FileNotFoundError, match="No outline.json"):
        repo.load_application(SLUG)


# --- metrics round-trip ----------------------------------------------------


def _sample_metrics() -> RunMetrics:
    return RunMetrics(
        slug=SLUG,
        steps=[
            StepMetrics(
                name="outline",
                wall_ms=500,
                call=CallMetrics(cost_usd=0.1, cache_creation_tokens=12000),
            ),
            StepMetrics(
                name="resume.northwind.billing.bullet_1",
                wall_ms=300,
                call=CallMetrics(cost_usd=0.02, cache_read_tokens=8000, cache_creation_tokens=200),
            ),
        ],
    )


def test_load_metrics_returns_none_when_absent(repo: FsWorkspaceRepository) -> None:
    assert repo.load_metrics(SLUG) is None


def test_metrics_round_trip(repo: FsWorkspaceRepository, workspace: Path) -> None:
    metrics = _sample_metrics()
    repo.save_metrics(SLUG, metrics)
    assert (workspace / "applications" / SLUG / "metrics.json").exists()
    loaded = repo.load_metrics(SLUG)
    assert loaded == metrics


def test_load_metrics_raises_on_malformed_json(repo: FsWorkspaceRepository, workspace: Path) -> None:
    path = workspace / "applications" / SLUG / "metrics.json"
    path.write_text("not json at all")
    with pytest.raises(json.JSONDecodeError):
        repo.load_metrics(SLUG)


def test_save_jd_creates_app_dir_and_normalizes_newline(tmp_path: Path) -> None:
    # Fresh workspace with no applications/<slug>/ yet; save_jd must create it.
    repo = FsWorkspaceRepository(tmp_path)
    jd_path = tmp_path / "applications" / SLUG / "jd.txt"

    repo.save_jd(SLUG, "Staff Platform Engineer at Globex")  # no trailing newline
    assert jd_path.read_text() == "Staff Platform Engineer at Globex\n"

    repo.save_jd(SLUG, "Already newline-terminated\n")  # trailing newline preserved, not doubled
    assert jd_path.read_text() == "Already newline-terminated\n"


# --- support.json ------------------------------------------------------------

PIPELINE_MD = (
    Path(__file__).resolve().parents[2]
    / "plugins" / "conjurer" / "skills" / "conjurer" / "references" / "pipeline.md"
)


def _cli_rows(workspace: Path, verdicts: dict[str, tuple[str, list[str]]]) -> dict[str, dict]:
    """support.json rows fingerprinted the way the CLI claim check does, from variants.md on disk."""
    app_dir = workspace / "applications" / SLUG
    lines = citations.pool_lines(
        (workspace / "master-resume.md").read_text(), (app_dir / "evidence.md").read_text()
    )
    rows = {}
    for variant_id, variant in verify.variant_targets((app_dir / "variants.md").read_text()):
        if variant_id not in verdicts:
            continue
        verdict, numbers = verdicts[variant_id]
        cited = [
            lines[line.id]
            for line in citations.resolve_citation(variant.citation, lines)
            if line.grounded
        ]
        rows[variant_id] = {
            "verdict": verdict,
            "relation": "partly_supports",
            "relation_confidence": 1.0,
            "unstated": 0.94,
            "unsourced_numbers": numbers,
            "fingerprint": verify.fingerprint(variant.content, cited),
        }
    return rows


def _write_support(workspace: Path, rows: dict[str, dict]) -> None:
    document = {"model": verify.JEV_MODEL, "variants": rows}
    (workspace / "applications" / SLUG / "support.json").write_text(json.dumps(document))


def test_load_support_is_empty_without_support_json(repo: FsWorkspaceRepository) -> None:
    assert repo.load_support(SLUG) == {}


def test_save_support_stamps_fingerprints_that_load_application_matches(
    repo: FsWorkspaceRepository, workspace: Path
) -> None:
    repo.save_outline(SLUG, _sample_outline())
    repo.save_variants(SLUG, _sample_units(repo.load_inputs(SLUG).evidence_pool))
    support = {
        "cover_letter.opening#1": Support(
            verdict="adds_detail",
            note=verify.note_for("adds_detail", ["12"]),
            unsourced_numbers=("12",),
            relation="partly_supports",
            relation_confidence=1.0,
            unstated=0.94,
        ),
        "cover_letter.opening#2": Support(verdict="unchecked", note=verify.NOTES["unchecked"]),
        "resume.northwind.billing.bullet_1#9": Support(verdict="traced"),
    }
    pool = repo.load_inputs(SLUG).evidence_pool
    repo.save_support(SLUG, support, _sample_units(pool), pool)

    cli = _cli_rows(workspace, {"cover_letter.opening#1": ("", []), "cover_letter.opening#2": ("", [])})
    stamped = {
        variant_id: replace(support[variant_id], fingerprint=row["fingerprint"])
        for variant_id, row in cli.items()
    }
    stamped["resume.northwind.billing.bullet_1#9"] = Support(verdict="traced", fingerprint="")
    assert repo.load_support(SLUG) == stamped
    variants = {v.id: v for unit in repo.load_application(SLUG).units for v in unit.variants}
    assert variants["cover_letter.opening#1"].support == stamped["cover_letter.opening#1"]
    assert variants["cover_letter.opening#2"].support == stamped["cover_letter.opening#2"]


def test_save_support_writes_the_documented_support_json(
    repo: FsWorkspaceRepository, workspace: Path
) -> None:
    repo.save_outline(SLUG, _sample_outline())
    repo.save_variants(SLUG, _sample_units(repo.load_inputs(SLUG).evidence_pool))
    pool = repo.load_inputs(SLUG).evidence_pool
    support = {"cover_letter.opening#1": Support(verdict="unchecked")}
    repo.save_support(SLUG, support, _sample_units(pool), pool)
    document = json.loads((workspace / "applications" / SLUG / "support.json").read_text())
    jsonschema.validate(document, SUPPORT_SCHEMA)
    assert document["model"] == verify.JEV_MODEL
    assert document["variants"]["cover_letter.opening#1"]["verdict"] == "unchecked"


def test_support_schema_validates_the_documented_example() -> None:
    section = PIPELINE_MD.read_text().split("### support.json", 1)[1]
    example = json.loads(section.split("```json", 1)[1].split("```", 1)[0])
    jsonschema.validate(example, SUPPORT_SCHEMA)
    row_schema = SUPPORT_SCHEMA["properties"]["variants"]["additionalProperties"]
    assert set(row_schema["properties"]["verdict"]["enum"]) == set(verify.VERDICTS)
    assert set(get_args(SupportVerdict)) == set(verify.VERDICTS)


def test_load_application_attaches_only_verdicts_whose_fingerprint_matches(
    repo: FsWorkspaceRepository, workspace: Path
) -> None:
    repo.save_outline(SLUG, _sample_outline())
    repo.save_variants(SLUG, _sample_units(repo.load_inputs(SLUG).evidence_pool))
    rows = _cli_rows(
        workspace,
        {
            "cover_letter.opening#1": ("adds_detail", ["12"]),
            "cover_letter.opening#2": ("conflicts", []),
            "resume.northwind.billing.bullet_1#1": ("traced", []),
        },
    )
    rows["cover_letter.opening#2"]["fingerprint"] = verify.fingerprint("an edited claim", [])
    _write_support(workspace, rows)

    variants = {v.id: v for unit in repo.load_application(SLUG).units for v in unit.variants}

    assert variants["cover_letter.opening#1"].support == Support(
        verdict="adds_detail",
        note="Adds detail your evidence doesn't state: 12",
        unsourced_numbers=("12",),
        relation="partly_supports",
        relation_confidence=1.0,
        unstated=0.94,
        fingerprint=rows["cover_letter.opening#1"]["fingerprint"],
    )
    assert variants["cover_letter.opening#2"].support is None
    traced = variants["resume.northwind.billing.bullet_1#1"].support
    assert traced is not None and traced.verdict == "traced" and traced.note is None


def test_load_application_without_support_json_attaches_no_verdicts(repo: FsWorkspaceRepository) -> None:
    repo.save_outline(SLUG, _sample_outline())
    repo.save_variants(SLUG, _sample_units(repo.load_inputs(SLUG).evidence_pool))
    app = repo.load_application(SLUG)
    assert [v.support for unit in app.units for v in unit.variants] == [None, None, None]


@pytest.mark.parametrize(
    "content",
    [
        "{truncated",
        '{"model": "jev-1.13.0"}',
        '{"model": "jev-1.13.0", "variants": {"cover_letter.opening#1": "x"}}',
        '{"model": "jev-1.13.0", "variants": []}',
    ],
    ids=["truncated-json", "no-variants-key", "row-not-an-object", "variants-not-an-object"],
)
def test_unreadable_support_json_loads_as_no_verdicts_and_says_so(
    repo: FsWorkspaceRepository, workspace: Path, caplog: pytest.LogCaptureFixture, content: str
) -> None:
    repo.save_outline(SLUG, _sample_outline())
    repo.save_variants(SLUG, _sample_units(repo.load_inputs(SLUG).evidence_pool))
    (workspace / "applications" / SLUG / "support.json").write_text(content)

    app = repo.load_application(SLUG)

    assert [v.support for unit in app.units for v in unit.variants] == [None, None, None]
    assert f"unreadable support.json for slug={SLUG}" in caplog.text


def test_save_support_fingerprints_a_saved_transient_citation_like_the_cli(
    repo: FsWorkspaceRepository, workspace: Path
) -> None:
    # Generation hands back each variant's citation unresolved; its fingerprint must still be
    # the one the CLI computes from variants.md once the variant is saved.
    citation = "master-resume.md L16; evidence.md L13; notes.md - side project"
    variant = Variant(
        id="cover_letter.opening#1",
        text="I led the migration and cut paging 60%.",
        evidence_items=(Evidence(id=citation, text=citation, source=citation, grounded=False),),
    )
    repo.save_outline(SLUG, _sample_outline())
    unit = Unit(id="cover_letter.opening", kind="cover_paragraph", label="Opening", context="c", variants=[variant])
    repo.save_variants(SLUG, [unit])
    repo.save_support(SLUG, {variant.id: Support(verdict="traced")}, [unit], repo.load_inputs(SLUG).evidence_pool)
    expected = _cli_rows(workspace, {variant.id: ("traced", [])})[variant.id]["fingerprint"]
    assert repo.load_support(SLUG)[variant.id].fingerprint == expected


@pytest.mark.parametrize(
    ("opening_verdicts", "opening_note"),
    [
        pytest.param(
            {"cover_letter.opening#1": ("adds_detail", ["12"]), "cover_letter.opening#2": ("conflicts", [])},
            "None of these lines is fully backed by your evidence. Add the fact to your master resume, "
            "or pick the closest and edit it.",
            id="every-variant-flagged-gets-the-note",
        ),
        pytest.param(
            {"cover_letter.opening#1": ("adds_detail", ["12"]), "cover_letter.opening#2": ("traced", [])},
            None,
            id="one-unflagged-variant-no-note",
        ),
        pytest.param(
            {"cover_letter.opening#1": ("adds_detail", ["12"])},
            None,
            id="one-variant-unchecked-by-absence-no-note",
        ),
    ],
)
def test_load_application_notes_a_unit_whose_every_variant_is_flagged(
    repo: FsWorkspaceRepository,
    workspace: Path,
    opening_verdicts: dict[str, tuple[str, list[str]]],
    opening_note: str | None,
) -> None:
    repo.save_outline(SLUG, _sample_outline())
    empty = Unit(id="resume.northwind.billing.bullet_2", kind="resume_bullet", label="Bullet 2", context="c", variants=[])
    repo.save_variants(SLUG, [*_sample_units(repo.load_inputs(SLUG).evidence_pool), empty])
    _write_support(workspace, _cli_rows(workspace, opening_verdicts))

    notes = {unit.id: unit.grounding_note for unit in repo.load_application(SLUG).units}

    assert notes == {
        "cover_letter.opening": opening_note,
        "cover_letter.evidence": None,
        "resume.northwind.billing.bullet_1": None,
        "resume.northwind.billing.bullet_2": None,
    }


@pytest.mark.parametrize("has_fingerprint", [False, True], ids=["fallback", "checked"])
def test_save_support_keeps_the_checked_snapshot_after_workspace_edits(repo, workspace, has_fingerprint):
    pool = repo.load_inputs(SLUG).evidence_pool
    units = _sample_units(pool)
    variant = units[0].variants[0]
    cited = [item.text for item in variant.evidence_items]
    fingerprint = verify.fingerprint(variant.text, cited)
    support = Support(verdict="traced", fingerprint=fingerprint if has_fingerprint else "")
    repo.save_outline(SLUG, _sample_outline())
    repo.save_variants(SLUG, units)
    master = workspace / "master-resume.md"
    master.write_text(master.read_text().replace("billing platform from a monolith", "an unrelated project"))

    repo.save_support(SLUG, {variant.id: support}, units, pool)

    assert repo.load_support(SLUG)[variant.id].fingerprint == fingerprint
    loaded = repo.load_application(SLUG)
    assert loaded.units[0].variants[0].support is None


def test_support_directory_does_not_block_loading_application(repo, workspace, caplog):
    repo.save_outline(SLUG, _sample_outline())
    repo.save_variants(SLUG, _sample_units(repo.load_inputs(SLUG).evidence_pool))
    (workspace / "applications" / SLUG / "support.json").mkdir()

    app = repo.load_application(SLUG)

    assert all(v.support is None for unit in app.units for v in unit.variants)
    assert f"unreadable support.json for slug={SLUG}" in caplog.text


def test_support_stat_failure_is_advisory(repo, monkeypatch, caplog):
    original_exists = Path.exists

    def exists(path):
        if path.name == "support.json":
            raise PermissionError("support directory is inaccessible")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", exists)
    assert repo.load_support(SLUG) == {}
    assert "support directory is inaccessible" in caplog.text


def test_save_support_preserves_a_verifiers_fingerprint_for_an_edited_claim(repo):
    pool = repo.load_inputs(SLUG).evidence_pool
    units = _sample_units(pool)
    variant = units[0].variants[0]
    checked_fingerprint = verify.fingerprint(variant.text, [item.text for item in variant.evidence_items])
    units[0].variants[0] = replace(variant, text="An edited claim after checking")
    repo.save_outline(SLUG, _sample_outline())
    repo.save_variants(SLUG, units)

    repo.save_support(
        SLUG, {variant.id: Support(verdict="traced", fingerprint=checked_fingerprint)}, units, pool
    )

    assert repo.load_support(SLUG)[variant.id].fingerprint == checked_fingerprint
    assert repo.load_application(SLUG).units[0].variants[0].support is None


def test_load_inputs_without_optional_evidence_keeps_resume_line_contract(repo, workspace):
    (workspace / "applications" / SLUG / "evidence.md").unlink()
    inputs = repo.load_inputs(SLUG)
    assert inputs.evidence == ""
    assert "master-resume.md L16" in inputs.evidence_pool
    assert all(not key.startswith("evidence.md ") for key in inputs.evidence_pool)


def test_targeted_write_preserves_unrelated_pick_bytes(repo, workspace):
    repo.save_outline(SLUG, _sample_outline())
    units = _sample_units(repo.load_inputs(SLUG).evidence_pool)
    repo.save_variants(SLUG, units)
    repo.set_pick(SLUG, units[0].id, units[0].variants[1].id)
    path = workspace / "applications" / SLUG / "variants.md"
    before = path.read_text().split("## Unit: " + units[1].id)[0]
    repo.save_unit_variants(SLUG, units[1])
    assert path.read_text().split("## Unit: " + units[1].id)[0] == before
    assert repo.get_picks(SLUG) == {units[0].id: units[0].variants[1].id}


def test_targeted_write_failure_preserves_saved_variants(repo, workspace, monkeypatch):
    repo.save_outline(SLUG, _sample_outline())
    units = _sample_units(repo.load_inputs(SLUG).evidence_pool)
    repo.save_variants(SLUG, units)
    path = workspace / "applications" / SLUG / "variants.md"
    before = path.read_bytes()
    def fails(source, target):
        raise OSError("disk unavailable")
    monkeypatch.setattr(os, "replace", fails)
    with pytest.raises(OSError, match="disk unavailable"):
        repo.save_unit_variants(SLUG, units[0])
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["evidence.md", "jd.txt", "outline.json", "variants.md"]


@pytest.mark.parametrize("previous", [True, False])
def test_initialization_failure_keeps_previous_outline_and_drafts(repo, workspace, monkeypatch, caplog, previous):
    repo.save_outline(SLUG, _sample_outline())
    units = _sample_units(repo.load_inputs(SLUG).evidence_pool)
    repo.save_variants(SLUG, units)
    repo.set_pick(SLUG, units[0].id, units[0].variants[0].id)
    outline_path = workspace / "applications" / SLUG / "outline.json"
    variants_path = outline_path.with_name("variants.md")
    before = (outline_path.read_bytes(), variants_path.read_bytes())
    if not previous:
        outline_path.unlink()
        variants_path.unlink()
        before = (None, None)
    real_replace = os.replace
    def fails_reset(source, target):
        if Path(target) == variants_path:
            raise OSError("reset denied")
        return real_replace(source, target)
    monkeypatch.setattr(os, "replace", fails_reset)
    class AnotherCompany(FakeGenerationPort):
        async def outline(self, slug):
            return replace(await super().outline(slug), company="Another company")
    manager = RunManager(repo, AnotherCompany(), NoVerificationPort())
    async def start():
        manager.start(SLUG)
        await manager.join(SLUG)
    asyncio.run(start())
    assert manager.status(SLUG).state == "error"
    assert (outline_path.read_bytes() if outline_path.exists() else None, variants_path.read_bytes() if variants_path.exists() else None) == before
    assert "generation run failed" in caplog.text

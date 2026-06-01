# ABOUTME: Tests for FsWorkspaceRepository — the filesystem workspace adapter.
# ABOUTME: Round-trips outline.json and variants.md against a tmp copy of the fixture workspace.

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.adapters.workspace_fs import FsWorkspaceRepository, default_repository
from app.domain import Outline, OutlineUnit, Unit, Variant, Evidence

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
    # Replace one variant's evidence with a free-form citation that is not an L<n> id.
    units[0].variants[0] = Variant(
        id="cover_letter.opening#1",
        text="A grounded paragraph.",
        evidence_items=(Evidence(id="evidence.md - billing migration", text="x", source="y"),),
    )
    repo.save_variants(SLUG, units)

    app = repo.load_application(SLUG)
    trace = app.units[0].variants[0].evidence()
    assert trace[0].id == "evidence.md - billing migration"
    assert trace[0].text == "evidence.md - billing migration"
    assert trace[0].source == "evidence.md - billing migration"
    # An unresolved / free-form citation is NOT grounded: the UI must not present its
    # "text" (which is only the citation string) as a verified quote.
    assert trace[0].grounded is False


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


def test_load_application_without_outline_raises(repo: FsWorkspaceRepository) -> None:
    with pytest.raises(FileNotFoundError, match="No outline.json"):
        repo.load_application(SLUG)


# --- default_repository ----------------------------------------------------


def test_default_repository_uses_env_when_set(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    monkeypatch.setenv("CONJURER_WORKSPACE", str(workspace))
    repo = default_repository()
    assert repo.root == workspace


def test_default_repository_falls_back_to_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONJURER_WORKSPACE", raising=False)
    repo = default_repository()
    assert repo.root == FIXTURE_WORKSPACE.resolve()

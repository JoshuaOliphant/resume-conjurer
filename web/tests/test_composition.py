# ABOUTME: Tests for ScriptCompositionPort — the stitch/lint/export composition adapter.
# ABOUTME: Drives the deterministic conjurer scripts against a tmp copy of the fixture workspace.

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import sys

from app.adapters.composition import ScriptCompositionPort, _ensure_scripts_on_path
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.domain import LintCheck, Unit, Variant

SLUG = "globex-staff-platform"
FIXTURE_WORKSPACE = Path(__file__).parent / "fixtures" / "workspace"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    shutil.copytree(FIXTURE_WORKSPACE, root)
    return root


@pytest.fixture
def repo(workspace: Path) -> FsWorkspaceRepository:
    return FsWorkspaceRepository(workspace)


@pytest.fixture
def port(workspace: Path) -> ScriptCompositionPort:
    return ScriptCompositionPort(workspace)


def _units_with_lint_trip() -> list[Unit]:
    """One cover unit whose picked variant trips a grimoire rule, plus one resume unit."""
    return [
        Unit(
            id="cover_letter.opening",
            kind="cover_paragraph",
            label="Opening",
            context="",
            variants=[
                Variant(id="cover_letter.opening#1", text="I just led the billing migration.", evidence_items=()),
                Variant(id="cover_letter.opening#2", text="I led the billing migration end to end.", evidence_items=()),
            ],
        ),
        Unit(
            id="resume.northwind.billing.bullet_1",
            kind="resume_bullet",
            label="Bullet 1",
            context="",
            variants=[
                Variant(id="resume.northwind.billing.bullet_1#1", text="- Led the billing platform migration.", evidence_items=()),
            ],
        ),
    ]


def _prepare_picks(repo: FsWorkspaceRepository, slug: str) -> None:
    """Write variants and pick exactly one variant for every unit (stitch needs all picked)."""
    repo.save_variants(slug, _units_with_lint_trip())
    repo.set_pick(slug, "cover_letter.opening", "cover_letter.opening#1")
    repo.set_pick(slug, "resume.northwind.billing.bullet_1", "resume.northwind.billing.bullet_1#1")


def test_ensure_scripts_on_path_adds_once(tmp_path: Path) -> None:
    fresh = tmp_path / "scripts"
    assert str(fresh) not in sys.path
    _ensure_scripts_on_path(fresh)  # absent -> appended
    assert sys.path.count(str(fresh)) == 1
    _ensure_scripts_on_path(fresh)  # present -> no duplicate
    assert sys.path.count(str(fresh)) == 1
    sys.path.remove(str(fresh))


def test_stitch_writes_cover_and_resume_with_picked_content(
    repo: FsWorkspaceRepository, port: ScriptCompositionPort, workspace: Path
) -> None:
    _prepare_picks(repo, SLUG)
    port.stitch(SLUG)

    app_dir = workspace / "applications" / SLUG
    cover = (app_dir / "cover_letter.md").read_text()
    resume = (app_dir / "resume.md").read_text()
    assert "I just led the billing migration." in cover
    assert "Led the billing platform migration." in resume


def test_lint_surfaces_finding_from_stitched_cover(
    repo: FsWorkspaceRepository, port: ScriptCompositionPort
) -> None:
    _prepare_picks(repo, SLUG)
    port.stitch(SLUG)
    checks = port.lint(SLUG)
    assert checks  # the "just" filler trips a rule
    assert all(isinstance(c, LintCheck) for c in checks)
    assert all(c.passed is False for c in checks)
    assert any("just" in c.label for c in checks)
    assert any("just led the billing migration" in c.detail for c in checks)


def test_lint_clean_documents_return_no_checks(
    repo: FsWorkspaceRepository, port: ScriptCompositionPort
) -> None:
    repo.save_variants(SLUG, _units_with_lint_trip())
    # Pick the clean cover variant (#2) this time.
    repo.set_pick(SLUG, "cover_letter.opening", "cover_letter.opening#2")
    repo.set_pick(SLUG, "resume.northwind.billing.bullet_1", "resume.northwind.billing.bullet_1#1")
    port.stitch(SLUG)
    assert port.lint(SLUG) == []


def test_export_returns_dict_and_handles_pandoc_presence(
    repo: FsWorkspaceRepository, port: ScriptCompositionPort
) -> None:
    _prepare_picks(repo, SLUG)
    port.stitch(SLUG)
    results = port.export(SLUG)
    assert isinstance(results, dict)
    assert results  # something to export after stitch
    have_pandoc = shutil.which("pandoc") is not None
    for status in results.values():
        if have_pandoc:
            assert status == "written"
        else:
            assert status.startswith("skipped")

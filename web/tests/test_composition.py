# ABOUTME: Tests for ScriptCompositionPort — the stitch/lint/export composition adapter.
# ABOUTME: Drives the deterministic conjurer scripts against a tmp copy of the fixture workspace.

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfReader

from app.adapters.composition import ScriptCompositionPort
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


def test_export_writes_readable_documents_without_pandoc(
    repo: FsWorkspaceRepository, port: ScriptCompositionPort, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare_picks(repo, SLUG)
    port.stitch(SLUG)
    monkeypatch.setattr("export_docs.pandoc_available", lambda: False)
    results = port.export(SLUG)
    assert results == {name: "written" for name in (
        "cover_letter.pdf", "cover_letter.docx", "resume.pdf", "resume.docx"
    )}
    app_dir = workspace / "applications" / SLUG
    assert "billing platform migration" in "\n".join(
        paragraph.text for paragraph in Document(str(app_dir / "resume.docx")).paragraphs
    )
    assert "billing platform migration" in "\n".join(
        page.extract_text() for page in PdfReader(app_dir / "resume.pdf").pages
    )


def test_export_reports_source_and_format_failures(port: ScriptCompositionPort, workspace: Path) -> None:
    app_dir = workspace / "applications" / SLUG
    (app_dir / "cover_letter.md").write_bytes(b"\xff")
    (app_dir / "resume.md").write_text("# Resume", encoding="utf-8")
    results = port.export(SLUG, ("pdf", "html"))
    assert results["cover_letter.pdf"].startswith("skipped: cannot read final document")
    assert results["cover_letter.html"].startswith("skipped: cannot read final document")
    assert results["resume.pdf"] == "written"
    assert results["resume.html"] == "skipped: unsupported export format"
    (app_dir / "resume.md").unlink()
    (app_dir / "cover_letter.md").unlink()
    assert port.export(SLUG) == {}


def test_failed_export_removes_stale_artifact(
    port: ScriptCompositionPort, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When export fails, any existing artifact should be removed to prevent stale files."""
    app_dir = workspace / "applications" / SLUG
    (app_dir / "resume.md").write_text("# Resume", encoding="utf-8")
    old_artifact = app_dir / "resume.pdf"
    old_artifact.write_bytes(b"previous")

    def failed_renderer(markdown: str, format_name: str, path: Path) -> None:
        path.write_bytes(b"partial")
        raise RuntimeError("render failed")

    monkeypatch.setattr("app.adapters.composition.export_document", failed_renderer)
    assert port.export(SLUG, ("pdf",)) == {"resume.pdf": "skipped: renderer failed (RuntimeError)"}
    assert not old_artifact.exists(), "stale artifact should be removed on failed export"
    assert list(app_dir.glob(".resume.*.pdf")) == []


def test_failed_publish_removes_stale_artifact(
    port: ScriptCompositionPort, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When os.replace fails, any existing artifact should be removed to prevent stale files."""
    app_dir = workspace / "applications" / SLUG
    (app_dir / "resume.md").write_text("# Resume", encoding="utf-8")
    old_artifact = app_dir / "resume.docx"
    old_artifact.write_bytes(b"previous")

    def failed_replace(source: Path, target: Path) -> None:
        raise OSError("publish failed")

    monkeypatch.setattr("app.adapters.composition.os.replace", failed_replace)
    assert port.export(SLUG, ("docx",)) == {"resume.docx": "skipped: publish failed"}
    assert not old_artifact.exists(), "stale artifact should be removed on failed publish"
    assert list(app_dir.glob(".resume.*.docx")) == []


def test_temporary_file_failure_is_reported(
    port: ScriptCompositionPort, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_dir = workspace / "applications" / SLUG
    (app_dir / "resume.md").write_text("# Resume", encoding="utf-8")
    monkeypatch.setattr("app.adapters.composition.tempfile.mkstemp", lambda **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    assert port.export(SLUG, ("pdf",)) == {"resume.pdf": "skipped: disk full"}


def test_temporary_file_cleanup_failure_is_reported(
    port: ScriptCompositionPort, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_dir = workspace / "applications" / SLUG
    (app_dir / "resume.md").write_text("# Resume", encoding="utf-8")
    real_unlink = Path.unlink

    def failed_unlink(path: Path, missing_ok: bool = False) -> None:
        if path.name.startswith(".resume."):
            raise OSError("cannot remove temporary file")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failed_unlink)
    assert port.export(SLUG, ("pdf",)) == {"resume.pdf": "skipped: temporary export cleanup failed"}


@pytest.mark.parametrize("filename", ["cover_letter.md", "resume.md", "cover_letter.pdf", "resume.docx"])
def test_download_returns_the_actual_export_file(port, workspace, filename):
    artifact = workspace / "applications" / SLUG / filename
    artifact.write_bytes(b"export artifact")
    assert port.download(SLUG, filename) == artifact.resolve()


@pytest.mark.parametrize("filename", ["../master-resume.md", "evidence.md", "metrics.json", "resume.html"])
def test_download_rejects_non_export_filenames(port, filename):
    assert port.download(SLUG, filename) is None


def test_download_rejects_missing_files_and_directories(port, workspace):
    artifact = workspace / "applications" / SLUG / "resume.pdf"
    assert port.download(SLUG, artifact.name) is None
    artifact.mkdir()
    assert port.download(SLUG, artifact.name) is None


def test_download_rejects_symlinks_outside_the_application(port, workspace):
    artifact = workspace / "applications" / SLUG / "resume.md"
    artifact.symlink_to(workspace / "master-resume.md")
    assert port.download(SLUG, artifact.name) is None
